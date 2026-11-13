"""SagaAnalyticsPipeline(storage).run(): real sagas → storage → Gold layer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("sqldim")

from sagaz import Saga, action, compensate  # noqa: E402
from sagaz.analytics import SagaAnalyticsPipeline, SagaQueries  # noqa: E402
from sagaz.analytics.sources import bronze_records_from_storage  # noqa: E402
from sagaz.core.config import SagaConfig  # noqa: E402
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage  # noqa: E402
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage  # noqa: E402
from sagaz.core.types import SagaStatus  # noqa: E402


class CheckoutSaga(Saga):
    saga_name = "checkout"

    @action("reserve")
    async def reserve(self, ctx):
        return {"reserved": True}

    @compensate("reserve")
    async def release(self, ctx):
        return None

    @action("charge", depends_on=["reserve"])
    async def charge(self, ctx):
        if ctx.get("declined"):
            msg = "card declined"
            raise RuntimeError(msg)
        return {"charged": True}


async def _run_checkouts(storage) -> None:
    config = SagaConfig(storage=storage)
    await CheckoutSaga(config=config).run({"order": 1})
    await CheckoutSaga(config=config).run({"order": 2})
    with pytest.raises(RuntimeError):
        await CheckoutSaga(config=config).run({"order": 3, "declined": True})


@pytest.fixture(params=["memory", "sqlite"])
async def storage(request, tmp_path):
    if request.param == "memory":
        yield InMemorySagaStorage()
        return
    sqlite = SQLiteSagaStorage(str(tmp_path / "sagas.db"))
    yield sqlite
    await sqlite.close()


class TestRunFromStorage:
    async def test_real_runs_reach_the_gold_layer(self, storage):
        await _run_checkouts(storage)

        with SagaAnalyticsPipeline(storage) as pipeline:
            stats = await pipeline.run()
            summary = pipeline.query(SagaQueries.SAGA_SUMMARY)
            latency = {r["step_name"]: r for r in pipeline.query(SagaQueries.STEP_LATENCY)}
            compensations = pipeline.query(SagaQueries.COMPENSATION_EVENTS)

        assert stats.ok, stats.quality_errors
        assert (stats.sagas_loaded, stats.facts_loaded) == (3, 6)
        assert summary[0]["total_sagas"] == 3
        assert summary[0]["completed"] == 2
        assert summary[0]["compensated"] == 1
        assert latency["charge"]["error_rate_pct"] == pytest.approx(100 / 3, abs=0.01)
        assert latency["reserve"]["p95_ms"] is not None
        assert compensations[0]["step_name"] == "reserve"

    async def test_run_refreshes_instead_of_duplicating(self, storage):
        await _run_checkouts(storage)
        with SagaAnalyticsPipeline(storage) as pipeline:
            await pipeline.run()
            await CheckoutSaga(config=SagaConfig(storage=storage)).run({"order": 4})
            stats = await pipeline.run()
            total = pipeline.query("SELECT COUNT(*) AS n FROM fact_execution")[0]["n"]

        assert stats.sagas_loaded == 4
        assert total == 8

    async def test_accepts_a_storage_manager(self):
        saga_storage = InMemorySagaStorage()
        await _run_checkouts(saga_storage)
        manager = SimpleNamespace(saga=saga_storage)

        with SagaAnalyticsPipeline(manager) as pipeline:
            stats = await pipeline.run()

        assert stats.sagas_loaded == 3


class TestRunErrors:
    async def test_run_without_storage_explains_how_to_fix_it(self):
        with SagaAnalyticsPipeline() as pipeline, pytest.raises(ValueError, match="storage"):
            await pipeline.run()

    async def test_object_without_export_is_rejected(self):
        with SagaAnalyticsPipeline(object()) as pipeline, pytest.raises(TypeError):
            await pipeline.run()


class TestBronzeExtraction:
    async def test_storage_records_are_normalised(self):
        storage = InMemorySagaStorage()
        aware = datetime(2026, 1, 1, 12, 0, tzinfo=UTC) + timedelta(hours=3)
        await storage.save_saga_state(
            "s1",
            "checkout",
            SagaStatus.ROLLED_BACK,
            [
                {
                    "name": "reserve",
                    "status": "compensated",
                    "executed_at": aware.isoformat(),
                    "duration_ms": 12.5,
                    "retry_count": 2,
                },
                {"name": "charge", "status": "failed", "executed_at": None},
                {
                    "name": "notify",
                    "status": "completed",
                    "executed_at": datetime(2026, 1, 1, 9, 30),
                },
            ],
            {},
        )

        sagas, steps = await bronze_records_from_storage(storage)

        assert sagas[0]["status"] == "rolled_back"
        assert sagas[0]["created_at"].tzinfo is None
        assert steps[0] == {
            "saga_id": "s1",
            "saga_name": "checkout",
            "step_name": "reserve",
            "action": "reserve",
            "outcome": "compensated",
            "duration_ms": 12.5,
            "attempt": 3,
            "executed_at": datetime(2026, 1, 1, 15, 0),
        }
        assert steps[1]["executed_at"] is None
        assert steps[1]["duration_ms"] is None
        assert steps[2]["executed_at"] == datetime(2026, 1, 1, 9, 30)  # naive kept as-is


def _saga(saga_id, status="completed"):
    return {"saga_id": saga_id, "saga_name": "Synthetic", "status": status}


def _step(saga_id, duration_ms, outcome="completed"):
    return {
        "saga_id": saga_id,
        "saga_name": "Synthetic",
        "step_name": "work",
        "outcome": outcome,
        "duration_ms": duration_ms,
    }


class TestGoldCorrectness:
    def test_p95_matches_linear_interpolation_on_synthetic_data(self):
        # Durations 1..100 ms: PERCENTILE_CONT(0.95) = 95 + 0.05 * (96 - 95) = 95.05.
        sagas = [_saga(f"s{i}") for i in range(1, 101)]
        steps = [_step(f"s{i}", float(i)) for i in range(1, 101)]
        with SagaAnalyticsPipeline() as pipeline:
            pipeline.load_from_records(sagas, steps)
            row = pipeline.query(SagaQueries.STEP_LATENCY)[0]

        assert row["executions"] == 100
        assert row["p50_ms"] == pytest.approx(50.5)
        assert row["p95_ms"] == pytest.approx(95.05)
        assert row["p99_ms"] == pytest.approx(99.01)

    def test_unknown_duration_does_not_drag_percentiles_down(self):
        sagas = [_saga("a"), _saga("b"), _saga("c")]
        steps = [_step("a", 100.0), _step("b", 100.0), _step("c", None)]
        with SagaAnalyticsPipeline() as pipeline:
            pipeline.load_from_records(sagas, steps)
            row = pipeline.query(SagaQueries.STEP_LATENCY)[0]

        assert row["p50_ms"] == pytest.approx(100.0)


class TestQualityGates:
    def test_unknown_saga_status_is_rejected(self):
        with SagaAnalyticsPipeline() as pipeline:
            stats = pipeline.load_from_records([_saga("s1", status="exploded")], [])

        assert stats.sagas_loaded == 0
        assert "unknown status 'exploded'" in stats.quality_errors[0]

    def test_unknown_step_outcome_is_rejected(self):
        with SagaAnalyticsPipeline() as pipeline:
            stats = pipeline.load_from_records([_saga("s1")], [_step("s1", 5.0, "teleported")])

        assert stats.facts_loaded == 0
        assert "unknown outcome 'teleported'" in stats.quality_errors[0]

    def test_status_case_is_normalised_before_the_gate(self):
        with SagaAnalyticsPipeline() as pipeline:
            stats = pipeline.load_from_records(
                [_saga("s1", status="ROLLED_BACK")], [_step("s1", 1.0, "Success")]
            )

        assert stats.ok, stats.quality_errors


@pytest.mark.integration
async def test_postgres_storage_keeps_step_durations_for_analytics(postgres_connection_string):
    if not postgres_connection_string:
        pytest.skip("PostgreSQL container not available")
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    async with PostgreSQLSagaStorage(
        postgres_connection_string, pool_min_size=1, pool_max_size=2
    ) as storage:
        pool = await storage._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE sagas CASCADE")
        await _run_checkouts(storage)

        exported = [record async for record in storage.export_all()]
        assert len(exported) == 3
        assert all(
            step.get("duration_ms") is not None for record in exported for step in record["steps"]
        )

        with SagaAnalyticsPipeline(storage) as pipeline:
            stats = await pipeline.run()
            latency = pipeline.query(SagaQueries.STEP_LATENCY)
        assert stats.ok, stats.quality_errors
        assert stats.facts_loaded == 6
        assert all(row["p95_ms"] is not None for row in latency)
