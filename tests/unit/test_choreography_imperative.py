"""Imperative choreography: ``participant.on(event_type, handler, compensation=)`` (#560)."""

from __future__ import annotations

import pytest

from sagaz.choreography import (
    ChoreographedSaga,
    ChoreographyEngine,
    ChoreographyTracker,
    Event,
    EventBus,
    on_event,
)
from sagaz.core.exceptions import SagaDefinitionError


def participants(log: list[str], limit: int = 100) -> list[ChoreographedSaga]:
    """The order flow of the declarative tests, written in the imperative style."""

    async def reserve(event: Event, me: ChoreographedSaga) -> None:
        log.append(f"reserve {event.data['order_id']}")
        await me.emit("inventory.reserved", dict(event.data))

    async def release(event: Event, me: ChoreographedSaga) -> None:
        log.append(f"release {event.data['order_id']} by {me.name}")

    def charge(event: Event, me: ChoreographedSaga) -> None:  # a sync handler works too
        if event.data["amount"] > limit:
            msg = "card declined"
            raise ValueError(msg)
        log.append(f"charge {event.data['order_id']}")

    async def ship(event: Event, me: ChoreographedSaga) -> None:
        await me.emit("order.shipped", event.data)

    inventory = ChoreographedSaga(name="inventory").on(
        "order.created", reserve, compensation=release
    )
    payments = ChoreographedSaga(name="payments").on("inventory.reserved", charge)
    shipping = ChoreographedSaga(name="shipping").on("payment.charged", ship)
    return [ChoreographedSaga(name="orders"), inventory, payments, shipping]


async def run(amount: int) -> tuple[list[str], str]:
    log: list[str] = []
    bus = EventBus()
    engine = ChoreographyEngine(bus, completion_events={"order.shipped"})
    tracker = ChoreographyTracker(bus, completion_events={"order.shipped"})
    orders, *others = participants(log)
    for participant in (orders, *others):
        engine.register(participant)
    await tracker.start()
    await engine.start()
    try:
        start = await orders.begin("order.created", {"order_id": "o-1", "amount": amount})
        status = await tracker.status(start.saga_id or "")
    finally:
        await engine.stop()
        await tracker.stop()
    return log, status.status


async def test_a_handler_receives_the_event_and_its_participant():
    log, status = await run(amount=40)
    assert log == ["reserve o-1", "charge o-1"]
    assert status == "executing"  # no shipping handler for payment.charged was triggered


async def test_a_failure_runs_the_compensations_with_their_participant():
    log, status = await run(amount=500)
    assert log == ["reserve o-1", "release o-1 by inventory"]
    assert status == "rolled_back"


def test_on_returns_the_participant_for_chaining():
    participant = ChoreographedSaga(name="p")
    assert participant.on("a", lambda e, p: None).on("b", lambda e, p: None) is participant
    assert participant.handles("a")
    assert participant.handles("b")


def test_two_handlers_for_one_event_type_are_a_definition_error():
    participant = ChoreographedSaga(name="p").on("a", lambda e, p: None)
    with pytest.raises(SagaDefinitionError, match="two handlers for event type 'a'"):
        participant.on("a", lambda e, p: None)


def test_declarative_duplicates_are_a_definition_error_too():
    class Twice(ChoreographedSaga):
        @on_event("a")
        async def first(self, event: Event) -> None: ...

        @on_event("a")
        async def second(self, event: Event) -> None: ...

    with pytest.raises(SagaDefinitionError, match="two handlers for event type 'a'"):
        Twice()


def test_styles_are_not_mixed():
    class Declared(ChoreographedSaga):
        @on_event("a")
        async def handle(self, event: Event) -> None: ...

    with pytest.raises(SagaDefinitionError, match="use one style"):
        Declared().on("b", lambda e, p: None)


def test_handlers_are_added_before_registering():
    participant = ChoreographedSaga(name="p")
    ChoreographyEngine(EventBus()).register(participant)
    with pytest.raises(SagaDefinitionError, match="before registering"):
        participant.on("a", lambda e, p: None)
