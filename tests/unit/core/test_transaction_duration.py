"""A transaction never ends before it started, whatever the wall clock did (#653)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sagaz.choreography import Event
from sagaz.choreography.tracker import ChoreographyTracker
from sagaz.core.events import SagaCompleted, SagaFailed, SagaRolledBack, SagaStarted
from sagaz.core.storage.saga_log import InMemorySagaLogStore
from sagaz.core.storage.saga_log._model import ended_at
from sagaz.core.storage.saga_log.event_store import SagaLogEventStore
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore

START = datetime(2026, 11, 25, 12, 0, 0, tzinfo=UTC)
BACK = timedelta(milliseconds=548)  # the wall clock stepped back by this much


@pytest.fixture(params=["memory", "sqlite"])
async def log(request, tmp_path):
    store = (
        InMemorySagaLogStore()
        if request.param == "memory"
        else SQLiteSagaLogStore(str(tmp_path / "log.db"))
    )
    yield store
    await store.close()


class TestTheRule:
    def test_a_clock_that_did_not_step_back_changes_nothing(self):
        observed = START + timedelta(milliseconds=120)
        assert ended_at(START, observed, 120.0) == observed
        assert ended_at(START, observed) == observed
        # The measured duration starts a little before the start event: it does not win.
        assert ended_at(START, observed, 125.0) == observed

    def test_an_end_observed_before_the_start_uses_the_measured_duration(self):
        assert ended_at(START, START - BACK, 120.0) == START + timedelta(milliseconds=120)

    def test_without_a_measured_duration_it_ends_when_it_started(self):
        assert ended_at(START, START - BACK) == START
        assert ended_at(START, START - BACK, -5.0) == START  # a negative duration is no duration

    def test_a_rerun_long_after_the_start_ends_when_observed(self):
        observed = START + timedelta(hours=3)
        assert ended_at(START, observed, 120.0) == observed


@pytest.mark.parametrize("ending", [SagaCompleted, SagaRolledBack, SagaFailed])
async def test_an_orchestrated_saga_ended_by_a_clock_that_stepped_back(log, ending):
    store = SagaLogEventStore(log)
    await store.append(SagaStarted("s-1", saga_name="order", occurred_at=START))
    await store.append(
        ending("s-1", saga_name="order", occurred_at=START - BACK, duration_ms=120.0)
    )
    transaction = await log.get_transaction("s-1")
    assert transaction.ended_at - transaction.started_at == timedelta(milliseconds=120)


async def test_a_saga_whose_start_was_not_recorded_has_no_negative_duration(log):
    store = SagaLogEventStore(log)
    await store.append(SagaCompleted("s-2", saga_name="order", occurred_at=START, duration_ms=80.0))
    transaction = await log.get_transaction("s-2")
    assert transaction.ended_at >= transaction.started_at


async def test_a_choreographed_transaction_completed_by_a_service_whose_clock_is_behind():
    """The completion event's clock is behind the clock of the service that began."""
    from sagaz.choreography import ChoreographedSaga, ChoreographyEngine, EventBus

    log = InMemorySagaLogStore()
    bus = EventBus()
    engine = ChoreographyEngine(bus, saga_log=log, completion_events={"order.completed"})
    orders = ChoreographedSaga(name="orders")
    engine.register(orders)
    tracker = ChoreographyTracker(bus, saga_log=log, completion_events={"order.completed"})
    await engine.start()
    await tracker.start()
    try:
        begun = await orders.begin("order.created", correlation_id="t-1")
        await engine.relay.relay()
        behind = begun.created_at - BACK
        completed = Event("order.completed", saga_id="t-1", created_at=behind, source="payments")
        await orders._state.publish("payments", completed, bus.publish)
        await engine.relay.relay()
    finally:
        await tracker.stop()
        await engine.stop()
    transaction = await log.get_transaction("t-1")
    assert transaction.status == "completed"
    assert transaction.ended_at >= transaction.started_at
