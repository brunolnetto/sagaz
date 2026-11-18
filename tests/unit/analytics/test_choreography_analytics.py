"""Analytics for choreographed sagas (#459)."""

from __future__ import annotations

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("sqldim")

from fastapi.testclient import TestClient  # noqa: E402

from sagaz.analytics import SagaAnalyticsPipeline, SagaQueries  # noqa: E402
from sagaz.analytics._choreography import choreography_rows  # noqa: E402
from sagaz.analytics.sources import bronze_records_from_storage  # noqa: E402
from sagaz.choreography import Event  # noqa: E402
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage  # noqa: E402
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage  # noqa: E402
from sagaz.core.tenant import system_scope  # noqa: E402
from sagaz.visualization.server import create_app  # noqa: E402
from tests.unit.analytics.test_storage_pipeline import CheckoutSaga  # noqa: E402
from tests.unit.test_choreography_compensation import Inventory, Stack  # noqa: E402


async def record(storage) -> None:
    """Three completed orders, one declined (compensated), one whose release fails,
    one still in flight, and one order in another tenant."""
    async with Stack(storage=storage) as stack:
        for i in range(3):
            await stack.orders.begin("order.created", {"order_id": f"ok-{i}", "amount": 40})
        await stack.orders.begin(
            "order.created", {"order_id": "declined", "amount": 500}, correlation_id="declined"
        )
        await stack.orders.begin(
            "order.created", {"order_id": "acme-1", "amount": 40}, tenant_id="acme"
        )
        # In flight: only the first event, nobody reacts to this type.
        await stack.bus.publish(Event("refund.requested", saga_id="in-flight", source="orders"))
    async with Stack(storage=storage, inventory=Inventory(fail_release=True)) as stack:
        await stack.orders.begin(
            "order.created", {"order_id": "stuck", "amount": 500}, correlation_id="stuck"
        )


@pytest.fixture(params=["memory", "sqlite"])
async def storage(request, tmp_path):
    if request.param == "memory":
        backend = InMemorySagaStorage()
        await record(backend)
        yield backend
        return
    async with SQLiteSagaStorage(str(tmp_path / "sagas.db")) as backend:
        await record(backend)
        yield backend


async def analytics(storage) -> tuple[SagaAnalyticsPipeline, object]:
    pipeline = SagaAnalyticsPipeline(storage)
    with system_scope():  # every tenant, as the monitor reads
        stats = await pipeline.run()
    return pipeline, stats


def by(rows, key):
    return {row[key]: row for row in rows}


