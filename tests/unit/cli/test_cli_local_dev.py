"""Local-development CLI commands (issue #48): dev, stop, status, logs, setup, benchmark."""

from __future__ import annotations

import json
import subprocess
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sagaz.cli import _dev_cmds, _project_cmds, app

COMPOSE = "services: {}\n"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def run(monkeypatch):
    calls = MagicMock(return_value=SimpleNamespace(returncode=0, stdout=""))
    monkeypatch.setattr(subprocess, "run", calls)
    return calls


class TestDevAndStop:
    @pytest.mark.parametrize(("args", "command"), [([], ["up"]), (["-d"], ["up", "-d"])])
    def test_dev_starts_compose(self, runner, run, tmp_path, args, command):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("docker-compose.yaml").write_text(COMPOSE)
            result = runner.invoke(app.cli, ["dev", *args])
        assert result.exit_code == 0, result.output
        run.assert_called_once_with(["docker", "compose", *command], check=False)

    @pytest.mark.parametrize("command", ["dev", "stop"])
    def test_without_compose_points_to_init_local(self, runner, run, tmp_path, command):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app.cli, [command])
        assert result.exit_code == 1
        assert "docker-compose.yaml not found" in result.output
        run.assert_not_called()

    def test_dev_message_names_the_real_command(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app.cli, ["dev"])
        assert "sagaz init --local" in result.output

    def test_stop_brings_compose_down(self, runner, run, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("docker-compose.yaml").write_text(COMPOSE)
            result = runner.invoke(app.cli, ["stop"])
        assert result.exit_code == 0, result.output
        run.assert_called_once_with(["docker", "compose", "down"], check=False)


class TestStatus:
    def _status(self, runner, monkeypatch, stdout, returncode=0):
        printed = []
        console = SimpleNamespace(print=printed.append)
        monkeypatch.setattr(_dev_cmds, "console", console)
        monkeypatch.setattr(
            subprocess,
            "run",
            MagicMock(return_value=SimpleNamespace(returncode=returncode, stdout=stdout)),
        )
        result = runner.invoke(app.cli, ["status"])
        assert result.exit_code == 0, result.output
        table = printed[0]
        return [
            tuple(cell for cell in row)
            for row in zip(*(column._cells for column in table.columns), strict=True)
        ]

    def test_services_are_colour_coded_by_state(self, runner, monkeypatch):
        stdout = json.dumps({"Service": "postgres", "State": "running"}) + json.dumps(
            {"Name": "redis", "State": "exited"}
        )
        rows = self._status(runner, monkeypatch, stdout)
        assert rows == [
            ("postgres", "[green]●[/green] running", ""),
            ("redis", "[red]○[/red] exited", ""),
        ]

    def test_stack_not_running(self, runner, monkeypatch):
        rows = self._status(runner, monkeypatch, "", returncode=1)
        assert rows == [("docker-compose", "[red]○ not running[/red]", "Run 'sagaz dev'")]

    def test_unparseable_output(self, runner, monkeypatch):
        rows = self._status(runner, monkeypatch, "{not json")
        assert rows == [("docker-compose", "[yellow]○ parse error[/yellow]", "")]

    def test_plain_output_without_rich(self, runner, run, monkeypatch):
        monkeypatch.setattr(_dev_cmds, "console", None)
        result = runner.invoke(app.cli, ["status"])
        assert result.exit_code == 0, result.output
        run.assert_called_once_with(["docker", "compose", "ps"], check=False)


class TestLogs:
    def test_all_logs(self, runner, run):
        result = runner.invoke(app.cli, ["logs"])
        assert result.exit_code == 0, result.output
        run.assert_called_once_with(["docker", "compose", "logs"], check=False)

    def test_follow_one_service(self, runner, run):
        runner.invoke(app.cli, ["logs", "-f", "-s", "worker"])
        run.assert_called_once_with(["docker", "compose", "logs", "-f", "worker"], check=False)

    def test_saga_id_filters_through_grep(self, runner, monkeypatch):
        popen = MagicMock()
        monkeypatch.setattr(subprocess, "Popen", popen)
        result = runner.invoke(app.cli, ["logs", "abc123"])

        assert result.exit_code == 0, result.output
        assert "Searching for saga: abc123" in result.output
        first, second = popen.call_args_list
        assert first.args[0] == ["docker", "compose", "logs"]
        assert second.args[0] == ["grep", "abc123"]


class TestSetup:
    def test_requires_a_project(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app.cli, ["setup"])
        assert result.exit_code == 1
        assert "sagaz init" in result.output

    @pytest.mark.parametrize(("confirm", "executed"), [("y", True), ("n", False)])
    def test_runs_or_aborts_after_the_summary(self, runner, tmp_path, confirm, executed):
        config = {"mode": "local"}
        with (
            runner.isolated_filesystem(temp_dir=tmp_path),
            patch.object(_project_cmds, "_gather_setup_configuration", return_value=config),
            patch.object(_project_cmds, "_display_configuration_summary"),
            patch.object(_project_cmds, "_execute_setup") as execute,
        ):
            Path("sagaz.yaml").write_text("name: x\n")
            result = runner.invoke(app.cli, ["setup"], input=f"{confirm}\n")

        assert result.exit_code == 0, result.output
        assert execute.called is executed
        assert ("Aborted." in result.output) is not executed


class TestInitDirectoryGuard:
    def test_non_empty_directory_needs_confirmation(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("shop").mkdir()
            Path("shop/existing.txt").write_text("x")
            result = runner.invoke(app.cli, ["init"], input="shop\n\nn\n")
        assert result.exit_code == 0
        assert "Aborted." in result.output


class TestBenchmark:
    """``sagaz benchmark`` runs in-process against the installed library."""

    def test_quick_reports_a_table(self, runner):
        result = runner.invoke(app.cli, ["benchmark", "--quick"])
        assert result.exit_code == 0, result.output
        assert "quick" in result.output
        assert "memory" in result.output

    def test_output_is_written_as_json(self, runner, tmp_path):
        out = tmp_path / "bench.json"
        result = runner.invoke(app.cli, ["benchmark", "--quick", "--output", str(out)])
        assert result.exit_code == 0, result.output
        report = json.loads(out.read_text())
        (row,) = report["results"]
        assert (row["profile"], row["sagas"], row["failed"]) == ("quick", 20, 0)
        assert row["throughput"] > 0
        assert row["p50_ms"] <= row["p95_ms"] <= row["p99_ms"]
        assert f"Results saved to {out}" in result.output

    def test_storage_url_benchmarks_that_backend_and_cleans_up(self, runner, tmp_path):
        import asyncio

        from sagaz.core.storage import create_storage_manager

        url = f"sqlite://{tmp_path / 'bench.db'}"
        result = runner.invoke(app.cli, ["benchmark", "--quick", "--storage-url", url])
        assert result.exit_code == 0, result.output
        assert "sqlite" in result.output

        async def remaining():
            async with create_storage_manager(url=url) as manager:
                return await manager.saga.count()

        assert asyncio.run(remaining()) == 0

    def test_failures_set_a_non_zero_exit_code(self, runner, monkeypatch):
        from sagaz.cli import _benchmark

        async def boom(self, ctx):
            msg = "declined"
            raise RuntimeError(msg)

        monkeypatch.setattr(_benchmark.BenchmarkSaga, "charge", boom)
        monkeypatch.setattr(
            _benchmark,
            "PROFILES",
            {**_benchmark.PROFILES, "quick": _benchmark.Profile("quick", 3, 1)},
        )
        result = runner.invoke(app.cli, ["benchmark", "--quick"])
        assert result.exit_code == 1
        assert "3 saga(s) failed" in result.output

    @pytest.mark.parametrize(
        ("profile", "quick", "expected"),
        [
            ("local", False, ["local"]),
            ("stress", False, ["stress"]),
            ("full", False, ["local", "production", "stress"]),
            ("stress", True, ["quick"]),
        ],
    )
    def test_profile_selection(self, profile, quick, expected):
        from sagaz.cli._benchmark import profiles_for

        assert [p.name for p in profiles_for(profile, quick)] == expected

    def test_plain_output_without_rich(self, runner, monkeypatch):
        from sagaz.cli import _benchmark_cmd

        monkeypatch.setattr(_benchmark_cmd, "console", None)
        result = runner.invoke(app.cli, ["benchmark", "--quick"])
        assert result.output.splitlines()[0].startswith("profile  storage  sagas")

    def test_percentile_edges(self):
        from sagaz.cli._benchmark import percentile, summary

        assert percentile([], 99) == 0.0
        assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
        assert percentile([1.0, 2.0], 99) == 2.0
        assert summary([]) == {"results": [], "median_throughput": 0}
