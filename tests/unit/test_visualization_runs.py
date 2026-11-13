"""Tests for the visualization run projection and runtime diagram."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sagaz.visualization.runs import RunStore, saga_runtime_diagram

T0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)


def ev(event_type, saga_id="s1", saga_name="OrderSaga", step=None, error=None, at_ms=0):
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "saga_id": saga_id,
        "saga_name": saga_name,
        "step_name": step,
        "error_type": error,
        "occurred_at": (T0 + timedelta(milliseconds=at_ms)).isoformat(),
    }


def successful_run(store, saga_id="s1", saga_name="OrderSaga", total_ms=30):
    store.apply(ev("saga.started", saga_id, saga_name))
    store.apply(ev("step.started", saga_id, saga_name, "reserve", at_ms=1))
    store.apply(ev("step.succeeded", saga_id, saga_name, "reserve", at_ms=11))
    store.apply(ev("step.started", saga_id, saga_name, "charge", at_ms=12))
    store.apply(ev("step.succeeded", saga_id, saga_name, "charge", at_ms=22))
    store.apply(ev("saga.completed", saga_id, saga_name, at_ms=total_ms))


def failed_run(store, saga_id="f1", saga_name="OrderSaga"):
    store.apply(ev("saga.started", saga_id, saga_name))
    store.apply(ev("step.started", saga_id, saga_name, "reserve", at_ms=1))
    store.apply(ev("step.succeeded", saga_id, saga_name, "reserve", at_ms=5))
    store.apply(ev("step.started", saga_id, saga_name, "charge", at_ms=6))
    store.apply(ev("step.failed", saga_id, saga_name, "charge", error="CardDeclined", at_ms=9))
    store.apply(ev("step.compensation_started", saga_id, saga_name, "reserve", at_ms=10))
    store.apply(ev("step.compensated", saga_id, saga_name, "reserve", at_ms=14))
    store.apply(ev("saga.failed", saga_id, saga_name, error="CardDeclined", at_ms=15))


class TestRunProjection:
    def test_successful_run_is_projected(self):
        store = RunStore()
        successful_run(store)

        run = store.get("s1")
        assert run is not None
        assert run.status == "completed"
        assert run.duration_ms == 30
        assert [s.name for s in run.steps.values()] == ["reserve", "charge"]
        assert all(s.status == "completed" for s in run.steps.values())
        assert run.steps["reserve"].duration_ms == 10
        assert run.current_step is None

        data = run.to_dict()
        assert data["step_count"] == 2
        assert len(data["events"]) == 6
        assert data["steps"][0]["started_at"] is not None

    def test_failed_run_tracks_compensation(self):
        store = RunStore()
        failed_run(store)

        run = store.get("f1")
        assert run.status == "failed"
        assert run.error_type == "CardDeclined"
        assert run.steps["charge"].status == "failed"
        assert run.steps["charge"].error_type == "CardDeclined"
        assert run.steps["reserve"].status == "compensated"
        assert run.steps["reserve"].compensation_duration_ms == 4

    def test_compensation_marks_running_run_as_compensating(self):
        store = RunStore()
        store.apply(ev("saga.started"))
        store.apply(ev("step.started", step="reserve"))
        store.apply(ev("step.compensation_started", step="reserve"))

        run = store.get("s1")
        assert run.status == "compensating"
        assert run.current_step == "reserve"

    def test_events_without_saga_started_still_create_run(self):
        store = RunStore()
        store.apply(ev("step.started", step="reserve"))

        run = store.get("s1")
        assert run.status == "running"
        assert run.started_at is None
        assert run.duration_ms is None
        assert run.current_step == "reserve"

    def test_step_event_without_step_name_is_ignored(self):
        store = RunStore()
        store.apply(ev("step.started", step=None))
        assert store.get("s1").steps == {}

    def test_duplicate_event_ids_are_ignored(self):
        store = RunStore()
        event = ev("saga.started")
        assert store.apply(event) is True
        assert store.apply(dict(event)) is False
        assert len(store.get("s1").events) == 1

    def test_seen_event_ids_are_bounded(self):
        store = RunStore(max_seen_event_ids=2)
        first = ev("saga.started")
        store.apply(first)
        store.apply(ev("step.started", step="a"))
        store.apply(ev("step.succeeded", step="a"))
        # The first id has been forgotten, so it is applied again.
        assert store.apply(first) is True

    def test_accepts_datetime_instances(self):
        store = RunStore()
        event = ev("saga.started")
        event["occurred_at"] = T0
        store.apply(event)
        assert store.get("s1").started_at == T0

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [({"max_runs": 0}, "max_runs"), ({"max_seen_event_ids": 0}, "max_seen")],
    )
    def test_invalid_configuration(self, kwargs, match):
        with pytest.raises(ValueError, match=match):
            RunStore(**kwargs)


class TestEviction:
    def test_finished_runs_are_evicted_before_running_ones(self):
        store = RunStore(max_runs=2)
        store.apply(ev("saga.started", saga_id="running"))
        successful_run(store, saga_id="done")
        store.apply(ev("saga.started", saga_id="new"))

        assert len(store) == 2
        assert store.get("done") is None
        assert store.get("running") is not None

    def test_oldest_run_is_evicted_when_all_running(self):
        store = RunStore(max_runs=2)
        for saga_id in ("a", "b", "c"):
            store.apply(ev("saga.started", saga_id=saga_id))

        assert store.get("a") is None
        assert store.get("c") is not None


class TestQueries:
    def test_list_is_newest_first_with_filters_and_pagination(self):
        store = RunStore()
        successful_run(store, saga_id="a")
        failed_run(store, saga_id="b")
        successful_run(store, saga_id="c", saga_name="RefundSaga")

        items, total = store.list()
        assert total == 3
        assert [r.saga_id for r in items] == ["c", "b", "a"]

        items, total = store.list(status="completed")
        assert total == 2
        assert {r.saga_id for r in items} == {"a", "c"}

        items, total = store.list(saga_name="OrderSaga", limit=1, offset=1)
        assert total == 2
        assert [r.saga_id for r in items] == ["a"]

    def test_summary_aggregates(self):
        store = RunStore()
        successful_run(store, saga_id="a", total_ms=10)
        successful_run(store, saga_id="b", total_ms=30)
        failed_run(store, saga_id="c")
        store.apply(ev("saga.started", saga_id="d"))

        summary = store.summary()
        assert summary["total_runs"] == 4
        assert summary["by_status"] == {
            "running": 1,
            "compensating": 0,
            "completed": 2,
            "failed": 1,
        }
        assert summary["success_rate"] == pytest.approx(2 / 3)
        assert summary["duration_ms"]["max"] == 30
        assert summary["duration_ms"]["p50"] == 15
        assert summary["by_saga"]["OrderSaga"]["completed"] == 2

        steps = {s["step_name"]: s for s in summary["steps"]}
        assert steps["charge"]["executions"] == 3
        assert steps["charge"]["failures"] == 1
        assert steps["reserve"]["compensations"] == 1
        assert steps["reserve"]["avg_duration_ms"] is not None

    def test_empty_summary(self):
        summary = RunStore().summary()
        assert summary["total_runs"] == 0
        assert summary["success_rate"] is None
        assert summary["duration_ms"] == {"avg": None, "p50": None, "p95": None, "max": None}
        assert summary["steps"] == []

    def test_step_without_duration_has_no_average(self):
        store = RunStore()
        store.apply(ev("step.started", step="reserve"))
        (step,) = store.summary()["steps"]
        assert step["avg_duration_ms"] is None


class TestRuntimeDiagram:
    def test_completed_run_is_colour_coded(self):
        store = RunStore()
        successful_run(store)
        diagram = saga_runtime_diagram(store.get("s1"))

        assert diagram.startswith("flowchart LR")
        assert '  s0["reserve<br/>10 ms"]:::completed' in diagram
        assert "  start --> s0" in diagram
        assert "  s0 --> s1" in diagram
        assert "  finish((done)):::completed" in diagram
        assert "classDef completed fill:#16a34a" in diagram

    def test_failed_run_shows_failure_and_compensation(self):
        store = RunStore()
        failed_run(store)
        diagram = saga_runtime_diagram(store.get("f1"), direction="TB")

        assert diagram.startswith("flowchart TB")
        assert ":::compensated" in diagram
        assert ":::failed" in diagram
        assert "finish((rolled back)):::failed" in diagram
        assert "classDef compensated fill:#4f46e5" in diagram
        assert "classDef compensating fill:#f59e0b" in diagram

    def test_running_run_has_no_finish_node(self):
        store = RunStore()
        store.apply(ev("saga.started"))
        store.apply(ev("step.started", step="reserve"))
        diagram = saga_runtime_diagram(store.get("s1"))

        assert '  s0["reserve"]:::running' in diagram
        assert "finish" not in diagram

    def test_untrusted_step_names_are_escaped(self):
        store = RunStore()
        store.apply(ev("step.started", step='x"]\nclick s0 "javascript:alert(1)"<b>&'))
        diagram = saga_runtime_diagram(store.get("s1"))
        node_line = next(line for line in diagram.splitlines() if line.startswith("  s0["))

        assert '"' not in node_line.removeprefix('  s0["').removesuffix('"]:::running')
        assert "<b>" not in diagram
        assert "\nclick" not in diagram
        assert "#quot;" in node_line
        assert "#lt;b#gt;" in node_line
        assert "#amp;" in node_line