class TestPipeline:
    async def test_choreography_never_pollutes_orchestration_reports(self, storage):
        await CheckoutSaga(config=_config(storage)).run({})
        sagas, _ = await bronze_records_from_storage(storage)
        assert {s["saga_name"] for s in sagas} == {"checkout"}
        pipeline, stats = await analytics(storage)
        with pipeline:
            assert [r["saga_name"] for r in pipeline.query(SagaQueries.SAGA_SUMMARY)] == [
                "checkout"
            ]
        assert (stats.sagas_loaded, stats.choreography_loaded) == (1, 7)

    async def test_summary_per_flow(self, storage):
        pipeline, _ = await analytics(storage)
        with pipeline:
            flows = by(pipeline.query(SagaQueries.CHOREOGRAPHY_SUMMARY), "flow")
        order = flows["order.created"]
        assert (order["transactions"], order["completed"]) == (6, 4)
        assert (order["compensated"], order["failed"], order["in_flight"]) == (1, 1, 0)
        assert order["compensation_rate_pct"] == pytest.approx(33.33)
        assert order["p50_duration_ms"] >= 0
        assert flows["refund.requested"]["in_flight"] == 1

    async def test_participants(self, storage):
        pipeline, _ = await analytics(storage)
        with pipeline:
            rows = by(pipeline.query(SagaQueries.CHOREOGRAPHY_PARTICIPANTS), "participant")
        assert rows["payments"]["failures_caused"] == 2
        assert rows["inventory"]["actions_undone"] == 1  # the declined order
        assert rows["inventory"]["compensation_failures"] == 1  # the stuck one
        assert rows["orders"]["events_emitted"] == 7
        assert rows["shipping"]["transactions"] == 4

    async def test_hop_latency(self, storage):
        pipeline, _ = await analytics(storage)
        with pipeline:
            rows = pipeline.query(SagaQueries.CHOREOGRAPHY_HOP_LATENCY)
        hops = {(r["participant"], r["event_type"]): r for r in rows}
        assert hops[("inventory", "inventory.reserved")]["hops"] == 6
        assert hops[("shipping", "order.shipped")]["hops"] == 4
        assert all(r["p50_ms"] >= 0 for r in rows)
        assert ("orders", "order.created") not in hops  # a beginning has no cause

    async def test_failures(self, storage):
        pipeline, _ = await analytics(storage)
        with pipeline:
            (row,) = pipeline.query(SagaQueries.CHOREOGRAPHY_FAILURES)
        assert (row["participant"], row["failed_event_type"]) == ("payments", "inventory.reserved")
        assert row["reason"] == "ValueError: card declined"
        assert (row["transactions"], row["left_inconsistent"]) == (2, 1)

    async def test_tenants_are_kept_apart(self, storage):
        pipeline, _ = await analytics(storage)
        with pipeline:
            tenants = pipeline.query(
                "SELECT tenant_id, COUNT(*) AS n FROM fact_choreography_transaction"
                " GROUP BY tenant_id ORDER BY tenant_id"
            )
        assert tenants == [{"tenant_id": "acme", "n": 1}, {"tenant_id": "default", "n": 6}]

    async def test_run_refreshes(self, storage):
        pipeline, _ = await analytics(storage)
        with pipeline:
            with system_scope():
                await pipeline.run()
            (count,) = pipeline.query("SELECT COUNT(*) AS n FROM fact_choreography_transaction")
        assert count["n"] == 7


def _config(storage):
    from sagaz.core.config import SagaConfig

    return SagaConfig(storage=storage, metrics=False, logging=False)


class TestRows:
    def test_older_records_without_causation_load_without_hops(self):
        record = {
            "saga_id": "t-1",
            "saga_name": "choreography",
            "context": {
                "correlation_id": "t-1",
                "status": "completed",
                "participants": ["orders", "inventory"],
                "events": [
                    {
                        "event_type": "order.created",
                        "event_id": "e1",
                        "source": "orders",
                        "at": "2026-11-01T10:00:00+00:00",
                    },
                    {
                        "event_type": "order.shipped",
                        "event_id": "e2",
                        "source": "inventory",
                        "at": "2026-11-01T10:00:02+00:00",
                    },
                ],
            },
        }
        transaction, events, compensations = choreography_rows(record)
        assert transaction["tenant_id"] == "default"
        assert (transaction["flow"], transaction["duration_ms"]) == ("order.created", 2000.0)
        assert [e["hop_ms"] for e in events] == [None, None]
        assert compensations == []

    def test_a_record_with_no_events(self):
        transaction, events, _ = choreography_rows(
            {"saga_id": "t-2", "saga_name": "choreography", "context": {}}
        )
        assert (transaction["flow"], transaction["status"]) == ("unknown", "executing")
        assert (transaction["started_at"], transaction["ended_at"]) == (None, None)
        assert events == []

    def test_only_tracker_records_are_loaded(self):
        with SagaAnalyticsPipeline() as pipeline:
            assert pipeline.load_choreography_records([{"saga_id": "x", "saga_name": "o"}]) == 0


class TestMonitor:
    async def test_reports_are_served(self, storage):
        with TestClient(create_app(analytics_storage=storage)) as client:
            body = client.get("/api/v1/analytics/choreography").json()
            failures = client.get("/api/v1/analytics/choreography-failures").json()
        assert body["choreography_loaded"] >= 6  # the default tenant at least
        assert body["rows"][0]["flow"] == "order.created"
        assert failures["rows"][0]["participant"] == "payments"
