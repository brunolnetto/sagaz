"""
sagaz.choreography — Saga Choreography Pattern.

Choreography is an alternative to orchestration where services react to events
independently. Unlike ``Saga`` (which has a central coordinator), a
``ChoreographedSaga`` declares event handlers using the ``@on_event`` decorator
and publishes new events via ``EventBus.publish()``.

Public API::

    from sagaz.choreography import (
        ChoreographedSaga,
        Event,
        EventBus,
        ChoreographyEngine,
        on_event,
    )

Quick start::

    bus = EventBus()
    engine = ChoreographyEngine(bus)

    class OrderSaga(ChoreographedSaga):
        @on_event("order.created")
        async def handle_order_created(self, event: Event) -> None:
            await bus.publish(Event("inventory.reserve", {"order_id": event.data["order_id"]}))

    saga = OrderSaga()
    engine.register(saga)
    await engine.start()
    await bus.publish(Event("order.created", {"order_id": "ORD-1"}))
    await engine.stop()
"""

from sagaz.choreography.decorators import on_event
from sagaz.choreography.engine import ChoreographyEngine
from sagaz.choreography.events import Event, EventBus
from sagaz.choreography.saga import ChoreographedSaga

__all__ = [
    "ChoreographedSaga",
    "ChoreographyEngine",
    "Event",
    "EventBus",
    "on_event",
]
