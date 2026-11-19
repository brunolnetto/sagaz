"""Analytics reads the unified saga log (ADR-041 phase 4, #467)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("sqldim")

from click.testing import CliRunner  # noqa: E402

from sagaz.analytics import SagaAnalyticsPipeline, SagaQueries  # noqa: E402
from sagaz.cli.app import cli  # noqa: E402
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage  # noqa: E402
from sagaz.core.storage.saga_log import InMemorySagaLogStore  # noqa: E402
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore  # noqa: E402
from sagaz.core.tenant import system_scope  # noqa: E402
from tests.unit.core.test_saga_log_migration import build_old_layout  # noqa: E402
from tests.unit.core.test_unified_orchestration import order_saga  # noqa: E402
from tests.unit.test_choreography_unified import shop  # noqa: E402


async def fill(log) -> None:
    """Orchestrated and choreographed transactions, all on one saga log."""
    await order_saga(log).run({"order_id": "o-1"}, saga_id="orch-ok")
    with pytest.raises(ValueError):
        await order_saga(log, fail_charge=True).run({"order_id": "o-2"}, saga_id="orch-bad")
    with pytest.raises(ValueError):
        failing = order_saga(log, fail_charge=True, fail_release=True)
        await failing.run({"order_id": "o-3"}, saga_id="orch-stuck")
    service, orders, _ = shop(log)
    async with service:
        for amount in (40, 40, 500):
            await orders.begin("order.created", {"order_id": "c", "amount": amount})
        await service.settle()


@pytest.fixture(params=["memory", "sqlite"])
async def log(request, tmp_path):
    store = (
        InMemorySagaLogStore()
        if request.param == "memory"
        else SQLiteSagaLogStore(str(tmp_path / "log.db"))
    )
    await fill(store)
    yield store
    await store.close()


async def reports(source, *queries: str) -> dict[str, list[dict]]:
    pipeline = SagaAnalyticsPipeline(source)
    with pipeline:
        with system_scope():
            await pipeline.run()
        return {q: pipeline.query(getattr(SagaQueries, q)) for q in queries}


class TestUnifiedSource:
    async def test_one_summary_for_both_coordination_styles(self, log):
        (flows,) = (await reports(log, "FLOW_SUMMARY")).values()
        by_flow = {(r["coordination"], r["flow"]): r for r in flows}
        orchestrated = by_flow[("orchestrated", "order")]
        assert (orchestrated["transactions"], orchestrated["completed"]) == (3, 1)
        assert (orchestrated["compensated"], orchestrated["failed"]) == (1, 1)
        choreographed = by_flow[("choreographed", "order.created")]
        assert (choreographed["transactions"], choreographed["completed"]) == (3, 2)
        assert choreographed["compensated"] == 1
        assert choreographed["compensation_rate_pct"] == pytest.approx(33.33)
        assert orchestrated["p50_duration_ms"] >= 0

    async def test_orchestrated_reports_come_from_activities(self, log):
        result = await reports(log, "SAGA_SUMMARY", "STEP_LATENCY", "COMPENSATION_EVENTS")
        (summary,) = result["SAGA_SUMMARY"]  # no phantom "choreography" saga
        assert (summary["saga_name"], summary["total_sagas"]) == ("order", 3)
        steps = {r["step_name"]: r for r in result["STEP_LATENCY"]}
        assert steps["charge"]["executions"] == 3
        assert steps["charge"]["error_rate_pct"] == pytest.approx(66.67)
        compensations = {r["step_name"]: r for r in result["COMPENSATION_EVENTS"]}
        assert compensations["reserve"]["compensation_count"] == 1  # the other one failed

    async def test_choreography_reports_come_from_the_log(self, log):
        result = await reports(
            log, "CHOREOGRAPHY_PARTICIPANTS", "CHOREOGRAPHY_HOP_LATENCY", "CHOREOGRAPHY_FAILURES"
        )
        participants = {r["participant"]: r for r in result["CHOREOGRAPHY_PARTICIPANTS"]}
        assert participants["payments"]["failures_caused"] == 1
        assert participants["inventory"]["actions_undone"] == 1
        hops = {(r["participant"], r["event_type"]) for r in result["CHOREOGRAPHY_HOP_LATENCY"]}
        assert ("inventory", "inventory.reserved") in hops
        (failure,) = result["CHOREOGRAPHY_FAILURES"]
        assert failure["reason"] == "ValueError: card declined"


GOLD = (
    "SAGA_SUMMARY",
    "COMPENSATION_EVENTS",
    "CHOREOGRAPHY_SUMMARY",
    "CHOREOGRAPHY_PARTICIPANTS",
    "CHOREOGRAPHY_FAILURES",
    "FLOW_SUMMARY",
)


def _comparable(rows: list[dict]) -> list[dict]:
    """Rows without timing columns (both layouts record times independently)."""
    timing = ("duration", "_ms")
    return sorted(
        ({k: v for k, v in row.items() if not any(t in k for t in timing)} for row in rows),
        key=repr,
    )


def test_reports_are_identical_after_migrating(tmp_path):
    path = str(tmp_path / "old.db")
    asyncio.run(build_old_layout(path))

    async def legacy():
        async with SQLiteSagaStorage(path) as storage:
            return await reports(storage, *GOLD, "STEP_LATENCY")

    before = asyncio.run(legacy())
    for query in GOLD:  # the comparison below must not pass on empty reports
        assert before[query], query
    result = CliRunner().invoke(cli, ["migrate", "unify", "--source", f"sqlite://{path}"])
    assert result.exit_code == 0, result.output

    async def unified():
        async with SQLiteSagaLogStore(path) as log:
            return await reports(log, *GOLD, "STEP_LATENCY")

    after = asyncio.run(unified())
    for query in GOLD:
        assert _comparable(after[query]) == _comparable(before[query]), query
    executions = {r["step_name"]: r["executions"] for r in before["STEP_LATENCY"]}
    assert {r["step_name"]: r["executions"] for r in after["STEP_LATENCY"]} == executions
