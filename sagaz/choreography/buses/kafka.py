"""
Kafka EventBus — distributed choreography transport via Apache Kafka.

Uses aiokafka for async producer/consumer.  Each message is written to a
single configurable topic; the ``event_type`` is used as the Kafka message
key so that events of the same type land on the same partition.

Architecture
------------
- ``publish()`` serialises the ``Event`` to JSON and calls
  ``AIOKafkaProducer.send_and_wait()``.
- ``start()`` creates producer + consumer, starts a background reader task.
- ``stop()`` cancels the reader task, then stops producer and consumer.
- ``subscribe()`` / ``unsubscribe()`` register/deregister in-process handlers.

Consumer groups
---------------
All instances sharing the same ``consumer_group`` load-balance message
consumption (Kafka's standard consumer group semantics).  Use the same group
name across replicas of one service; use different group names for different
service types that each need their own copy of every event (fan-out).

Configuration
-------------
All options are exposed through ``KafkaEventBusConfig``.  Environment
variables follow the ``SAGAZ_BUS_KAFKA_*`` prefix:

    SAGAZ_BUS_KAFKA_BOOTSTRAP_SERVERS   localhost:9092
    SAGAZ_BUS_KAFKA_TOPIC               sagaz.choreography
    SAGAZ_BUS_KAFKA_CONSUMER_GROUP      sagaz
    SAGAZ_BUS_KAFKA_CONSUMER_NAME       worker-1
    SAGAZ_BUS_KAFKA_SECURITY_PROTOCOL   PLAINTEXT
    SAGAZ_BUS_KAFKA_SASL_MECHANISM      (PLAIN, SCRAM-SHA-256, …)
    SAGAZ_BUS_KAFKA_SASL_USERNAME
    SAGAZ_BUS_KAFKA_SASL_PASSWORD
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sagaz.choreography.events import AbstractEventBus, Event, HandlerT
from sagaz.core.exceptions import MissingDependencyError

try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # type: ignore[import-untyped]

    _KAFKA_AVAILABLE = True
except ImportError:
    _KAFKA_AVAILABLE = False
    AIOKafkaProducer: Any = None  # type: ignore[assignment, no-redef]
    AIOKafkaConsumer: Any = None  # type: ignore[assignment, no-redef]

logger = logging.getLogger(__name__)


@dataclass
class KafkaEventBusConfig:
    """
    Configuration for ``KafkaEventBus``.

    Parameters
    ----------
    bootstrap_servers:
        Comma-separated Kafka broker addresses.
    topic:
        Kafka topic used as the choreography bus.
    consumer_group:
        Consumer group ID shared by all instances of the same service.
    consumer_name:
        Unique client identifier within the group (e.g. hostname + pid).
    auto_offset_reset:
        Where to start consuming if no committed offset exists
        (``"latest"`` or ``"earliest"``).
    max_poll_records:
        Maximum records fetched per poll.
    security_protocol:
        ``PLAINTEXT``, ``SSL``, ``SASL_PLAINTEXT``, or ``SASL_SSL``.
    sasl_mechanism:
        SASL mechanism (``PLAIN``, ``SCRAM-SHA-256``, etc.)
        ``None`` disables SASL.
    sasl_username:
        SASL username; used only when ``sasl_mechanism`` is set.
    sasl_password:
        SASL password; used only when ``sasl_mechanism`` is set.
    """

    bootstrap_servers: str = "localhost:9092"
    topic: str = "sagaz.choreography"
    consumer_group: str = "sagaz"
    consumer_name: str = "worker-1"
    auto_offset_reset: str = "latest"
    max_poll_records: int = 100
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None

    @classmethod
    def from_env(cls) -> KafkaEventBusConfig:
        """Build config from environment variables."""
        return cls(
            bootstrap_servers=os.environ.get(
                "SAGAZ_BUS_KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
            ),
            topic=os.environ.get("SAGAZ_BUS_KAFKA_TOPIC", "sagaz.choreography"),
            consumer_group=os.environ.get("SAGAZ_BUS_KAFKA_CONSUMER_GROUP", "sagaz"),
            consumer_name=os.environ.get("SAGAZ_BUS_KAFKA_CONSUMER_NAME", "worker-1"),
            security_protocol=os.environ.get(
                "SAGAZ_BUS_KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"
            ),
            sasl_mechanism=os.environ.get("SAGAZ_BUS_KAFKA_SASL_MECHANISM"),
            sasl_username=os.environ.get("SAGAZ_BUS_KAFKA_SASL_USERNAME"),
            sasl_password=os.environ.get("SAGAZ_BUS_KAFKA_SASL_PASSWORD"),
        )


def _event_to_value(event: Event) -> bytes:
    """Serialise an ``Event`` to a JSON-encoded bytes value."""
    return json.dumps(
        {
            "event_type": event.event_type,
            "data": event.data,
            "event_id": event.event_id,
            "saga_id": event.saga_id,
            "created_at": event.created_at.isoformat(),
        }
    ).encode()


def _value_to_event(value: bytes) -> Event:
    """Deserialise a Kafka message value back to an ``Event``."""
    payload = json.loads(value.decode())
    raw_dt = datetime.fromisoformat(payload["created_at"])
    created_at = raw_dt.astimezone(UTC) if raw_dt.tzinfo else raw_dt.replace(tzinfo=UTC)
    return Event(
        event_type=payload["event_type"],
        data=payload["data"],
        event_id=payload["event_id"],
        saga_id=payload.get("saga_id"),
        created_at=created_at,
    )


class KafkaEventBus(AbstractEventBus):
    """
    Distributed ``EventBus`` backed by Apache Kafka.

    Use ``start()`` before publishing or subscribing, and ``stop()`` on
    shutdown.  Suitable as a drop-in replacement for the in-process
    ``EventBus`` when distributed choreography across multiple processes or
    services is needed.

    Parameters
    ----------
    config:
        ``KafkaEventBusConfig`` instance.  Defaults to ``from_env()``.

    Raises
    ------
    MissingDependencyError
        If the ``aiokafka`` package is not installed.
    """

    def __init__(self, config: KafkaEventBusConfig | None = None) -> None:
        if not _KAFKA_AVAILABLE:
            pkg = "aiokafka"
            raise MissingDependencyError(pkg, feature="KafkaEventBus")
        self._config = config or KafkaEventBusConfig.from_env()
        self._handlers: dict[str, list[HandlerT]] = defaultdict(list)
        self._producer: Any = None
        self._consumer: Any = None
        self._reader_task: asyncio.Task[None] | None = None
        self._published: list[Event] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create producer/consumer, connect, and start the reader loop."""
        if self._reader_task is not None and not self._reader_task.done():
            return

        producer_kwargs: dict[str, Any] = {
            "bootstrap_servers": self._config.bootstrap_servers,
            "client_id": self._config.consumer_name,
            "acks": "all",
            "enable_idempotence": True,
        }
        consumer_kwargs: dict[str, Any] = {
            "bootstrap_servers": self._config.bootstrap_servers,
            "group_id": self._config.consumer_group,
            "client_id": f"{self._config.consumer_name}-consumer",
            "auto_offset_reset": self._config.auto_offset_reset,
            "enable_auto_commit": False,
        }
        if self._config.sasl_mechanism:
            sasl_opts: dict[str, Any] = {
                "security_protocol": self._config.security_protocol,
                "sasl_mechanism": self._config.sasl_mechanism,
                "sasl_plain_username": self._config.sasl_username,
                "sasl_plain_password": self._config.sasl_password,
            }
            producer_kwargs.update(sasl_opts)
            consumer_kwargs.update(sasl_opts)

        self._producer = AIOKafkaProducer(**producer_kwargs)
        self._consumer = AIOKafkaConsumer(self._config.topic, **consumer_kwargs)
        await self._producer.start()
        await self._consumer.start()

        self._reader_task = asyncio.create_task(
            self._reader_loop(), name="sagaz-kafka-reader"
        )
        logger.info(
            "KafkaEventBus started (topic=%s, group=%s)",
            self._config.topic,
            self._config.consumer_group,
        )

    async def stop(self) -> None:
        """Cancel the reader loop and stop the producer/consumer."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
        logger.info("KafkaEventBus stopped")

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
            pass

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(self, event: Event) -> None:
        """
        Publish *event* to the Kafka topic.

        The event is JSON-serialised and sent via ``send_and_wait``; the
        ``event_type`` is used as the Kafka message key for deterministic
        partition routing.
        """
        if self._producer is None:
            msg = "Call start() before publish()"
            raise RuntimeError(msg)
        value = _event_to_value(event)
        await self._producer.send_and_wait(
            self._config.topic,
            value=value,
            key=event.event_type.encode(),
        )
        self._published.append(event)
        logger.debug("Published %r to Kafka topic %s", event, self._config.topic)

    # ------------------------------------------------------------------
    # Reader loop (internal)
    # ------------------------------------------------------------------

    async def _reader_loop(self) -> None:
        """Background task: poll Kafka and dispatch to in-process handlers."""
        while True:
            try:
                records = await self._consumer.getmany(
                    timeout_ms=500,
                    max_records=self._config.max_poll_records,
                )
                for tp, messages in records.items():
                    for msg in messages:
                        await self._dispatch(msg.value)
                        await self._consumer.commit({tp: msg.offset + 1})
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("KafkaEventBus reader error")
                await asyncio.sleep(0.5)

    async def _dispatch(self, value: bytes) -> None:
        """Deserialise one Kafka value and invoke matching handlers."""
        try:
            event = _value_to_event(value)
        except Exception:
            logger.exception("Failed to deserialise Kafka message: %s", value)
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
