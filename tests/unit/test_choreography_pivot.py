"""Pivots in a choreography: what led to a completed pivot is not undone (#571)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from sagaz.choreography import (
    COMPENSATE,
    COMPENSATED,
    PIVOTED,
    ChoreographedSaga,
    ChoreographyEngine,
    ChoreographyTracker,
    Event,
    EventBus,
    on_event,
)
from sagaz.choreography._pivot import commit, split
from sagaz.choreography.state.sqlite import SQLiteParticipantState
from sagaz.core.listeners import SagaListener
from sagaz.core.storage.saga_log import InMemorySagaLogStore

COMPLETIONS = ["order.shipped"]


class Shop:
    """inventory reserves; gifts wraps beside the pivot; payments charges (the pivot);
    labels prints and shipping ships after it."""

    def __init__(self, *, fails: str | None = None, pivot: bool = True) -> None:
        self.fails = fails
        self.undone: list[str] = []
        self.orders = ChoreographedSaga(name="orders")
        self.participants = [
            self.orders,
            ChoreographedSaga(name="inventory").on(
                "order.created", self.step("reserve", "stock.reserved"), self.undo("reserve")
            ),
            # Beside the pivot, not before it; registered first, so it is done by then.
            ChoreographedSaga(name="gifts").on(
                "stock.reserved", self.step("wrap", None), self.undo("wrap")
            ),
            ChoreographedSaga(name="payments").on(
                "stock.reserved",
                self.step("charge", "payment.captured"),
                self.undo("charge"),
                pivot=pivot,
            ),
            # Registered before shipping: on the in-process bus it runs first.
            ChoreographedSaga(name="labels").on(
                "payment.captured", self.step("label", None), self.undo("label")
            ),
            ChoreographedSaga(name="shipping").on(
                "payment.captured", self.step("ship", "order.shipped"), self.undo("ship")
            ),
        ]

    def step(self, name: str, emits: str | None) -> Any:
        async def handler(event: Event, me: ChoreographedSaga) -> None:
            if self.fails == name:
                msg = f"{name} failed"
                raise RuntimeError(msg)
            if emits:
                await me.emit(emits)

        return handler

    def undo(self, name: str) -> Any:
        async def compensation(event: Event, me: ChoreographedSaga) -> None:
            self.undone.append(name)

        return compensation


class Run:
    def __init__(self, shop: Shop, *, state: Any = None, saga_log: Any = None, listeners=()):
        self.shop = shop
        self.bus = EventBus()
        self.seen: list[Event] = []
        self.engine = ChoreographyEngine(
            self.bus,
            completion_events=COMPLETIONS,
            retry_backoff_base=0,
            default_max_retries=0,
            state=state,
            saga_log=saga_log,
            relay_interval=3600,
        )
        self.tracker = ChoreographyTracker(
            self.bus, completion_events=COMPLETIONS, saga_log=saga_log, listeners=listeners
        )
        for participant in shop.participants:
            self.engine.register(participant)

    async def _see(self, event: Event) -> None:
        self.seen.append(event)

    async def go(self, then: Any = None) -> str:
        self.bus.subscribe("*", self._see)
        await self.engine.start()
        await self.tracker.start()
        try:
            await self.shop.orders.begin("order.created", correlation_id="t-1")
            await self._settle()
            if then is not None:
                await then(self)
                await self._settle()
            status = await self.tracker.status("t-1")
        finally:
            await self.tracker.stop()
            await self.engine.stop()
        assert status is not None
        self.status = status
        return status.status

    async def _settle(self) -> None:
        for _ in range(12):  # the unified log publishes through its relay
            if self.engine.relay is not None:
                await self.engine.relay.relay()

    def reports(self) -> dict[str, dict[str, Any]]:
        """Each participant's ``choreography.compensated`` report."""
        return {e.data["participant"]: e.data for e in self.seen if e.event_type == COMPENSATED}


@pytest.fixture(params=["memory", "sqlite", "unified"])
async def backend(request, tmp_path):
    if request.param == "memory":
        yield {}
    elif request.param == "sqlite":
        state = SQLiteParticipantState(str(tmp_path / "state.db"))
        yield {"state": state}
        await state.close()
    else:
        yield {"saga_log": InMemorySagaLogStore()}


class TestAFailureAfterThePivot:
    async def test_what_led_to_the_pivot_is_kept_and_what_followed_is_undone(self, backend):
        shop = Shop(fails="ship")
        run = Run(shop, **backend)
        assert await run.go() == "partially_committed"
        # reserve led to the pivot, charge is the pivot: kept. label came after it and
        # wrap ran beside it (done before the pivot was): both undone.
        assert sorted(shop.undone) == ["label", "wrap"]
        assert run.reports()["gifts"] == {
            "participant": "gifts",
            "undone": ["stock.reserved"],
            "failed": [],
            "kept": [],
        }
        reports = run.reports()
        assert reports["inventory"]["kept"] == ["order.created"]
        assert reports["payments"]["kept"] == ["stock.reserved"]
        assert reports["labels"]["undone"] == ["payment.captured"]
        assert reports["labels"]["kept"] == []

    async def test_the_tracker_names_the_pivot(self, backend):
        run = Run(Shop(fails="ship"), **backend)
        await run.go()
        (pivot,) = run.status.pivots
        assert pivot["participant"] == "payments"
        assert pivot["pivot_event_type"] == "stock.reserved"

    async def test_the_listeners_are_told_it_failed_partially_committed(self):
        calls: list[tuple[str, str]] = []

        class Recorder(SagaListener):
            async def on_saga_failed(self, saga_name, saga_id, ctx, error):
                calls.append((saga_id, ctx["status"]))

        await Run(Shop(fails="ship"), listeners=[Recorder()]).go()
        assert calls == [("t-1", "partially_committed")]

    async def test_on_the_unified_log_the_transaction_ends_partially_committed(self):
        log = InMemorySagaLogStore()
        await Run(Shop(fails="ship"), saga_log=log).go()
        transaction = await log.get_transaction("t-1")
        assert transaction.status == "partially_committed"
        assert transaction.ended_at is not None


