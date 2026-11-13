"""`sagaz init --local` and real (unmocked) deployment templates (issue #48)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import click
import pytest
import yaml
from click.testing import CliRunner

from sagaz.cli import _init_handlers as handlers
from sagaz.cli.app import cli

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "sagaz"


class TestTemplatesAreReallyCopied:
    @pytest.mark.parametrize("broker", ["redis", "kafka", "rabbitmq"])
    def test_local_compose_for_each_broker(self, broker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        handlers._init_local(broker, with_observability=False)

        compose = yaml.safe_load((tmp_path / "docker-compose.yaml").read_text())
        services = " ".join(compose["services"])
        assert broker in services
        assert "postgres" in services

    def test_observability_adds_the_monitoring_folder(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        handlers._init_local("redis", with_observability=True)
        assert (tmp_path / "monitoring").is_dir()
        assert any((tmp_path / "monitoring").rglob("*"))

    def test_missing_template_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(click.ClickException, match="not available"):
            handlers._copy_resource("local/does-not-exist.yaml", "x.yaml")
        assert not (tmp_path / "x.yaml").exists()

    def test_resources_point_at_the_shipped_directory(self):
        assert Path(str(handlers._resources())) == PACKAGE_ROOT / "deployment" / "resources"


def test_every_package_data_pattern_matches_files():
    """Guards the 1.8.0 regression: package-data pointed at a moved directory."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]["sagaz"]

    for pattern in patterns:
        matches = [p for p in PACKAGE_ROOT.glob(pattern) if p.is_file()]
        assert matches, f"package-data pattern {pattern!r} matches no files"

    shipped = {p for pattern in patterns for p in PACKAGE_ROOT.glob(pattern) if p.is_file()}
    templates = {p for p in (PACKAGE_ROOT / "deployment" / "resources").rglob("*") if p.is_file()}
    assert templates <= shipped


class TestInitLocal:
    # Project name, location, example choice, then the local setup questions
    # (storage, broker, outbox, metrics, tracing, logging, benchmarks, dev mode).
    ANSWERS = "shop\n\n\n\n\n\n\n\n\n\n\n\n"

    def test_creates_project_and_compose_side_by_side(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
            result = runner.invoke(cli, ["init", "--local"], input=self.ANSWERS)
            project = Path(cwd) / "shop"

            assert result.exit_code == 0, result.output
            assert (project / "sagaz.yaml").exists()
            assert (project / "docker-compose.yaml").exists()
            assert not (Path(cwd) / "docker-compose.yaml").exists()
            assert "Mode: local" in result.output
            assert "Start it with: cd shop && sagaz dev" in result.output

    def test_without_local_no_compose_is_written(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
            result = runner.invoke(cli, ["init"], input="shop\n\n\n")

            assert result.exit_code == 0, result.output
            assert (Path(cwd) / "shop" / "sagaz.yaml").exists()
            assert not (Path(cwd) / "shop" / "docker-compose.yaml").exists()

    def test_help_documents_the_flag(self):
        result = CliRunner().invoke(cli, ["init", "--help"])
        assert "--local" in result.output
        assert "sagaz init --local" in result.output
