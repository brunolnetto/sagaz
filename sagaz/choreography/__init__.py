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

Quick start (in-process bus)::

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

Distributed bus (Redis Streams — requires ``sagaz[redis]``)::

    from sagaz.choreography import RedisStreamsEventBus, RedisStreamsBusConfig

    config = RedisStreamsBusConfig(url="redis://localhost:6379/0")
    bus = RedisStreamsEventBus(config)
    await bus.start()
    # ... same engine/saga setup ...
    await bus.stop()
"""

from sagaz.choreography.buses import RedisStreamsBusConfig, RedisStreamsEventBus
from sagaz.choreography.decorators import on_event
from sagaz.choreography.engine import ChoreographyEngine
from sagaz.choreography.events import Event, EventBus
from sagaz.choreography.saga import ChoreographedSaga

__all__ = [
    "ChoreographedSaga",
    "ChoreographyEngine",
    "Event",
    "EventBus",
    "RedisStreamsBusConfig",
    "RedisStreamsEventBus",
    "on_event",
]
