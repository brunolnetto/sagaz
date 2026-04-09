"""
Unit tests for sagaz.choreography — Event, EventBus, ChoreographedSaga,
ChoreographyEngine, and @on_event decorator.
"""

from __future__ import annotations

import pytest

from sagaz.choreography import (
    ChoreographedSaga,
    ChoreographyEngine,
    Event,
    EventBus,
    on_event,
)
from sagaz.choreography.decorators import get_event_type

# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


class TestEvent:
    def test_defaults_are_set(self):
        e = Event("order.created", {"order_id": "ORD-1"})
        assert e.event_type == "order.created"
        assert e.data["order_id"] == "ORD-1"
        assert e.event_id  # non-empty UUID
        assert e.saga_id is None
        assert e.created_at is not None

    def test_frozen_prevents_mutation(self):
        e = Event("order.created")
        with pytest.raises((TypeError, AttributeError)):
            e.event_type = "other"  # type: ignore[misc]

    def test_with_saga_returns_new_event(self):
        e = Event("order.created")
        e2 = e.with_saga("saga-123")
        assert e2.saga_id == "saga-123"
        assert e.saga_id is None  # original unchanged
        assert e2.event_id == e.event_id  # same id, new saga ref

    def test_repr_contains_type(self):
        e = Event("order.created")
        assert "order.created" in repr(e)

    def test_with_saga_does_not_share_data_dict(self):
        """with_saga() must return an independent copy of the data dict."""
        original_data = {"order_id": "ORD-1"}
        e = Event("order.created", original_data)
        e2 = e.with_saga("saga-123")
        # Mutations to one dict must not affect the other
        original_data["order_id"] = "MUTATED"
        assert e2.data["order_id"] == "ORD-1"


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self):
        bus = EventBus()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        bus.subscribe("order.created", handler)
        await bus.publish(Event("order.created", {"order_id": "1"}))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_wildcard_receives_all(self):
        bus = EventBus()
        received: list[Event] = []

        async def wildcard(e: Event) -> None:
            received.append(e)

        bus.subscribe("*", wildcard)
        await bus.publish(Event("order.created"))
        await bus.publish(Event("payment.charged"))
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self):
        bus = EventBus()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        bus.subscribe("order.created", handler)
        bus.unsubscribe("order.created", handler)
        await bus.publish(Event("order.created"))
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_published_history_is_recorded(self):
        bus = EventBus()
        await bus.publish(Event("order.created"))
        await bus.publish(Event("payment.charged"))
        assert len(bus.published) == 2

    @pytest.mark.asyncio
    async def test_clear_history(self):
        bus = EventBus()
        await bus.publish(Event("x"))
        bus.clear_history()
        assert bus.published == []

    @pytest.mark.asyncio
    async def test_handler_count(self):
        bus = EventBus()

        async def h1(e):
            pass

        async def h2(e):
            pass

        bus.subscribe("order.created", h1)
        bus.subscribe("order.created", h2)
        assert bus.handler_count("order.created") == 2

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_stop_other_handlers(self):
        """A failing handler should not prevent others from running."""
        bus = EventBus()
        second_called = []

        async def bad_handler(e: Event) -> None:
            msg = "broken"
            raise RuntimeError(msg)

        async def good_handler(e: Event) -> None:
            second_called.append(True)

        bus.subscribe("order.created", bad_handler)
        bus.subscribe("order.created", good_handler)
        await bus.publish(Event("order.created"))
        assert second_called  # good handler still ran

    @pytest.mark.asyncio
    async def test_no_handlers_publishes_silently(self):
        bus = EventBus()
        # No handlers registered — should not raise
        await bus.publish(Event("unknown.event"))
        assert len(bus.published) == 1

    def test_unsubscribe_nonexistent_handler_is_silent(self):
        """Unsubscribing a handler that was never registered must not raise."""
        bus = EventBus()

        async def never_subscribed(e: Event) -> None:
            pass

        # Must not raise ValueError
        bus.unsubscribe("order.created", never_subscribed)

    @pytest.mark.asyncio
    async def test_start_and_stop_are_noops(self):
        """EventBus.start() and stop() are no-ops — must not raise."""
        bus = EventBus()
        await bus.start()
        await bus.stop()


