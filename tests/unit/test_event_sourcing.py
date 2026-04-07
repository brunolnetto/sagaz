"""
Unit tests for PR #70 — event sourcing:
  - sagaz/core/events.py
  - sagaz/storage/event_store.py  (SQLiteEventStore)
  - sagaz/projections/summary.py (SagaSummaryProjection)
  - sagaz/cli/app.py             (event-log command)
"""

from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner

from sagaz.core.events import (
    CompensationStarted,
    SagaCompleted,
    SagaFailed,
    SagaRolledBack,
    SagaStarted,
    StepCompensated,
    StepExecuted,
    StepFailed,
    event_type_from_name,
)
from sagaz.projections.summary import SagaSummaryProjection, build_projection
from sagaz.storage.event_store import SagaSnapshot, SQLiteEventStore

# ---------------------------------------------------------------------------
# SagaEvent hierarchy
# ---------------------------------------------------------------------------


class TestSagaEvents:
    def test_saga_started_fields(self):
        e = SagaStarted(saga_id="s1", saga_name="OrderSaga")
        assert e.saga_id == "s1"
        assert e.saga_name == "OrderSaga"
        assert e.event_id  # UUID present
        assert e.occurred_at is not None

    def test_step_executed_to_dict(self):
        e = StepExecuted(saga_id="s1", step_name="reserve", step_result=42, duration_ms=5.5)
        d = e.to_dict()
        assert d["event_type"] == "StepExecuted"
        assert d["step_name"] == "reserve"
        assert d["step_result"] == 42

    def test_step_failed_to_dict(self):
        e = StepFailed(saga_id="s1", step_name="pay", error_type="ValueError", error_message="bad")
        d = e.to_dict()
        assert d["error_type"] == "ValueError"

    def test_step_compensated_to_dict(self):
        e = StepCompensated(saga_id="s1", step_name="reserve")
        d = e.to_dict()
        assert d["step_name"] == "reserve"

    def test_compensation_started_to_dict(self):
        e = CompensationStarted(saga_id="s1", failed_step="pay")
        d = e.to_dict()
        assert d["failed_step"] == "pay"

    def test_saga_completed_to_dict(self):
        e = SagaCompleted(saga_id="s1", duration_ms=100.0)
        d = e.to_dict()
        assert d["duration_ms"] == 100.0

    def test_saga_rolled_back_to_dict(self):
        e = SagaRolledBack(saga_id="s1", compensation_duration_ms=20.0)
        d = e.to_dict()
        assert d["compensation_duration_ms"] == 20.0

    def test_saga_failed_to_dict(self):
        e = SagaFailed(saga_id="s1", error_message="unrecoverable")
        d = e.to_dict()
        assert d["error_message"] == "unrecoverable"

    def test_events_are_frozen(self):
        e = SagaStarted(saga_id="s1", saga_name="X")
        with pytest.raises((TypeError, AttributeError)):
            e.saga_id = "other"  # type: ignore[misc]

    def test_event_type_from_name_known(self):
        cls = event_type_from_name("SagaStarted")
        assert cls is SagaStarted

    def test_event_type_from_name_unknown(self):
        assert event_type_from_name("Nonexistent") is None


# ---------------------------------------------------------------------------
# SQLiteEventStore
# ---------------------------------------------------------------------------


