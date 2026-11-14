"""Unit tests of the multi-tenancy overhead benchmark harness (benchmarks/tenancy).

Statistics, scheduling and reporting are checked with synthetic numbers; the
workload runs for real but tiny, on the in-memory and SQLite backends, so the
assertions never depend on how fast the machine is.
"""

from __future__ import annotations

import json
import logging

import pytest

from benchmarks.tenancy import backends, cli, report, runner, stats, workload
from benchmarks.tenancy.stats import RunResult
from benchmarks.tenancy.workload import BASELINE, MULTI, MULTI_REGISTRY, Mode, Plan
from sagaz.core.storage.memory import InMemorySagaStorage
from sagaz.core.tenant import TenantContext, tenant_scope


def _run(mode, round_, wall, sagas=100, p50=1.0):
    return RunResult(mode, round_, sagas, wall, p50, p50 * 2, p50 * 3)


# ── stats ──


class TestPercentile:
    def test_interpolates_between_ranks(self):
        assert stats.percentile([1, 2, 3, 4], 50) == 2.5
        assert stats.percentile([4, 1, 3, 2], 0) == 1
        assert stats.percentile([1, 2, 3, 4], 100) == 4
        assert stats.percentile([10], 99) == 10

    def test_p99_of_a_hundred_values(self):
        assert stats.percentile(list(range(1, 101)), 99) == pytest.approx(99.01)

    @pytest.mark.parametrize(("values", "q"), [([], 50), ([1], -1), ([1], 101)])
    def test_rejects_bad_input(self, values, q):
        with pytest.raises(ValueError):
            stats.percentile(values, q)


def test_run_result_from_latencies():
    run = RunResult.from_latencies("multi", 2, [0.001, 0.002, 0.003, 0.004], wall_seconds=0.5)
    assert (run.mode, run.round, run.sagas) == ("multi", 2, 4)
    assert run.throughput == 8
    assert run.p50_ms == pytest.approx(2.5)
    assert run.p99_ms == pytest.approx(3.97)


class TestSummarize:
    def test_medians_and_spread(self):
        runs = [_run("a", 0, 1.0, p50=1), _run("a", 1, 2.0, p50=3), _run("a", 2, 4.0, p50=2)]
        summary = stats.summarize(runs)
        assert summary.runs == 3
        assert summary.throughput == 50
        assert (summary.throughput_min, summary.throughput_max) == (25, 100)
        assert (summary.p50_ms, summary.p95_ms, summary.p99_ms) == (2, 4, 6)

    def test_rejects_empty_or_mixed(self):
        with pytest.raises(ValueError, match="no runs"):
            stats.summarize([])
        with pytest.raises(ValueError, match="several modes"):
            stats.summarize([_run("a", 0, 1), _run("b", 0, 1)])


class TestPairedOverhead:
    def test_pairs_runs_of_the_same_round(self):
        runs = [
            _run("base", 0, 1.0),
            _run("multi", 0, 1.1),
            _run("base", 1, 2.0),
            _run("multi", 1, 1.9),
            _run("base", 2, 1.0),
            _run("multi", 2, 1.02),
            _run("multi", 3, 9.0),  # unpaired: ignored
        ]
        overhead = stats.paired_overhead(runs, "multi", "base")
        assert overhead.median_pct == pytest.approx(2.0)
        assert overhead.min_pct == pytest.approx(-5.0)
        assert overhead.max_pct == pytest.approx(10.0)

    def test_needs_a_common_round(self):
        with pytest.raises(ValueError, match="no round"):
            stats.paired_overhead([_run("a", 0, 1), _run("b", 1, 1)], "a", "b")


class TestSchedule:
    def test_two_modes_alternate_first(self):
        assert stats.schedule(["A", "B"], 3) == [
            (0, "A"),
            (0, "B"),
            (1, "B"),
            (1, "A"),
            (2, "A"),
            (2, "B"),
        ]

    def test_three_modes_rotate(self):
        orders = [[m for r, m in stats.schedule(["A", "B", "C"], 3) if r == i] for i in range(3)]
        assert orders == [["A", "B", "C"], ["B", "C", "A"], ["C", "A", "B"]]

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            stats.schedule(["A"], 0)
        with pytest.raises(ValueError):
            stats.schedule([], 1)


# ── workload ──


class TestPlan:
    def test_totals_and_tenant_ids(self):
        plan = Plan(tenants=12, sagas_per_tenant=3, sagas_per_worker=2)
        assert plan.total_sagas == 72
        assert plan.tenant_ids()[:2] == ["tenant-00", "tenant-01"]
        assert len(set(plan.tenant_ids())) == 12

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"tenants": 0, "sagas_per_tenant": 1},
            {"tenants": 1, "sagas_per_tenant": 0},
            {"tenants": 1, "sagas_per_tenant": 1, "sagas_per_worker": 0},
            {"tenants": 1, "sagas_per_tenant": 1, "step_sleep_ms": -1},
        ],
    )
    def test_rejects_empty_workloads(self, kwargs):
        with pytest.raises(ValueError):
            Plan(**kwargs)


