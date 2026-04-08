"""
Redis Streams EventBus — distributed choreography transport.

Uses Redis Streams (XADD / XREADGROUP) so that choreographed sagas can span
multiple processes or services without requiring Kafka or RabbitMQ.

Architecture
------------
- ``publish()`` serialises the ``Event`` to JSON and issues an ``XADD`` to
  the configured stream.
- ``start()`` launches a background asyncio task that loops on ``XREADGROUP``
  and dispatches received events to locally-registered handlers.
- ``stop()`` cancels the reader task and closes the Redis connection.
- ``subscribe()`` / ``unsubscribe()`` register/deregister in-process handlers
  (same API as ``EventBus``).

Thread-safety
-------------
The bus is designed for single-event-loop use.  Do not share an instance
across threads.

Configuration
-------------
All options are exposed through ``RedisStreamsBusConfig``.  Environment
variables follow the same naming as ``RedisBrokerConfig``.

    SAGAZ_BUS_REDIS_URL               redis://localhost:6379/0
    SAGAZ_BUS_REDIS_STREAM_NAME       sagaz.choreography
    SAGAZ_BUS_REDIS_CONSUMER_GROUP    sagaz
    SAGAZ_BUS_REDIS_CONSUMER_NAME     worker-1
    SAGAZ_BUS_REDIS_BLOCK_TIMEOUT_MS  1000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from sagaz.choreography.events import Event, HandlerT
from sagaz.core.exceptions import MissingDependencyError

try:
    import redis.asyncio as aioredis  # type: ignore[import-untyped]

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    aioredis: Any = None  # type: ignore[assignment, no-redef]

logger = logging.getLogger(__name__)

_FIELD_EVENT_TYPE = b"event_type"
_FIELD_DATA = b"data"
_FIELD_EVENT_ID = b"event_id"
_FIELD_SAGA_ID = b"saga_id"
_FIELD_CREATED_AT = b"created_at"

_LAST_DELIVERED = ">"  # consume only new messages per consumer group


@dataclass
class RedisStreamsBusConfig:
    """
    Configuration for ``RedisStreamsEventBus``.

    Parameters
    ----------
    url:
        Redis connection URL.
    stream_name:
        Name of the Redis stream used as the choreography bus.
    consumer_group:
        Consumer group name.  All instances in the same group share the
        message load; use the *same* group name per service type.
    consumer_name:
        Unique consumer name within the group (e.g. hostname + pid).
    block_timeout_ms:
        How long (ms) ``XREADGROUP`` blocks waiting for new messages.
        Lower values increase poll frequency but also CPU usage.
    max_stream_length:
        Maximum stream length; older entries are trimmed automatically.
    read_count:
        Number of messages to fetch per ``XREADGROUP`` call.
    """

    url: str = "redis://localhost:6379/0"
    stream_name: str = "sagaz.choreography"
    consumer_group: str = "sagaz"
    consumer_name: str = "worker-1"
    block_timeout_ms: int = 1000
    max_stream_length: int = 50_000
    read_count: int = 100

    @classmethod
    def from_env(cls) -> RedisStreamsBusConfig:
        """Build config from environment variables."""
        return cls(
            url=os.environ.get("SAGAZ_BUS_REDIS_URL", "redis://localhost:6379/0"),
            stream_name=os.environ.get(
                "SAGAZ_BUS_REDIS_STREAM_NAME", "sagaz.choreography"
            ),
            consumer_group=os.environ.get("SAGAZ_BUS_REDIS_CONSUMER_GROUP", "sagaz"),
            consumer_name=os.environ.get("SAGAZ_BUS_REDIS_CONSUMER_NAME", "worker-1"),
            block_timeout_ms=int(
                os.environ.get("SAGAZ_BUS_REDIS_BLOCK_TIMEOUT_MS", "1000")
            ),
        )


def _event_to_fields(event: Event) -> dict[str, str]:
    """Serialise an ``Event`` to Redis stream field mapping."""
    return {
        "event_type": event.event_type,
        "data": json.dumps(event.data),
        "event_id": event.event_id,
        "saga_id": event.saga_id or "",
        "created_at": event.created_at.isoformat(),
    }


def _fields_to_event(fields: dict[bytes, bytes]) -> Event:
    """Deserialise Redis stream fields back to an ``Event``."""
    from datetime import datetime, timezone

    saga_id_raw = fields.get(_FIELD_SAGA_ID, b"").decode()
    return Event(
        event_type=fields[_FIELD_EVENT_TYPE].decode(),
        data=json.loads(fields[_FIELD_DATA].decode()),
        event_id=fields[_FIELD_EVENT_ID].decode(),
        saga_id=saga_id_raw or None,
        created_at=datetime.fromisoformat(
            fields[_FIELD_CREATED_AT].decode()
        ).replace(tzinfo=UTC),
    )


class RedisStreamsEventBus:
    """
    Distributed ``EventBus`` backed by Redis Streams.

    Use ``start()`` before publishing or subscribing, and ``stop()`` on
    shutdown.  Suitable as a drop-in replacement for the in-process
    ``EventBus`` when distributed choreography is needed.

    Parameters
    ----------
    config:
        ``RedisStreamsBusConfig`` instance.  Defaults to ``from_env()``.

    Raises
    ------
    MissingDependencyError
        If the ``redis`` package is not installed.
    """

    def __init__(self, config: RedisStreamsBusConfig | None = None) -> None:
        if not _REDIS_AVAILABLE:
            msg = (
                "RedisStreamsEventBus requires the 'redis' package. "
                "Install it with: pip install sagaz[redis]"
            )
            raise MissingDependencyError(msg)
        self._config = config or RedisStreamsBusConfig.from_env()
        self._handlers: dict[str, list[HandlerT]] = defaultdict(list)
        self._client: Any = None
        self._reader_task: asyncio.Task[None] | None = None
        self._published: list[Event] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to Redis, ensure the consumer group exists, start reader."""
        self._client = aioredis.from_url(
            self._config.url, decode_responses=False
        )
        # Create consumer group (idempotent — OK if already exists)
        try:
            await self._client.xgroup_create(
                self._config.stream_name,
                self._config.consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            # BUSYGROUP means the group already exists — not an error
            if "BUSYGROUP" not in str(exc):
                raise
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name="sagaz-chorus-reader"
        )
        logger.info(
            "RedisStreamsEventBus started (stream=%s, group=%s)",
            self._config.stream_name,
            self._config.consumer_group,
        )

    async def stop(self) -> None:
        """Cancel the reader task and close the Redis connection."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("RedisStreamsEventBus stopped")

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
        Publish *event* to the Redis stream.

        The event is serialised to stream fields and written via ``XADD``.
        The reader loop on every consumer will receive it and dispatch
        to locally-registered handlers.
        """
        if self._client is None:
            msg = "Call start() before publish()"
            raise RuntimeError(msg)
        fields = _event_to_fields(event)
        await self._client.xadd(
            self._config.stream_name,
            fields,
            maxlen=self._config.max_stream_length,
            approximate=True,
        )
        self._published.append(event)
        logger.debug("Published %r to stream %s", event, self._config.stream_name)

    # ------------------------------------------------------------------
    # Reader loop (internal)
    # ------------------------------------------------------------------

    async def _reader_loop(self) -> None:
        """Background task: read from Redis Streams and dispatch to handlers."""
        while True:
            try:
                results = await self._client.xreadgroup(
                    self._config.consumer_group,
                    self._config.consumer_name,
                    {self._config.stream_name: _LAST_DELIVERED},
                    count=self._config.read_count,
                    block=self._config.block_timeout_ms,
                )
                if not results:
                    continue
                for _stream, messages in results:
                    for msg_id, fields in messages:
                        await self._dispatch(fields)
                        await self._client.xack(
                            self._config.stream_name,
                            self._config.consumer_group,
                            msg_id,
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("RedisStreamsEventBus reader error")
                await asyncio.sleep(0.5)

    async def _dispatch(self, fields: dict[bytes, bytes]) -> None:
        """Deserialise one stream message and invoke matching handlers."""
        try:
            event = _fields_to_event(fields)
        except Exception:
            logger.exception("Failed to deserialise event fields: %s", fields)
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
