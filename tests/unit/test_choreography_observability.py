"""Choreography is traced and seen by listeners, as orchestration is (#563)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from sagaz.choreography import ChoreographedSaga, ChoreographyEngine, Event, EventBus
from sagaz.choreography.events import COMPENSATE
from sagaz.choreography.tracker import ChoreographyTracker
from sagaz.core.listeners import LoggingSagaListener, SagaListener


class Recorder(SagaListener):
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        self.calls.append(("saga_start", saga_name, saga_id))

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        self.calls.append(("step_enter", saga_name, step_name, ctx["saga_id"]))

    async def on_step_success(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], result: Any
    ) -> None:
        self.calls.append(("step_success", saga_name, step_name))

    async def on_step_failure(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self.calls.append(("step_failure", saga_name, step_name, str(error)))

    async def on_compensation_start(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        self.calls.append(("compensation_start", saga_name, step_name))

    async def on_compensation_complete(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        self.calls.append(("compensation_complete", saga_name, step_name))

    async def on_compensation_failed(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self.calls.append(("compensation_failed", saga_name, step_name, str(error)))

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        self.calls.append(("saga_complete", saga_name, saga_id))

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self.calls.append(("saga_failed", saga_name, saga_id, str(error)))


def shop(*, pay_fails: bool = False, undo_fails: bool = False) -> list[ChoreographedSaga]:
    async def reserve(event: Event, me: ChoreographedSaga) -> None:
        await me.emit("stock.reserved")

    async def release(event: Event, me: ChoreographedSaga) -> None:
        if undo_fails:
            msg = "warehouse offline"
            raise RuntimeError(msg)

    async def pay(event: Event, me: ChoreographedSaga) -> None:
        if pay_fails:
            msg = "card declined"
            raise RuntimeError(msg)
        await me.emit("order.completed")

    return [
        ChoreographedSaga(name="orders"),
        ChoreographedSaga(name="inventory").on("order.created", reserve, release),
        ChoreographedSaga(name="payments").on("stock.reserved", pay),
    ]


async def run(
    engine: ChoreographyEngine,
    participants: list[ChoreographedSaga],
    tracker: ChoreographyTracker | None = None,
) -> None:
    for participant in participants:
        engine.register(participant)
    await engine.start()
    if tracker is not None:
        await tracker.start()
    try:
        await participants[0].begin("order.created", {"order_id": "o-1"}, correlation_id="t-1")
        for _ in range(10):  # the unified log publishes through its relay
            if engine.relay is not None:
                await engine.relay.relay()
    finally:
        if tracker is not None:
            await tracker.stop()
        await engine.stop()


COMPLETIONS = ["order.completed"]


def engine_with(*listeners: SagaListener, saga_log: Any = None) -> ChoreographyEngine:
    return ChoreographyEngine(
        EventBus(),
        completion_events=COMPLETIONS,
        listeners=listeners,
        retry_backoff_base=0,
        saga_log=saga_log,
        relay_interval=3600,  # the test relays itself
    )


def tracker_for(engine: ChoreographyEngine, *listeners: SagaListener, saga_log: Any = None):
    return ChoreographyTracker(
        engine._bus, completion_events=COMPLETIONS, saga_log=saga_log, listeners=listeners
    )


def saga_hooks(recorder: Recorder) -> list[tuple[str, ...]]:
    return [call for call in recorder.calls if call[0].startswith("saga_")]


class TestParticipantListeners:
    """The engine's listeners see each participant's steps and compensations."""

    async def test_each_handler_is_a_step(self):
        recorder = Recorder()
        await run(engine_with(recorder), shop())
        assert ("step_enter", "inventory", "order.created", "t-1") in recorder.calls
        assert ("step_success", "inventory", "order.created") in recorder.calls
        assert ("step_success", "payments", "stock.reserved") in recorder.calls
        assert saga_hooks(recorder) == []  # a participant does not see the whole

    async def test_a_failed_step_and_the_compensation_it_causes(self):
        recorder = Recorder()
        await run(engine_with(recorder), shop(pay_fails=True))
        assert ("step_failure", "payments", "stock.reserved", "card declined") in recorder.calls
        assert ("compensation_start", "inventory", "order.created") in recorder.calls
        assert ("compensation_complete", "inventory", "order.created") in recorder.calls
        assert saga_hooks(recorder) == []

    async def test_a_failed_compensation_is_reported(self):
        recorder = Recorder()
        await run(engine_with(recorder), shop(pay_fails=True, undo_fails=True))
        assert (
            "compensation_failed",
            "inventory",
            "order.created",
            "warehouse offline",
        ) in recorder.calls
        assert ("compensation_complete", "inventory", "order.created") not in recorder.calls

    async def test_a_listener_that_raises_does_not_break_the_transaction(self, caplog):
        class Broken(SagaListener):
            async def on_step_enter(self, *args: Any) -> None:
                msg = "listener bug"
                raise RuntimeError(msg)

        recorder = Recorder()
        with caplog.at_level(logging.WARNING, logger="sagaz.choreography"):
            await run(engine_with(Broken(), recorder), shop())
        assert ("step_success", "payments", "stock.reserved") in recorder.calls
        assert "listener bug" in caplog.text

    async def test_the_built_in_logging_listener_works_as_it_is(self, caplog):
        with caplog.at_level(logging.INFO):
            await run(engine_with(LoggingSagaListener()), shop())
        assert "inventory" in caplog.text


def unified_log() -> Any:
    from sagaz.core.storage.saga_log import create_saga_log_store

    return create_saga_log_store("memory://")


@pytest.mark.parametrize("on_log", [False, True], ids=["projection", "unified-log"])
class TestTransactionListeners:
    """The tracker's listeners see each transaction once, however many participants."""

    async def track(self, on_log: bool, **failures: bool) -> Recorder:
        recorder = Recorder()
        log = unified_log() if on_log else None
        engine = engine_with(saga_log=log)
        await run(engine, shop(**failures), tracker_for(engine, recorder, saga_log=log))
        return recorder

    async def test_a_completed_transaction_is_started_and_completed_once(self, on_log):
        recorder = await self.track(on_log)
        assert saga_hooks(recorder) == [
            ("saga_start", "choreography", "t-1"),
            ("saga_complete", "choreography", "t-1"),
        ]

    async def test_a_rolled_back_transaction_fails_once_with_the_reported_reason(self, on_log):
        recorder = await self.track(on_log, pay_fails=True)
        hooks = saga_hooks(recorder)
        assert [call[0] for call in hooks] == ["saga_start", "saga_failed"]
        assert "payments" in hooks[1][3]
        assert "card declined" in hooks[1][3]

    async def test_a_failed_compensation_says_so(self, on_log):
        recorder = await self.track(on_log, pay_fails=True, undo_fails=True)
        failed = [call for call in saga_hooks(recorder) if call[0] == "saga_failed"]
        assert len(failed) == 1
        assert "a compensation failed too" in failed[0][3]


