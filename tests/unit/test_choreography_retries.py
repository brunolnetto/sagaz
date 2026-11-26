"""Retries and timeouts of choreography handlers, like orchestrated steps (#561)."""

from __future__ import annotations

import asyncio

from sagaz.choreography import (
    ChoreographedSaga,
    ChoreographyEngine,
    ChoreographyTracker,
    Event,
    EventBus,
    compensate,
    on_event,
)


class Flaky(ChoreographedSaga):
    """Fails its first *failures* attempts, then succeeds."""

    def __init__(self, failures: int) -> None:
        super().__init__(name="flaky")
        self.failures = failures
        self.attempts = 0

    @on_event("order.created")
    async def reserve(self, event: Event) -> None:
        self.attempts += 1
        if self.attempts <= self.failures:
            msg = "warehouse busy"
            raise RuntimeError(msg)


class Once(Flaky):
    @on_event("order.created", max_retries=0)
    async def reserve(self, event: Event) -> None:
        await super().reserve.__wrapped__(self, event)


class Slow(ChoreographedSaga):
    def __init__(self) -> None:
        super().__init__(name="slow")
        self.attempts = 0

    @on_event("order.created", max_retries=1, timeout_seconds=0.05)
    async def reserve(self, event: Event) -> None:
        self.attempts += 1
        await asyncio.sleep(1)


async def deliver(participant: ChoreographedSaga, **engine_options) -> str:
    """Begin one transaction; return its status once the handler is done."""
    bus = EventBus()
    engine = ChoreographyEngine(bus, retry_backoff_base=0.001, **engine_options)
    tracker = ChoreographyTracker(bus)
    orders = ChoreographedSaga(name="orders")
    engine.register(orders)
    engine.register(participant)
    await tracker.start()
    await engine.start()
    try:
        start = await orders.begin("order.created", {"order_id": "o-1"})
        return (await tracker.status(start.saga_id or "")).status
    finally:
        await engine.stop()
        await tracker.stop()


async def test_a_failing_handler_is_retried_three_times_by_default():
    participant = Flaky(failures=3)
    assert await deliver(participant) == "executing"  # the fourth attempt succeeded
    assert participant.attempts == 4


async def test_after_the_last_retry_the_transaction_is_compensated():
    participant = Flaky(failures=4)
    assert await deliver(participant) == "rolled_back"
    assert participant.attempts == 4


async def test_the_engine_default_can_be_changed():
    participant = Flaky(failures=1)
    assert await deliver(participant, default_max_retries=0) == "rolled_back"
    assert participant.attempts == 1


async def test_a_handler_can_opt_out_of_retries():
    participant = Once(failures=1)
    assert await deliver(participant) == "rolled_back"
    assert participant.attempts == 1


async def test_each_attempt_has_its_timeout():
    participant = Slow()
    assert await deliver(participant) == "rolled_back"
    assert participant.attempts == 2


async def test_the_imperative_style_takes_the_same_options():
    attempts: list[int] = []

    def reserve(event: Event, me: ChoreographedSaga) -> None:
        attempts.append(1)
        msg = "warehouse busy"
        raise RuntimeError(msg)

    participant = ChoreographedSaga(name="inventory").on("order.created", reserve, max_retries=2)
    assert participant.retry_policy("order.created") == (2, None)
    assert await deliver(participant) == "rolled_back"
    assert len(attempts) == 3


def test_handle_runs_the_handler_once_outside_an_engine():
    participant = Flaky(failures=0)
    asyncio.run(participant.handle(Event("order.created", {})))
    assert participant.attempts == 1


class FlakyUndo(ChoreographedSaga):
    """Reserves, then needs *failures* failed attempts before its release succeeds."""

    def __init__(self, failures: int) -> None:
        super().__init__(name="inventory")
        self.failures = failures
        self.release_attempts = 0
        self.released = False

    @on_event("order.created", max_retries=0)
    async def reserve(self, event: Event) -> None:
        await self.emit("inventory.reserved", event.data)

    @compensate("order.created")
    async def release(self, event: Event) -> None:
        self.release_attempts += 1
        if self.release_attempts <= self.failures:
            msg = "warehouse offline"
            raise RuntimeError(msg)
        self.released = True


class Declines(ChoreographedSaga):
    @on_event("inventory.reserved", max_retries=0)
    async def charge(self, event: Event) -> None:
        msg = "card declined"
        raise ValueError(msg)


async def compensate_with(inventory: FlakyUndo) -> str:
    bus = EventBus()
    engine = ChoreographyEngine(bus, retry_backoff_base=0.001)
    tracker = ChoreographyTracker(bus)
    orders = ChoreographedSaga(name="orders")
    for participant in (orders, inventory, Declines(name="payments")):
        engine.register(participant)
    await tracker.start()
    await engine.start()
    try:
        start = await orders.begin("order.created", {"order_id": "o-1"})
        return (await tracker.status(start.saga_id or "")).status
    finally:
        await engine.stop()
        await tracker.stop()


async def test_a_flaky_compensation_is_retried():
    inventory = FlakyUndo(failures=2)
    assert await compensate_with(inventory) == "rolled_back"
    assert (inventory.release_attempts, inventory.released) == (3, True)


async def test_a_compensation_that_keeps_failing_is_reported():
    inventory = FlakyUndo(failures=10)
    assert await compensate_with(inventory) == "failed"
    assert inventory.release_attempts == 4
