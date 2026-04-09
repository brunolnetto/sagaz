"""
Unit tests for sagaz.analytics — SagaAnalyticsPipeline and related.
Uses DuckDB in-memory; no external services required.
"""

from __future__ import annotations

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed; install sagaz[analytics]")

from sqldim import AccumulatingFact, TransactionFact

from sagaz.analytics.pipeline import PipelineStats, SagaAnalyticsPipeline, SagaBronzeProcessor
from sagaz.analytics.queries import SagaQueries
from sagaz.analytics.schema import DimSaga, DimStep, FactExecution, FactSagaLifecycle

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _saga(saga_id: str, name: str = "OrderSaga", status: str = "completed") -> dict:
    return {"saga_id": saga_id, "saga_name": name, "status": status}


def _step(
    saga_id: str,
    step_name: str,
    outcome: str = "success",
    duration_ms: float = 50.0,
    saga_name: str = "OrderSaga",
) -> dict:
    return {
        "saga_id": saga_id,
        "saga_name": saga_name,
        "step_name": step_name,
        "outcome": outcome,
        "duration_ms": duration_ms,
        "attempt": 1,
    }


# ---------------------------------------------------------------------------
# Schema model definitions
# ---------------------------------------------------------------------------


class TestSchemaModels:
    def test_dimsaga_is_importable(self):
        assert DimSaga is not None

    def test_dimstep_is_importable(self):
        assert DimStep is not None

    def test_factexecution_is_importable(self):
        assert FactExecution is not None

    def test_dimsaga_has_required_fields(self):
        fields = DimSaga.model_fields
        assert "saga_id" in fields
        assert "saga_name" in fields
        assert "status" in fields

    def test_factexecution_has_measure_fields(self):
        fields = FactExecution.model_fields
        assert "duration_ms" in fields
        assert "outcome" in fields
        assert "saga_id" in fields


# ---------------------------------------------------------------------------
# PipelineStats
# ---------------------------------------------------------------------------


class TestPipelineStats:
    def test_ok_when_no_errors(self):
        stats = PipelineStats(sagas_loaded=3, steps_loaded=5, facts_loaded=5)
        assert stats.ok is True

    def test_not_ok_when_errors(self):
        stats = PipelineStats(quality_errors=["bad record"])
        assert stats.ok is False


# ---------------------------------------------------------------------------
# SagaAnalyticsPipeline — context manager
# ---------------------------------------------------------------------------


class TestPipelineLifecycle:
    def test_context_manager_closes_cleanly(self):
        with SagaAnalyticsPipeline() as pipeline:
            assert pipeline is not None

    def test_close_is_idempotent(self):
        pipeline = SagaAnalyticsPipeline()
        pipeline.close()
        pipeline.close()  # second close should not raise


# ---------------------------------------------------------------------------
# load_from_records
# ---------------------------------------------------------------------------


class TestLoadFromRecords:
    def test_loads_sagas(self):
        with SagaAnalyticsPipeline() as p:
            stats = p.load_from_records([_saga("s1"), _saga("s2"), _saga("s3")], [])
        assert stats.sagas_loaded == 3
        assert stats.ok is True

    def test_loads_steps_and_facts(self):
        with SagaAnalyticsPipeline() as p:
            stats = p.load_from_records(
                [_saga("s1")],
                [_step("s1", "reserve"), _step("s1", "charge")],
            )
        assert stats.steps_loaded == 2
        assert stats.facts_loaded == 2

    def test_missing_saga_id_is_quality_error(self):
        with SagaAnalyticsPipeline() as p:
            stats = p.load_from_records([{"saga_name": "X", "status": "ok"}], [])
        assert not stats.ok
        assert any("saga_id" in e for e in stats.quality_errors)

    def test_missing_step_name_is_quality_error(self):
        with SagaAnalyticsPipeline() as p:
            stats = p.load_from_records(
                [_saga("s1")],
                [{"saga_id": "s1", "outcome": "success"}],
            )
        assert not stats.ok

    def test_negative_duration_is_quality_error(self):
        with SagaAnalyticsPipeline() as p:
            stats = p.load_from_records(
                [_saga("s1")],
                [_step("s1", "pay", duration_ms=-10)],
            )
        assert not stats.ok

    def test_upsert_deduplicates_saga_records(self):
        """Loading the same saga_id twice replaces, not duplicates."""
        with SagaAnalyticsPipeline() as p:
            p.load_from_records(
                [_saga("s1", status="executing"), _saga("s1", status="completed")], []
            )
            rows = p.query("SELECT status FROM dim_saga WHERE saga_id = 's1'")
        assert len(rows) == 1
        assert rows[0]["status"] == "completed"

    def test_dim_step_upsert_deduplicates(self):
        """Same saga_name::step_name loaded twice should produce one dim_step row."""
        with SagaAnalyticsPipeline() as p:
            p.load_from_records(
                [_saga("s1"), _saga("s2")],
                [_step("s1", "charge"), _step("s2", "charge")],
            )
            rows = p.query("SELECT COUNT(*) AS cnt FROM dim_step")
        # Both have the same step_name but same saga_name → one row
        assert rows[0]["cnt"] == 1