def test_modes():
    assert not MULTI.is_ablation
    assert workload.MULTI_RLS_OFF.is_ablation
    assert workload.BASELINE_NO_TENANT_SQL.is_ablation
    names = {mode.name for mode in (*workload.STANDARD_MODES, *workload.POSTGRES_ABLATIONS)}
    assert {name for pair in workload.COMPARISONS for name in pair} <= names


class TestTenantArgs:
    def test_baseline_runs_without_tenants(self):
        args, registry = workload._tenant_args(Plan(3, 2), BASELINE)
        assert (args, registry) == ([None, None, None], None)

    def test_multi_gets_contexts_with_quota_equal_to_the_load(self):
        args, registry = workload._tenant_args(Plan(3, 2), MULTI)
        assert registry is None
        assert [a.tenant_id for a in args] == ["tenant-0", "tenant-1", "tenant-2"]
        assert all(a.quotas.max_concurrent_sagas == 2 for a in args)

    def test_registry_mode_passes_ids_resolved_by_the_registry(self):
        args, registry = workload._tenant_args(Plan(2, 4), MULTI_REGISTRY)
        assert args == ["tenant-0", "tenant-1"]
        assert registry.get("tenant-1").quotas.max_concurrent_sagas == 4


@pytest.mark.parametrize("mode", [BASELINE, MULTI, MULTI_REGISTRY])
async def test_run_once_stores_every_saga_in_its_tenant(mode):
    storage = InMemorySagaStorage()
    plan = Plan(tenants=3, sagas_per_tenant=2, sagas_per_worker=2)
    run = await workload.run_once(storage, plan, mode, 0, "t")
    assert run.sagas == plan.total_sagas == 12
    assert run.throughput > 0
    assert 0 < run.p50_ms <= run.p95_ms <= run.p99_ms
    tenant = "tenant-2" if mode.tenancy else "default"
    with tenant_scope(tenant):
        state = await storage.load_saga_state("t-2-1-1")
    assert state["status"] == "completed"
    assert sorted(step["name"] for step in state["steps"]) == [
        "charge",
        "notify",
        "reserve",
        "ship",
    ]
    assert state["context"]["notified"] is True


async def test_run_once_with_step_sleep():
    run = await workload.run_once(InMemorySagaStorage(), Plan(1, 1, step_sleep_ms=1), MULTI, 0, "s")
    assert run.p50_ms >= 4  # four steps of 1 ms


async def test_run_once_fails_when_a_saga_fails(monkeypatch):
    suspended = [TenantContext("t-0", active=False), TenantContext("t-1", active=False)]
    monkeypatch.setattr(workload, "_tenant_args", lambda plan, mode: (suspended, None))
    with pytest.raises(workload.RunFailedError, match="2 failed workers"):
        await workload.run_once(InMemorySagaStorage(), Plan(2, 1), MULTI, 0, "f")


class _UnwritableStorage(InMemorySagaStorage):
    async def save_saga_state(self, *args, **kwargs):
        msg = "read-only"
        raise RuntimeError(msg)


async def test_run_once_fails_when_state_is_not_persisted():
    with pytest.raises(workload.RunFailedError, match="persistence failures"):
        await workload.run_once(_UnwritableStorage(), Plan(1, 1), BASELINE, 0, "p")


def test_persistence_watch_ignores_other_warnings():
    with workload.watch_persistence() as failures:
        logging.getLogger("sagaz.test").warning("something else")
        logging.getLogger("sagaz.test").warning("Failed to persist saga start: x")
    assert (failures.count, failures.last) == (1, "Failed to persist saga start: x")


class TestVerifyPersisted:
    async def test_missing_saga(self):
        with pytest.raises(workload.RunFailedError, match="not stored"):
            await workload.verify_persisted(InMemorySagaStorage(), [(None, "nope")])

    async def test_tenant_saga_visible_to_default_tenant(self):
        class LeakyStorage(InMemorySagaStorage):
            async def load_saga_state(self, saga_id):
                return {"status": "completed"}

        with pytest.raises(workload.RunFailedError, match="visible to the default"):
            await workload.verify_persisted(LeakyStorage(), [("acme", "x")])

    def test_tenant_id_of_each_argument_kind(self):
        assert workload._tenant_id(None) is None
        assert workload._tenant_id(TenantContext("acme")) == "acme"
        assert workload._tenant_id("globex") == "globex"


# ── backends and runner ──


async def test_open_backend_rejects_unknown_or_unconfigured():
    options = backends.BackendOptions()
    for name, match in [
        ("mongo", "unknown backend"),
        ("redis", "--redis-url"),
        ("postgres", "--postgres-admin-url"),
    ]:
        with pytest.raises(ValueError, match=match):
            async with backends.open_backend(name, options):
                pass


async def test_non_postgres_backends_reject_ablations():
    async with backends.open_backend("memory", backends.BackendOptions()) as session:
        await session.prepare(MULTI)
        assert not session.supports_ablations
        with pytest.raises(ValueError, match="ablation"):
            await session.prepare(workload.MULTI_RLS_OFF)