async def test_the_context_names_the_initiators_and_participants():
    seen: list[dict[str, Any]] = []

    class Ctx(SagaListener):
        async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]):
            seen.append(ctx)

    engine = engine_with()
    await run(engine, shop(), tracker_for(engine, Ctx()))
    assert seen[0]["initiators"] == ["orders"]
    assert seen[0]["participants"] == ["orders", "inventory", "payments"]
    assert seen[0]["status"] == "completed"
    assert seen[0]["tenant_id"] == "default"


async def test_a_redelivered_first_event_does_not_start_the_transaction_again():
    recorder = Recorder()
    bus = EventBus()
    tracker = ChoreographyTracker(bus, listeners=[recorder])
    await tracker.start()
    first = Event("order.created", saga_id="t-1", source="orders")
    await bus.publish(first)
    await bus.publish(first)  # an at-least-once bus delivers it again
    assert saga_hooks(recorder) == [("saga_start", "choreography", "t-1")]


@pytest.fixture
def spans(monkeypatch):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from sagaz.choreography import _observe

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(_observe, "tracer", lambda: provider.get_tracer("test"))
    return exporter


def by_name(exporter: Any) -> dict[str, Any]:
    return {span.name: span for span in exporter.get_finished_spans()}


class TestTracing:
    async def test_a_transaction_is_one_trace(self, spans):
        await run(engine_with(), shop())
        found = by_name(spans)
        begin = found["orders begin order.created"]
        reserve = found["inventory handle order.created"]
        pay = found["payments handle stock.reserved"]
        assert {s.context.trace_id for s in found.values()} == {begin.context.trace_id}
        assert reserve.parent.span_id == begin.context.span_id
        assert pay.parent.span_id == reserve.context.span_id  # emitted inside reserve's span
        assert reserve.attributes["sagaz.correlation_id"] == "t-1"
        assert reserve.status.is_ok

    async def test_a_failed_handler_and_compensation_are_errors_in_the_trace(self, spans):
        await run(engine_with(), shop(pay_fails=True, undo_fails=True))
        found = by_name(spans)
        pay = found["payments handle stock.reserved"]
        assert not pay.status.is_ok
        assert "card declined" in pay.status.description
        compensation = found["inventory compensate transaction " + COMPENSATE]
        assert compensation.parent.span_id == pay.context.span_id  # caused by the failure
        undo = found["inventory compensate order.created"]
        assert undo.parent.span_id == compensation.context.span_id
        assert "warehouse offline" in undo.status.description
        assert len({s.context.trace_id for s in found.values()}) == 1

    async def test_the_trace_context_travels_with_the_event(self):
        pytest.importorskip("opentelemetry.sdk")
        event = Event("x", trace_context={"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"})
        assert Event.from_dict(event.to_dict()).trace_context == event.trace_context
        assert Event.from_dict({**event.to_dict(), "trace_context": None}).trace_context == {}
        old = {k: v for k, v in event.to_dict().items() if k != "trace_context"}
        assert Event.from_dict(old).trace_context == {}  # events published before 2.6.0

    async def test_an_uninstrumented_participant_passes_the_trace_on(self, monkeypatch):
        from sagaz.choreography import _observe

        monkeypatch.setattr(_observe, "_trace", lambda: None)  # no opentelemetry here
        emitted: list[Event] = []
        bus = EventBus()
        bus.subscribe("stock.reserved", lambda event: emitted.append(event))

        async def reserve(event: Event, me: ChoreographedSaga) -> None:
            await me.emit("stock.reserved")

        engine = ChoreographyEngine(bus)
        engine.register(ChoreographedSaga(name="inventory").on("order.created", reserve))
        await engine.start()
        try:
            await bus.publish(Event("order.created", saga_id="t-1", trace_context=TRACEPARENT))
        finally:
            await engine.stop()
        assert emitted[0].trace_context == TRACEPARENT

    def test_a_caused_event_inherits_the_trace_context(self):
        cause = Event("a", saga_id="t-1", trace_context=TRACEPARENT)
        assert Event("b").caused_by(cause).trace_context == TRACEPARENT
        own = {"traceparent": "00-" + "3" * 32 + "-" + "4" * 16 + "-01"}
        assert Event("b", trace_context=own).caused_by(cause).trace_context == own

    async def test_without_a_current_span_events_carry_no_context(self):
        from sagaz.choreography._observe import with_trace_context

        event = Event("x")
        assert with_trace_context(event) is event


TRACEPARENT = {"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"}


def test_the_trace_context_crosses_redis_streams():
    from sagaz.choreography.buses.redis_streams import _event_to_fields, _fields_to_event

    fields = {
        k.encode(): v.encode()
        for k, v in _event_to_fields(Event("x", trace_context=TRACEPARENT)).items()
    }
    assert _fields_to_event(fields).trace_context == TRACEPARENT
    del fields[b"trace_context"]  # a message published before 2.6.0
    assert _fields_to_event(fields).trace_context == {}


def test_the_schema_envelope_has_an_optional_trace_context():
    import json

    from sagaz.integrations.schema_registry import envelope_schema

    payload = {"type": "record", "name": "p", "fields": []}
    avro = json.loads(envelope_schema("x", payload, envelope="choreography"))
    field = next(f for f in avro["fields"] if f["name"] == "trace_context")
    assert field["default"] is None  # readers of older messages stay compatible
    as_json = json.loads(envelope_schema("x", {}, format="json", envelope="choreography"))
    assert "trace_context" not in as_json["required"]