# ---------------------------------------------------------------------------
# query — Gold layer SQL
# ---------------------------------------------------------------------------


class TestPipelineQuery:
    def _setup(self) -> SagaAnalyticsPipeline:
        p = SagaAnalyticsPipeline()
        p.load_from_records(
            [
                _saga("s1", "OrderSaga", "completed"),
                _saga("s2", "OrderSaga", "rolled_back"),
                _saga("s3", "PaySaga", "completed"),
            ],
            [
                _step("s1", "reserve", "success", 20.0),
                _step("s1", "charge", "success", 80.0),
                _step("s2", "reserve", "compensated", 25.0),
                _step("s2", "charge", "failed", 200.0),
                _step("s3", "pay", "success", 50.0, saga_name="PaySaga"),
            ],
        )
        return p

    def test_saga_summary_returns_rows(self):
        with self._setup() as p:
            rows = p.query(SagaQueries.SAGA_SUMMARY)
        assert len(rows) >= 1

    def test_saga_summary_has_expected_columns(self):
        with self._setup() as p:
            rows = p.query(SagaQueries.SAGA_SUMMARY)
        assert rows
        assert "saga_name" in rows[0]
        assert "total_sagas" in rows[0]
        assert "compensation_rate_pct" in rows[0]

    def test_step_latency_returns_rows(self):
        with self._setup() as p:
            rows = p.query(SagaQueries.STEP_LATENCY)
        assert len(rows) >= 1

    def test_step_latency_has_percentile_columns(self):
        with self._setup() as p:
            rows = p.query(SagaQueries.STEP_LATENCY)
        assert rows
        assert "p50_ms" in rows[0]
        assert "p99_ms" in rows[0]

    def test_compensation_events_query(self):
        with self._setup() as p:
            rows = p.query(SagaQueries.COMPENSATION_EVENTS)
        # s2/reserve was compensated
        assert len(rows) >= 1

    def test_empty_pipeline_returns_empty_summary(self):
        with SagaAnalyticsPipeline() as p:
            rows = p.query(SagaQueries.SAGA_SUMMARY)
        assert rows == []

    def test_raw_duckdb_query_works(self):
        with self._setup() as p:
            rows = p.query("SELECT COUNT(*) AS cnt FROM fact_execution")
        assert rows[0]["cnt"] == 5


# ---------------------------------------------------------------------------
# Schema model sqldim semantics
# ---------------------------------------------------------------------------


class TestSchemaModelSemantics:
    """Verify that sqldim metadata (natural keys, SCD type, grain, fact type)
    is correctly declared on every Silver model."""

    def test_dimsaga_natural_key(self):
        assert DimSaga.__natural_key__ == ["saga_id"]

    def test_dimsaga_scd_type_is_1(self):
        assert DimSaga.__scd_type__ == 1

    def test_dimstep_natural_key(self):
        assert DimStep.__natural_key__ == ["step_key"]

    def test_dimstep_scd_type_is_1(self):
        assert DimStep.__scd_type__ == 1

    def test_factexecution_is_transaction_fact(self):
        assert issubclass(FactExecution, TransactionFact)

    def test_factexecution_grain(self):
        assert FactExecution.__grain__ == "step_attempt"

    def test_factexecution_fk_references_dim_step(self):
        """FK must point at dim_step (not the old typo 'dimstep')."""
        fk = FactExecution.model_fields["step_key"].metadata
        fk_strings = [str(m) for m in fk]
        assert any("dim_step" in s for s in fk_strings)

    def test_factsagalifecycle_importable(self):
        assert FactSagaLifecycle is not None

    def test_factsagalifecycle_is_accumulating_fact(self):
        assert issubclass(FactSagaLifecycle, AccumulatingFact)

    def test_factsagalifecycle_grain(self):
        assert FactSagaLifecycle.__grain__ == "saga"

    def test_factsagalifecycle_has_milestone_fields(self):
        fields = FactSagaLifecycle.model_fields
        assert "started_at" in fields
        assert "completed_at" in fields
        assert "rolled_back_at" in fields
        assert "total_duration_ms" in fields
        assert "step_count" in fields
        assert "compensation_count" in fields


# ---------------------------------------------------------------------------
# SagaBronzeProcessor — sqldim TransformPipeline integration
# ---------------------------------------------------------------------------


