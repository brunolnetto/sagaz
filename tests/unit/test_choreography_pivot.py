"""Pivots in a choreography: what led to a completed pivot is not undone (#571)."""

from __future__ import annotations

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
from sagaz.choreography._pivot import commit
from sagaz.choreography.state import ParticipantState
from sagaz.choreography.state.sqlite import SQLiteParticipantState
from sagaz.core.listeners import SagaListener
from sagaz.core.storage.saga_log import InMemorySagaLogStore

COMPLETIONS = ["order.shipped"]


class Shop:
    """inventory reserves, payments charges (the pivot), labels prints, shipping ships."""

    def __init__(self, *, fails: str | None = None, pivot: bool = True) -> None:
        self.fails = fails
        self.undone: list[str] = []
        self.orders = ChoreographedSaga(name="orders")
        self.participants = [
            self.orders,
            ChoreographedSaga(name="inventory").on(
                "order.created", self.step("reserve", "stock.reserved"), self.undo("reserve")
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
        # reserve led to the pivot, charge is the pivot: kept. label came after: undone.
        assert shop.undone == ["label"]
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
        assert shop.undone == ["reserve"]
        assert run.status.pivots == []

    async def test_without_a_pivot_everything_is_undone(self, backend):
        shop = Shop(fails="ship", pivot=False)
        assert await Run(shop, **backend).go() == "rolled_back"
        assert sorted(shop.undone) == ["charge", "label", "reserve"]

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

        shop.participants[2] = quiet.on("stock.reserved", charge, pivot=True)

        async def give_up(run: Run) -> None:  # e.g. an expired deadline
            await run.bus.publish(Event(COMPENSATE, {"reason": "too late"}, saga_id="t-1"))

        run = Run(shop)
        assert await run.go(then=give_up) == "partially_committed"
        assert shop.undone == []
        assert [e.source for e in run.seen if e.event_type == PIVOTED] == ["payments"]


class TestThePieces:
    async def test_the_decorator_marks_a_pivot(self):
        class Payments(ChoreographedSaga):
            @on_event("stock.reserved", pivot=True)
            async def charge(self, event: Event) -> None: ...

            @on_event("order.created")
            async def note(self, event: Event) -> None: ...

        assert Payments()._pivots == {"stock.reserved"}

    async def test_a_pivot_announced_again_does_not_commit_what_came_after(self):
        """A retried pivot handler announces twice: only the first one commits."""
        saga = ChoreographedSaga(name="labels").on("a", lambda e, me: None, lambda e, me: None)
        before = Event("a", saga_id="t-1")
        after = Event("a", saga_id="t-1")
        await saga._state.record_action("labels", before)
        await commit(saga, Event(PIVOTED, {"pivot_event_id": "p-1"}, saga_id="t-1"))
        await saga._state.record_action("labels", after)
        await commit(saga, Event(PIVOTED, {"pivot_event_id": "p-1"}, saga_id="t-1"))
        undone, failed = await saga.compensate_transaction("t-1")
        assert (undone, failed) == (["a"], [])  # only *after*

    async def test_a_notice_without_a_transaction_is_ignored(self):
        saga = ChoreographedSaga(name="labels")
        await commit(saga, Event(PIVOTED, {"pivot_event_id": "p-1"}))
        assert await saga._state.actions("labels", "t-1") == []

    async def test_a_state_of_your_own_must_implement_actions_for_pivots(self):
        class Mine:
            actions = ParticipantState.actions

        with pytest.raises(NotImplementedError, match="pivots need"):
            await Mine().actions("p", "t-1")

    def test_the_diagram_draws_the_pivot(self):
        run = Run(Shop())
        chart = run.engine.to_mermaid()
        assert '==>|"pivot"|' in chart
