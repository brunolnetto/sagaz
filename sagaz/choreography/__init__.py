"""
sagaz.choreography — Saga Choreography Pattern.

Choreography is an alternative to orchestration where services react to events
independently. Unlike ``Saga`` (which has a central coordinator), a
``ChoreographedSaga`` declares event handlers using the ``@on_event`` decorator
and publishes new events via an ``AbstractEventBus`` implementation.

Public API::

    from sagaz.choreography import (
        AbstractEventBus,
        BusBackend,
        ChoreographedSaga,
        Event,
        EventBus,
        ChoreographyEngine,
        KafkaEventBus,
        KafkaEventBusConfig,
        RabbitMQEventBus,
        RabbitMQEventBusConfig,
        RedisStreamsBusConfig,
        RedisStreamsEventBus,
        create_event_bus,
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

Selecting a broker at runtime::

    from sagaz.choreography import create_event_bus, BusBackend

    bus = create_event_bus(BusBackend.REDIS)          # Redis Streams
    bus = create_event_bus(BusBackend.KAFKA)          # Apache Kafka
    bus = create_event_bus(BusBackend.RABBITMQ)       # RabbitMQ / AMQP
    bus = create_event_bus(BusBackend.MEMORY)         # in-process (default)
"""

from sagaz.choreography.buses import (
    BusBackend,
    KafkaEventBus,
    KafkaEventBusConfig,
    RabbitMQEventBus,
    RabbitMQEventBusConfig,
    RedisStreamsBusConfig,
    RedisStreamsEventBus,
    create_event_bus,
)
from sagaz.choreography.decorators import on_event
from sagaz.choreography.engine import ChoreographyEngine
from sagaz.choreography.events import AbstractEventBus, Event, EventBus
from sagaz.choreography.saga import ChoreographedSaga

__all__ = [
    "AbstractEventBus",
    "BusBackend",
    "ChoreographedSaga",
    "ChoreographyEngine",
    "Event",
    "EventBus",
    "KafkaEventBus",
    "KafkaEventBusConfig",
    "RabbitMQEventBus",
    "RabbitMQEventBusConfig",
    "RedisStreamsBusConfig",
    "RedisStreamsEventBus",
    "create_event_bus",
    "on_event",
]