class TestBronzeProcessor:
    """Verify that SagaBronzeProcessor applies sqldim transforms correctly."""

    def _processor(self) -> SagaBronzeProcessor:
        import duckdb

        return SagaBronzeProcessor(duckdb.connect(":memory:"))

    def test_process_sagas_lowercases_status(self):
        proc = self._processor()
        records = [
            {
                "saga_id": "s1",
                "saga_name": "OrderSaga",
                "status": "COMPLETED",
                "created_at": None,
                "updated_at": None,
            }
        ]
        result = proc.process_sagas(records)
        assert result[0]["status"] == "completed"

    def test_process_sagas_fills_null_saga_name(self):
        proc = self._processor()
        records = [
            {
                "saga_id": "s1",
                "saga_name": None,
                "status": "executing",
                "created_at": None,
                "updated_at": None,
            }
        ]
        result = proc.process_sagas(records)
        assert result[0]["saga_name"] == "unknown"

    def test_process_sagas_preserves_known_saga_name(self):
        proc = self._processor()
        records = [
            {
                "saga_id": "s1",
                "saga_name": "PaySaga",
                "status": "completed",
                "created_at": None,
                "updated_at": None,
            }
        ]
        result = proc.process_sagas(records)
        assert result[0]["saga_name"] == "PaySaga"

    def test_process_executions_lowercases_outcome(self):
        proc = self._processor()
        records = [
            {
                "saga_id": "s1",
                "saga_name": "OrderSaga",
                "step_name": "pay",
                "action": None,
                "outcome": "SUCCESS",
                "duration_ms": "50.0",
                "attempt": "1",
                "executed_at": None,
            }
        ]
        result = proc.process_executions(records)
        assert result[0]["outcome"] == "success"

    def test_process_executions_casts_duration_ms_to_float(self):
        proc = self._processor()
        records = [
            {
                "saga_id": "s1",
                "saga_name": "OrderSaga",
                "step_name": "pay",
                "action": None,
                "outcome": "success",
                "duration_ms": "75.5",
                "attempt": "1",
                "executed_at": None,
            }
        ]
        result = proc.process_executions(records)
        assert isinstance(result[0]["duration_ms"], float)
        assert result[0]["duration_ms"] == 75.5

    def test_process_executions_casts_attempt_to_int(self):
        proc = self._processor()
        records = [
            {
                "saga_id": "s1",
                "saga_name": "OrderSaga",
                "step_name": "pay",
                "action": None,
                "outcome": "success",
                "duration_ms": "10.0",
                "attempt": "3",
                "executed_at": None,
            }
        ]
        result = proc.process_executions(records)
        assert isinstance(result[0]["attempt"], int)
        assert result[0]["attempt"] == 3

    def test_process_sagas_empty_input_returns_empty(self):
        proc = self._processor()
        assert proc.process_sagas([]) == []

    def test_process_executions_empty_input_returns_empty(self):
        proc = self._processor()
        assert proc.process_executions([]) == []

    def test_process_executions_fills_null_saga_name(self):
        proc = self._processor()
        records = [
            {
                "saga_id": "s1",
                "saga_name": None,
                "step_name": "charge",
                "action": None,
                "outcome": "success",
                "duration_ms": "10.0",
                "attempt": "1",
                "executed_at": None,
            }
        ]
        result = proc.process_executions(records)
        assert result[0]["saga_name"] == "unknown"


# ---------------------------------------------------------------------------
# FactSagaLifecycle — accumulating snapshot populated by pipeline
# ---------------------------------------------------------------------------


class TestLifecycleLoading:
    """Verify that FactSagaLifecycle is correctly populated after load_from_records."""

    def _setup_with_steps(self) -> SagaAnalyticsPipeline:
        p = SagaAnalyticsPipeline()
        p.load_from_records(
            [_saga("s1", "OrderSaga", "completed"), _saga("s2", "OrderSaga", "rolled_back")],
            [
                _step("s1", "reserve", "success", 20.0),
                _step("s1", "charge", "success", 80.0),
                _step("s2", "reserve", "compensated", 30.0),
            ],
        )
        return p

    def test_lifecycle_row_created_for_each_saga(self):
        with self._setup_with_steps() as p:
            rows = p.query("SELECT COUNT(*) AS cnt FROM fact_saga_lifecycle")
        assert rows[0]["cnt"] == 2

    def test_lifecycle_step_count_correct(self):
        with self._setup_with_steps() as p:
            rows = p.query("SELECT step_count FROM fact_saga_lifecycle WHERE saga_id = 's1'")
        assert rows[0]["step_count"] == 2

    def test_lifecycle_total_duration_ms_correct(self):
        with self._setup_with_steps() as p:
            rows = p.query("SELECT total_duration_ms FROM fact_saga_lifecycle WHERE saga_id = 's1'")
        assert rows[0]["total_duration_ms"] == pytest.approx(100.0)

    def test_lifecycle_compensation_count_correct(self):
        with self._setup_with_steps() as p:
            rows = p.query(
                "SELECT compensation_count FROM fact_saga_lifecycle WHERE saga_id = 's2'"
            )
        assert rows[0]["compensation_count"] == 1

    def test_lifecycle_milestones_query(self):
        with self._setup_with_steps() as p:
            rows = p.query(SagaQueries.SAGA_LIFECYCLE_MILESTONES)
        assert len(rows) == 2
        cols = set(rows[0].keys())
        assert {"saga_name", "saga_id", "total_duration_ms", "step_count"}.issubset(cols)