# ---------------------------------------------------------------------------
# @on_event decorator
# ---------------------------------------------------------------------------


class TestOnEventDecorator:
    def test_marks_method_with_event_type(self):
        @on_event("order.created")
        async def handler(self, event):
            pass

        assert get_event_type(handler) == "order.created"

    def test_marks_wildcard(self):
        @on_event("*")
        async def handler(self, event):
            pass

        assert get_event_type(handler) == "*"

    def test_plain_method_has_no_event_type(self):
        async def handler(self, event):
            pass

        assert get_event_type(handler) is None


# ---------------------------------------------------------------------------
# ChoreographedSaga
# ---------------------------------------------------------------------------


class TestChoreographedSaga:
    def test_discovers_handlers_on_init(self):
        class OrderSaga(ChoreographedSaga):
            @on_event("order.created")
            async def handle_order(self, event: Event) -> None:
                pass

        saga = OrderSaga()
        assert "order.created" in saga._handlers

    def test_handles_returns_true_for_registered_event(self):
        class MySaga(ChoreographedSaga):
            @on_event("payment.charged")
            async def handle(self, event: Event) -> None:
                pass

        saga = MySaga()
        assert saga.handles("payment.charged")
        assert not saga.handles("unknown.event")

    @pytest.mark.asyncio
    async def test_handle_dispatches_to_handler(self):
        results = []

        class MySaga(ChoreographedSaga):
            @on_event("order.created")
            async def handle_order(self, event: Event) -> None:
                results.append(event.data.get("order_id"))

        saga = MySaga()
        await saga.handle(Event("order.created", {"order_id": "ORD-99"}))
        assert results == ["ORD-99"]

    @pytest.mark.asyncio
    async def test_handle_ignores_unregistered_events(self):
        class MySaga(ChoreographedSaga):
            @on_event("order.created")
            async def handle_order(self, event: Event) -> None:
                pass

        saga = MySaga()
        # Should not raise
        await saga.handle(Event("payment.charged", {}))
        assert len(saga.events_handled) == 0

    @pytest.mark.asyncio
    async def test_wildcard_handler_receives_any_event(self):
        received = []

        class MySaga(ChoreographedSaga):
            @on_event("*")
            async def handle_all(self, event: Event) -> None:
                received.append(event.event_type)

        saga = MySaga()
        await saga.handle(Event("order.created"))
        await saga.handle(Event("payment.failed"))
        assert received == ["order.created", "payment.failed"]

    @pytest.mark.asyncio
    async def test_events_handled_tracks_dispatched_events(self):
        class MySaga(ChoreographedSaga):
            @on_event("order.created")
            async def handle_order(self, event: Event) -> None:
                pass

        saga = MySaga()
        await saga.handle(Event("order.created"))
        assert len(saga.events_handled) == 1

    def test_default_saga_id_is_assigned(self):
        saga = ChoreographedSaga()
        assert saga.saga_id
        assert len(saga.saga_id) > 0

    def test_custom_saga_id_preserved(self):
        saga = ChoreographedSaga(saga_id="custom-123")
        assert saga.saga_id == "custom-123"


# ---------------------------------------------------------------------------
# ChoreographyEngine
# ---------------------------------------------------------------------------