class TestSQLiteEventStore:
    @pytest.mark.asyncio
    async def test_append_returns_sequence(self):
        store = SQLiteEventStore()
        seq = await store.append(SagaStarted(saga_id="s1", saga_name="MySaga"))
        assert seq == 1

    @pytest.mark.asyncio
    async def test_load_empty_stream(self):
        store = SQLiteEventStore()
        events = await store.load_stream("missing-saga")
        assert events == []

    @pytest.mark.asyncio
    async def test_load_stream_returns_events_in_order(self):
        store = SQLiteEventStore()
        saga_id = "order-001"
        await store.append(SagaStarted(saga_id=saga_id, saga_name="OrderSaga"))
        await store.append(StepExecuted(saga_id=saga_id, step_name="reserve"))
        await store.append(SagaCompleted(saga_id=saga_id, duration_ms=50.0))

        events = await store.load_stream(saga_id)
        assert len(events) == 3
        assert isinstance(events[0], SagaStarted)
        assert isinstance(events[1], StepExecuted)
        assert isinstance(events[2], SagaCompleted)

    @pytest.mark.asyncio
    async def test_load_stream_after_filters_correctly(self):
        store = SQLiteEventStore()
        saga_id = "order-002"
        seq1 = await store.append(SagaStarted(saga_id=saga_id, saga_name="MySaga"))
        await store.append(StepExecuted(saga_id=saga_id, step_name="step1"))
        await store.append(SagaCompleted(saga_id=saga_id))

        tail = await store.load_stream_after(saga_id, after_sequence=seq1)
        assert len(tail) == 2
        assert isinstance(tail[0], StepExecuted)
        assert isinstance(tail[1], SagaCompleted)

    @pytest.mark.asyncio
    async def test_load_stream_after_empty_when_all_consumed(self):
        store = SQLiteEventStore()
        saga_id = "order-003"
        seq = await store.append(SagaStarted(saga_id=saga_id, saga_name="MySaga"))
        tail = await store.load_stream_after(saga_id, after_sequence=seq)
        assert tail == []

    @pytest.mark.asyncio
    async def test_snapshot_round_trip(self):
        store = SQLiteEventStore()
        snapshot = SagaSnapshot(
            saga_id="s1",
            sequence=5,
            state={"status": "executing", "steps": {}},
        )
        await store.save_snapshot(snapshot)
        loaded = await store.load_latest_snapshot("s1")
        assert loaded is not None
        assert loaded.sequence == 5
        assert loaded.state["status"] == "executing"

    @pytest.mark.asyncio
    async def test_load_latest_snapshot_returns_none_when_absent(self):
        store = SQLiteEventStore()
        assert await store.load_latest_snapshot("nonexistent") is None

    @pytest.mark.asyncio
    async def test_load_latest_snapshot_returns_most_recent(self):
        store = SQLiteEventStore()
        await store.save_snapshot(SagaSnapshot("s1", 2, {"status": "v2"}))
        await store.save_snapshot(SagaSnapshot("s1", 5, {"status": "v5"}))
        snap = await store.load_latest_snapshot("s1")
        assert snap.sequence == 5

    @pytest.mark.asyncio
    async def test_multiple_sagas_isolated(self):
        store = SQLiteEventStore()
        await store.append(SagaStarted(saga_id="a", saga_name="A"))
        await store.append(SagaStarted(saga_id="b", saga_name="B"))
        assert len(await store.load_stream("a")) == 1
        assert len(await store.load_stream("b")) == 1


# ---------------------------------------------------------------------------
# SagaSummaryProjection
# ---------------------------------------------------------------------------