async def test_measure_interleaves_and_summarizes():
    messages = []
    async with backends.open_backend("memory", backends.BackendOptions()) as session:
        result = await runner.measure(
            session, Plan(2, 2), [BASELINE, MULTI], rounds=3, warmup=1, progress=messages.append
        )
    assert [(r.round, r.mode) for r in result.runs] == stats.schedule(["baseline", "multi"], 3)
    assert [s.mode for s in result.summaries] == ["baseline", "multi"]
    assert [(o.mode, o.reference) for o in result.overheads] == [("multi", "baseline")]
    assert len(messages) == 6
    assert messages[0].startswith("memory round 1/3 baseline: ")


async def test_measure_rejects_duplicate_modes():
    async with backends.open_backend("memory", backends.BackendOptions()) as session:
        with pytest.raises(ValueError, match="unique"):
            await runner.measure(session, Plan(1, 1), [MULTI, Mode("multi", tenancy=False)], 1)


async def test_run_benchmark_on_memory_and_sqlite():
    results = await runner.run_benchmark(
        ["memory", "sqlite"],
        backends.BackendOptions(),
        Plan(2, 2),
        workload.STANDARD_MODES,
        rounds=1,
        warmup=0,
        ablation_modes=workload.POSTGRES_ABLATIONS,  # skipped: not PostgreSQL
    )
    assert [r.backend for r in results] == ["memory", "sqlite"]
    assert results[1].info["sqlite"]
    assert [s.mode for s in results[1].summaries] == ["baseline", "multi", "multi-registry"]


# ── report ──


def _backend_result():
    runs = [_run("baseline", 0, 1.0), _run("multi", 0, 1.03), _run("multi-registry", 0, 0.99)]
    by_mode = {}
    for run in runs:
        by_mode.setdefault(run.mode, []).append(run)
    return report.BackendResult(
        backend="memory",
        info={"version": "1"},
        runs=runs,
        summaries=[stats.summarize(group) for group in by_mode.values()],
        overheads=[
            stats.paired_overhead(runs, "multi", "baseline"),
            stats.paired_overhead(runs, "multi-registry", "baseline"),
        ],
    )


def test_results_table():
    table = report.results_table([_backend_result()])
    lines = table.splitlines()
    assert lines[0].startswith("| Backend | Mode | Sagas/s (median)")
    assert lines[2] == "| memory | baseline | 100 | 100-100 | 1.0 | 2.0 | 3.0 | - |"
    assert lines[3].endswith("| +3.0% [+3.0%, +3.0%] |")
    assert lines[4].endswith("| -1.0% [-1.0%, -1.0%] |")


def test_comparisons_table_and_render():
    result = _backend_result()
    assert "| memory | multi | baseline | +3.0% [+3.0%, +3.0%] |" in (
        report.comparisons_table([result])
    )
    full = report.Report(config={"tenants": 2}, environment={"cpus": 8}, backends=[result])
    text = report.render(full)
    assert text.startswith("Configuration: tenants=2")
    assert "Environment: cpus=8" in text
    assert "- memory: version=1" in text


def test_overhead_cell_without_value():
    assert report.overhead_cell(None) == "-"


def test_json_round_trip(tmp_path):
    full = report.Report(config={"tenants": 2}, environment={}, backends=[_backend_result()])
    path = tmp_path / "out.json"
    full.write_json(path)
    data = json.loads(path.read_text())
    assert data["backends"][0]["overheads"][0]["median_pct"] == pytest.approx(3.0)
    assert data["backends"][0]["runs"][1]["wall_seconds"] == 1.03


def test_environment_info():
    info = report.environment_info()
    assert info["cpus"] >= 1
    assert info["python"].count(".") == 2
    assert {"uname", "memory_mb", "sagaz_commit", "loadavg"} <= set(info)


def test_total_memory_without_proc(monkeypatch):
    def missing(self):
        raise OSError

    monkeypatch.setattr(report.Path, "read_text", missing)
    assert report._total_memory_mb() is None


# ── cli ──


def test_parser_defaults_are_the_scaled_down_configuration():
    args = cli.build_parser().parse_args([])
    assert (args.tenants, args.sagas_per_tenant, args.rounds) == (100, 10, 10)
    assert args.backends == ["memory", "sqlite"]
    assert not args.postgres_ablations
    assert "--tenants 1000 --sagas-per-tenant 10" in cli.DESCRIPTION


@pytest.mark.parametrize("value", ["", "memory,mongo"])
def test_parser_rejects_unknown_backends(value):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--backends", value])


def test_main_prints_tables_and_writes_json(tmp_path, capsys):
    path = tmp_path / "result.json"
    argv = ["--backends", "memory", "--tenants", "2", "--sagas-per-tenant", "2"]
    argv += ["--rounds", "2", "--warmup", "0", "--json", str(path)]
    assert cli.main(argv) == 0
    out = capsys.readouterr()
    assert "| memory | multi-registry |" in out.out
    assert "memory round 2/2" in out.err
    data = json.loads(path.read_text())
    assert data["config"]["sagas_per_run"] == 4
    assert "loadavg_end" in data["environment"]