class TestChoreographyEngine:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        bus = EventBus()
        engine = ChoreographyEngine(bus)
        assert not engine.is_running
        await engine.start()
        assert engine.is_running
        await engine.stop()
        assert not engine.is_running

    @pytest.mark.asyncio
    async def test_register_wires_handlers(self):
        bus = EventBus()
        engine = ChoreographyEngine(bus)
        results = []

        class MySaga(ChoreographedSaga):
            @on_event("order.created")
            async def handle_order(self, event: Event) -> None:
                results.append(event.data.get("order_id"))

        engine.register(MySaga(saga_id="s1"))
        await engine.start()
        await bus.publish(Event("order.created", {"order_id": "ORD-1"}))
        await engine.stop()
        assert "ORD-1" in results

    @pytest.mark.asyncio
    async def test_multiple_sagas_receive_same_event(self):
        bus = EventBus()
        engine = ChoreographyEngine(bus)
        received = []

        class SagaA(ChoreographedSaga):
            @on_event("payment.charged")
            async def handle(self, event: Event) -> None:
                received.append("A")

        class SagaB(ChoreographedSaga):
            @on_event("payment.charged")
            async def handle(self, event: Event) -> None:
                received.append("B")

        engine.register(SagaA(saga_id="a"))
        engine.register(SagaB(saga_id="b"))
        await engine.start()
        await bus.publish(Event("payment.charged"))
        await engine.stop()
        assert set(received) == {"A", "B"}

    @pytest.mark.asyncio
    async def test_unregister_removes_saga(self):
        bus = EventBus()
        engine = ChoreographyEngine(bus)

        class MySaga(ChoreographedSaga):
            @on_event("order.created")
            async def handle(self, event: Event) -> None:
                pass

        engine.register(MySaga(saga_id="s1"))
        engine.unregister("s1")
        assert engine.get_saga("s1") is None

    @pytest.mark.asyncio
    async def test_registered_sagas_list(self):
        bus = EventBus()
        engine = ChoreographyEngine(bus)
        engine.register(ChoreographedSaga(saga_id="s1"))
        engine.register(ChoreographedSaga(saga_id="s2"))
        assert len(engine.registered_sagas) == 2

    @pytest.mark.asyncio
    async def test_end_to_end_chain(self):
        """
        Chain: order.created → inventory.reserve → payment.initiate → order.confirmed
        """
        bus = EventBus()
        engine = ChoreographyEngine(bus)
        trace: list[str] = []

        class InventorySaga(ChoreographedSaga):
            @on_event("order.created")
            async def reserve(self, event: Event) -> None:
                trace.append("inventory.reserved")
                await bus.publish(Event("inventory.reserved", event.data))

        class PaymentSaga(ChoreographedSaga):
            @on_event("inventory.reserved")
            async def charge(self, event: Event) -> None:
                trace.append("payment.charged")
                await bus.publish(Event("payment.charged", event.data))

        class NotificationSaga(ChoreographedSaga):
            @on_event("payment.charged")
            async def notify(self, event: Event) -> None:
                trace.append("order.confirmed")

        engine.register(InventorySaga(saga_id="inv"))
        engine.register(PaymentSaga(saga_id="pay"))
        engine.register(NotificationSaga(saga_id="notif"))
        await engine.start()
        await bus.publish(Event("order.created", {"order_id": "ORD-42"}))
        await engine.stop()

        assert trace == ["inventory.reserved", "payment.charged", "order.confirmed"]

    @pytest.mark.asyncio
    async def test_deregister_unsubscribes_handlers(self):
        """After unregister, the saga no longer receives events from the bus."""
        bus = EventBus()
        engine = ChoreographyEngine(bus)
        received: list[str] = []

        class MySaga(ChoreographedSaga):
            @on_event("order.created")
            async def handle_order(self, event: Event) -> None:
                received.append(event.data.get("id", ""))

        saga = MySaga(saga_id="s1")
        engine.register(saga)
        await engine.start()

        await bus.publish(Event("order.created", {"id": "before"}))
        assert "before" in received

        engine.unregister("s1")
        received.clear()
        await bus.publish(Event("order.created", {"id": "after"}))
        assert "after" not in received, "Handler still called after unregister"

        await engine.stop()

    @pytest.mark.asyncio
    async def test_re_register_replaces_old_handlers(self):
        """Re-registering a saga with the same ID must not duplicate handler calls."""
        bus = EventBus()
        engine = ChoreographyEngine(bus)
        calls = 0

        class MySaga(ChoreographedSaga):
            @on_event("x.event")
            async def handle(self, event: Event) -> None:
                nonlocal calls
                calls += 1

        # Register the same saga ID twice — second call should replace the first.
        engine.register(MySaga(saga_id="s1"))
        engine.register(MySaga(saga_id="s1"))
        await engine.start()

        await bus.publish(Event("x.event"))
        await engine.stop()

        assert calls == 1, f"Expected 1 call, got {calls} (duplicate handler registered)"