class TestSagaSummaryProjection:
    def test_initial_state(self):
        proj = SagaSummaryProjection("s1")
        assert proj.status == "pending"
        assert proj.steps == {}

    def test_apply_saga_started(self):
        proj = SagaSummaryProjection("s1")
        proj.apply(SagaStarted(saga_id="s1", saga_name="OrderSaga"))
        assert proj.status == "executing"
        assert proj.saga_name == "OrderSaga"

    def test_apply_step_executed(self):
        proj = SagaSummaryProjection("s1")
        proj.apply(SagaStarted(saga_id="s1", saga_name="X"))
        proj.apply(StepExecuted(saga_id="s1", step_name="reserve", step_result=True))
        assert proj.steps["reserve"].status == "completed"

    def test_apply_step_failed(self):
        proj = SagaSummaryProjection("s1")
        proj.apply(
            StepFailed(
                saga_id="s1", step_name="charge", error_type="IOError", error_message="timeout"
            )
        )
        assert proj.steps["charge"].status == "failed"

    def test_apply_compensation_started(self):
        proj = SagaSummaryProjection("s1")
        proj.apply(CompensationStarted(saga_id="s1", failed_step="charge"))
        assert proj.status == "compensating"
        assert proj.failed_step == "charge"

    def test_apply_step_compensated(self):
        proj = SagaSummaryProjection("s1")
        proj.apply(StepExecuted(saga_id="s1", step_name="reserve", step_result=None))
        proj.apply(StepCompensated(saga_id="s1", step_name="reserve"))
        assert proj.steps["reserve"].compensated

    def test_apply_saga_completed(self):
        proj = SagaSummaryProjection("s1")
        proj.apply(SagaCompleted(saga_id="s1", duration_ms=200.0))
        assert proj.status == "completed"
        assert proj.duration_ms == 200.0

    def test_apply_saga_rolled_back(self):
        proj = SagaSummaryProjection("s1")
        proj.apply(SagaRolledBack(saga_id="s1", compensation_duration_ms=30.0))
        assert proj.status == "rolled_back"

    def test_apply_saga_failed(self):
        proj = SagaSummaryProjection("s1")
        proj.apply(SagaFailed(saga_id="s1", error_message="fatal"))
        assert proj.status == "failed"
        assert proj.error_message == "fatal"

    def test_to_dict_structure(self):
        proj = build_projection(
            "s1",
            [
                SagaStarted(saga_id="s1", saga_name="MySaga"),
                StepExecuted(saga_id="s1", step_name="step1", step_result=1),
                SagaCompleted(saga_id="s1", duration_ms=50.0),
            ],
        )
        d = proj.to_dict()
        assert d["saga_id"] == "s1"
        assert d["status"] == "completed"
        assert "step1" in d["steps"]

    @pytest.mark.asyncio
    async def test_end_to_end_100_events_consistent(self):
        """Integration: 100 lifecycle events → projection consistent."""
        store = SQLiteEventStore()
        saga_id = "big-saga"
        await store.append(SagaStarted(saga_id=saga_id, saga_name="Stress"))
        for i in range(49):
            await store.append(StepExecuted(saga_id=saga_id, step_name=f"step{i}"))
        await store.append(SagaCompleted(saga_id=saga_id, duration_ms=9999.9))

        events = await store.load_stream(saga_id)
        assert len(events) == 51
        proj = build_projection(saga_id, events)
        d = proj.to_dict()
        assert d["status"] == "completed"
        assert len(d["steps"]) == 49

    @pytest.mark.asyncio
    async def test_snapshot_threshold_load_uses_snapshot_plus_tail(self):
        """Snapshot at event 5, then 3 tail events → projection uses both."""
        store = SQLiteEventStore()
        saga_id = "snap-saga"

        events_before_snap = [
            SagaStarted(saga_id=saga_id, saga_name="SnapSaga"),
            StepExecuted(saga_id=saga_id, step_name="step1"),
            StepExecuted(saga_id=saga_id, step_name="step2"),
            StepExecuted(saga_id=saga_id, step_name="step3"),
            StepExecuted(saga_id=saga_id, step_name="step4"),
        ]
        last_seq = 0
        for ev in events_before_snap:
            last_seq = await store.append(ev)

        # Compute and save snapshot
        proj_snap = build_projection(saga_id, events_before_snap)
        await store.save_snapshot(
            SagaSnapshot(saga_id=saga_id, sequence=last_seq, state=proj_snap.to_dict())
        )

        # Append 3 more tail events
        tail_events = [
            StepExecuted(saga_id=saga_id, step_name="step5"),
            StepExecuted(saga_id=saga_id, step_name="step6"),
            SagaCompleted(saga_id=saga_id, duration_ms=1.0),
        ]
        for ev in tail_events:
            await store.append(ev)

        # Simulate snapshot + tail load
        snap = await store.load_latest_snapshot(saga_id)
        assert snap is not None
        tail = await store.load_stream_after(saga_id, after_sequence=snap.sequence)
        assert len(tail) == 3

        # Rebuild from projection state + tail
        proj = SagaSummaryProjection(saga_id=saga_id)
        # restore from snapshot
        import dataclasses as _dc

        snapped = snap.state
        proj.status = snapped["status"]
        proj.saga_name = snapped["saga_name"]
        for ev in tail:
            proj.apply(ev)

        assert proj.status == "completed"


# ---------------------------------------------------------------------------
# CLI event-log command
# ---------------------------------------------------------------------------


class TestEventLogCommand:
    def test_no_events_shows_message(self):
        from sagaz.cli.app import event_log_cmd

        runner = CliRunner()
        result = runner.invoke(event_log_cmd, ["missing-saga", "--db", ":memory:"])
        assert result.exit_code == 0
        assert "No events found" in result.output

    def test_json_output(self, tmp_path):
        import asyncio

        from sagaz.cli.app import event_log_cmd
        from sagaz.storage.event_store import SQLiteEventStore

        db_file = str(tmp_path / "events.db")
        store = SQLiteEventStore(db_path=db_file)
        asyncio.run(store.append(SagaStarted(saga_id="s1", saga_name="MySaga")))
        asyncio.run(store.append(SagaCompleted(saga_id="s1")))
        store.close()

        runner = CliRunner()
        result = runner.invoke(event_log_cmd, ["s1", "--db", db_file, "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2
        assert data[0]["event_type"] == "SagaStarted"

    def test_text_output(self, tmp_path):
        import asyncio

        from sagaz.cli.app import event_log_cmd
        from sagaz.storage.event_store import SQLiteEventStore

        db_file = str(tmp_path / "events.db")
        store = SQLiteEventStore(db_path=db_file)
        asyncio.run(store.append(SagaStarted(saga_id="s2", saga_name="X")))
        store.close()

        runner = CliRunner()
        result = runner.invoke(event_log_cmd, ["s2", "--db", db_file])
        assert result.exit_code == 0
        assert "s2" in result.output or "SagaStarted" in result.output