class TestWithoutACompletedPivot:
    async def test_a_failure_before_the_pivot_rolls_everything_back(self, backend):
        shop = Shop(fails="charge")
        run = Run(shop, **backend)
        assert await run.go() == "rolled_back"
        assert sorted(shop.undone) == ["reserve", "wrap"]
        assert run.status.pivots == []

    async def test_without_a_pivot_everything_is_undone(self, backend):
        shop = Shop(fails="ship", pivot=False)
        assert await Run(shop, **backend).go() == "rolled_back"
        assert sorted(shop.undone) == ["charge", "label", "reserve", "wrap"]

    async def test_a_transaction_that_completes_is_completed(self, backend):
        shop = Shop()
        assert await Run(shop, **backend).go() == "completed"
        assert shop.undone == []


class TestCompensationAskedFromOutside:
    async def test_a_pivot_that_emits_nothing_is_announced_when_it_returns(self):
        shop = Shop()
        quiet = ChoreographedSaga(name="payments")

        async def charge(event: Event, me: ChoreographedSaga) -> None:
            return None

        shop.participants[3] = quiet.on("stock.reserved", charge, pivot=True)

        async def give_up(run: Run) -> None:  # e.g. an expired deadline
            await run.bus.publish(Event(COMPENSATE, {"reason": "too late"}, saga_id="t-1"))

        run = Run(shop)
        assert await run.go(then=give_up) == "partially_committed"
        assert shop.undone == ["wrap"]
        assert [e.source for e in run.seen if e.event_type == PIVOTED] == ["payments"]


class TestThePieces:
    async def test_the_decorator_marks_a_pivot(self):
        class Payments(ChoreographedSaga):
            @on_event("stock.reserved", pivot=True)
            async def charge(self, event: Event) -> None: ...

            @on_event("order.created")
            async def note(self, event: Event) -> None: ...

        assert Payments()._pivots == {"stock.reserved"}

    async def test_only_what_the_pivot_descends_from_is_kept(self):
        """Whenever the notice arrives: an action is kept by its place in the lineage."""
        saga = ChoreographedSaga(name="x").on("a", lambda e, me: None, lambda e, me: None)
        root = Event("a", saga_id="t-1", source="orders")
        mine = Event("a", source="orders").caused_by(root)  # x handles it, and emits:
        trigger = Event("pay", source="x").caused_by(mine)
        beside = Event("a", source="orders").caused_by(root)  # x handles it; leads nowhere
        shared = Event("a", source="other").caused_by(root)  # someone else continued it
        notice = Event(PIVOTED, source="payments").caused_by(
            Event("x", source="other").caused_by(shared).caused_by(trigger)
        )
        late = Event("a", source="payments").caused_by(notice)
        await saga._state.record_action("x", mine)
        await commit(saga, notice)
        for event in (beside, shared, late):  # recorded after the notice
            await saga._state.record_action("x", event)
        undone, kept = split(saga, await saga._state.finish("x", "t-1", compensated=True))
        assert [e.event_id for e in undone] == [beside.event_id, shared.event_id, late.event_id]
        assert kept == ["a"]

    async def test_a_notice_without_a_transaction_is_ignored(self):
        saga = ChoreographedSaga(name="labels")
        await commit(saga, Event(PIVOTED))
        assert await saga._state.finish("labels", "t-1", compensated=True) == []

    def test_the_diagram_draws_the_pivot(self):
        run = Run(Shop())
        chart = run.engine.to_mermaid()
        assert '==>|"pivot"|' in chart


class TestLineage:
    """Every event names the events it descends from, on every bus."""

    def test_caused_by_extends_the_lineage(self):
        first = Event("a", saga_id="t-1")
        second = Event("b", source="inventory").caused_by(first)
        third = Event("c", source="payments").caused_by(second)
        assert first.lineage == ()
        assert second.lineage == ((first.event_id, "inventory"),)
        assert third.lineage == ((first.event_id, "inventory"), (second.event_id, "payments"))
        assert third.lineage[-1] == (third.causation_id, third.source)

    def test_it_survives_the_json_envelope(self):
        event = Event("c", source="p").caused_by(Event("b").caused_by(Event("a", saga_id="t-1")))
        assert Event.from_dict(json.loads(json.dumps(event.to_dict()))) == event

    def test_an_envelope_written_before_it_existed_has_none(self):
        body = Event("a", saga_id="t-1").to_dict()
        del body["lineage"]
        assert Event.from_dict(body).lineage == ()

    def test_it_survives_the_redis_stream_fields(self):
        from sagaz.choreography.buses.redis_streams import _event_to_fields, _fields_to_event

        event = Event("b", source="inventory").caused_by(Event("a", saga_id="t-1"))
        fields = {k.encode(): v.encode() for k, v in _event_to_fields(event).items()}
        assert _fields_to_event(fields).lineage == event.lineage
        del fields[b"lineage"]  # a message from an older producer
        assert _fields_to_event(fields).lineage == ()

    def test_the_schema_registry_envelope_has_it(self):
        from sagaz.integrations.schema_registry import _FIELDS

        assert "lineage" in [name for name, *_ in _FIELDS["choreography"]]
