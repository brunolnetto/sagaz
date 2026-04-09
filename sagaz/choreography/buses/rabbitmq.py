"""
RabbitMQ EventBus — distributed choreography transport via AMQP.

Uses ``aio-pika`` for async AMQP access with publisher confirms.  Events are
published to a topic exchange using the ``event_type`` as the routing key.
A single queue is bound to the exchange with the ``#`` wildcard so it receives
all event types; in-process handler dispatch is then performed locally.

Architecture
------------
- ``publish()`` serialises the ``Event`` to JSON and calls
  ``exchange.publish()`` with the ``event_type`` as the routing key.
- ``start()`` connects to RabbitMQ, declares the exchange and queue, binds
  the queue, and registers ``_on_message`` as the consumer callback.
- ``stop()`` cancels the consumer, closes the channel, and disconnects.
- ``subscribe()`` / ``unsubscribe()`` register/deregister in-process handlers.

Configuration
-------------
All options are exposed through ``RabbitMQEventBusConfig``.  Environment
variables follow the ``SAGAZ_BUS_RABBITMQ_*`` prefix:

    SAGAZ_BUS_RABBITMQ_URL          amqp://guest:guest@localhost/
    SAGAZ_BUS_RABBITMQ_EXCHANGE     sagaz.choreography
    SAGAZ_BUS_RABBITMQ_QUEUE        sagaz.choreography.queue
    SAGAZ_BUS_RABBITMQ_PREFETCH     100
    SAGAZ_BUS_RABBITMQ_HEARTBEAT    60
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sagaz.choreography.events import AbstractEventBus, Event, HandlerT
from sagaz.core.exceptions import MissingDependencyError

try:
    import aio_pika  # type: ignore[import-untyped]
    from aio_pika import DeliveryMode, ExchangeType, Message  # type: ignore[import-untyped]

    _RABBITMQ_AVAILABLE = True
except ImportError:
    _RABBITMQ_AVAILABLE = False
    aio_pika: Any = None  # type: ignore[assignment, no-redef]
    Message: Any = None  # type: ignore[assignment, no-redef]
    DeliveryMode: Any = None  # type: ignore[assignment, no-redef]
    ExchangeType: Any = None  # type: ignore[assignment, no-redef]

logger = logging.getLogger(__name__)


@dataclass
class RabbitMQEventBusConfig:
    """
    Configuration for ``RabbitMQEventBus``.

    Parameters
    ----------
    url:
        AMQP connection URL.
    exchange_name:
        Name of the topic exchange used as the choreography bus.
    exchange_durable:
        Whether the exchange survives a broker restart.
    queue_name:
        Name of the queue to consume from.
    queue_durable:
        Whether the queue survives a broker restart.
    prefetch_count:
        QoS prefetch count (limits concurrent in-flight messages).
    heartbeat:
        AMQP heartbeat interval in seconds.
    """

    url: str = "amqp://guest:guest@localhost/"
    exchange_name: str = "sagaz.choreography"
    exchange_durable: bool = True
    queue_name: str = "sagaz.choreography.queue"
    queue_durable: bool = True
    prefetch_count: int = 100
    heartbeat: int = 60

    @classmethod
    def from_env(cls) -> RabbitMQEventBusConfig:
        """Build config from environment variables."""
        return cls(
            url=os.environ.get(
                "SAGAZ_BUS_RABBITMQ_URL", "amqp://guest:guest@localhost/"
            ),
            exchange_name=os.environ.get(
                "SAGAZ_BUS_RABBITMQ_EXCHANGE", "sagaz.choreography"
            ),
            queue_name=os.environ.get(
                "SAGAZ_BUS_RABBITMQ_QUEUE", "sagaz.choreography.queue"
            ),
            prefetch_count=int(
                os.environ.get("SAGAZ_BUS_RABBITMQ_PREFETCH", "100")
            ),
            heartbeat=int(os.environ.get("SAGAZ_BUS_RABBITMQ_HEARTBEAT", "60")),
        )


class RabbitMQEventBus(AbstractEventBus):
    """
    Distributed ``EventBus`` backed by RabbitMQ (AMQP).

    Uses a **topic exchange** where the routing key is the ``event_type``
    string.  A single queue bound with the ``#`` wildcard receives all events;
    routing to specific in-process handlers happens after deserialization.

    Use ``start()`` before publishing or subscribing, and ``stop()`` on
    shutdown.

    Parameters
    ----------
    config:
        ``RabbitMQEventBusConfig`` instance.  Defaults to ``from_env()``.

    Raises
    ------
    MissingDependencyError
        If the ``aio-pika`` package is not installed.
    """

    def __init__(self, config: RabbitMQEventBusConfig | None = None) -> None:
        if not _RABBITMQ_AVAILABLE:
            pkg = "aio-pika"
            raise MissingDependencyError(pkg, feature="RabbitMQEventBus")
        self._config = config or RabbitMQEventBusConfig.from_env()
        self._handlers: dict[str, list[HandlerT]] = defaultdict(list)
        self._connection: Any = None
        self._channel: Any = None
        self._exchange: Any = None
        self._queue: Any = None
        self._consumer_tag: str | None = None
        self._published: list[Event] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to RabbitMQ, declare exchange/queue, and start consuming."""
        if self._connection is not None:
            return

        self._connection = await aio_pika.connect_robust(
            self._config.url,
            heartbeat=self._config.heartbeat,
        )
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=self._config.prefetch_count)

        self._exchange = await self._channel.declare_exchange(
            self._config.exchange_name,
            ExchangeType.TOPIC,
            durable=self._config.exchange_durable,
        )
        self._queue = await self._channel.declare_queue(
            self._config.queue_name,
            durable=self._config.queue_durable,
        )
        # Bind to all routing keys — in-process handler routing done locally.
        await self._queue.bind(self._exchange, routing_key="#")
        self._consumer_tag = await self._queue.consume(self._on_message)

        logger.info(
            "RabbitMQEventBus started (exchange=%s, queue=%s)",
            self._config.exchange_name,
            self._config.queue_name,
        )

    async def stop(self) -> None:
        """Cancel the consumer, close channel, and disconnect."""
        if self._queue is not None and self._consumer_tag is not None:
            await self._queue.cancel(self._consumer_tag)
            self._consumer_tag = None
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        self._exchange = self._queue = None
        logger.info("RabbitMQEventBus stopped")

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, handler: HandlerT) -> None:
        """Register *handler* for *event_type* (or ``"*"`` for all events)."""
        self._handlers[event_type].append(handler)
        logger.debug("Subscribed %s to %r", handler, event_type)

    def unsubscribe(self, event_type: str, handler: HandlerT) -> None:
        """Remove *handler* from *event_type* subscribers."""
        try:
            self._handlers[event_type].remove(handler)
        except ValueError:
            pass  # handler was not registered — silent no-op

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(self, event: Event) -> None:
        """
        Publish *event* to the RabbitMQ exchange.

        The event is JSON-serialised to a persistent AMQP message and
        published with the ``event_type`` as the routing key.
        """
        if self._exchange is None:
            msg = "Call start() before publish()"
            raise RuntimeError(msg)
        payload = json.dumps(
            {
                "event_type": event.event_type,
                "data": event.data,
                "event_id": event.event_id,
                "saga_id": event.saga_id,
                "created_at": event.created_at.isoformat(),
            }
        ).encode()
        message = Message(
            payload,
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        await self._exchange.publish(message, routing_key=event.event_type)
        self._published.append(event)
        logger.debug(
            "Published %r to exchange %s (key=%s)",
            event,
            self._config.exchange_name,
            event.event_type,
        )

    # ------------------------------------------------------------------
    # Consumer callback (internal)
    # ------------------------------------------------------------------

    async def _on_message(self, message: Any) -> None:
        """Deserialise an incoming AMQP message and dispatch to handlers."""
        async with message.process():
            try:
                payload = json.loads(message.body.decode())
                raw_dt = datetime.fromisoformat(payload["created_at"])
                created_at = (
                    raw_dt.astimezone(UTC) if raw_dt.tzinfo else raw_dt.replace(tzinfo=UTC)
                )
                event = Event(
                    event_type=payload["event_type"],
                    data=payload["data"],
                    event_id=payload["event_id"],
                    saga_id=payload.get("saga_id"),
                    created_at=created_at,
                )
            except Exception:
                logger.exception("Failed to deserialise RabbitMQ message")
                return

            handlers = list(self._handlers.get(event.event_type, []))
            handlers += list(self._handlers.get("*", []))
            for handler in handlers:
                try:
                    await handler(event)
                except Exception:
                    logger.exception(
                        "Handler %s raised on event %r", handler, event.event_type
                    )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def published(self) -> list[Event]:
        """Events published via this bus instance (for testing/debugging)."""
        return list(self._published)

    def clear_history(self) -> None:
        """Discard the recorded publish history."""
        self._published.clear()

    def handler_count(self, event_type: str) -> int:
        """Return the number of handlers registered for *event_type*."""
        return len(self._handlers.get(event_type, []))
