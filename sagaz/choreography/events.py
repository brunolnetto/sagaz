"""
Event and EventBus for saga choreography.

``Event`` is a lightweight, immutable message.
``AbstractEventBus`` is the shared protocol every transport backend implements.
``EventBus`` is an in-process pub/sub bus that directly awaits handlers.
Distributed transports (Redis Streams, Kafka, RabbitMQ) live in
``sagaz.choreography.buses`` and all extend ``AbstractEventBus``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

HandlerT = Callable[["Event"], Awaitable[None]]


@dataclass(frozen=True)
class Event:
    """
    Immutable domain event.

    Parameters
    ----------
    event_type:
        Dot-separated event identifier, e.g. ``"order.created"``.
    data:
        Arbitrary payload dict.
    event_id:
        Auto-generated UUID if not provided.
    saga_id:
        Optional correlation ID linking the event to a saga run.
    created_at:
        Timestamp; defaults to ``datetime.now(UTC)``.
    """

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    saga_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def with_saga(self, saga_id: str) -> Event:
        """Return a new Event with the given saga_id."""
        return Event(
            event_type=self.event_type,
            data=self.data,
            event_id=self.event_id,
            saga_id=saga_id,
            created_at=self.created_at,
        )

    def __repr__(self) -> str:
        return f"Event({self.event_type!r}, saga={self.saga_id!r}, id={self.event_id[:8]})"


class AbstractEventBus(ABC):
    """
    Shared contract for all EventBus transport backends.

    Implementations
    ---------------
    - ``EventBus``              — in-process asyncio (zero dependencies)
    - ``RedisStreamsEventBus``  — Redis Streams (requires ``sagaz[redis]``)
    - ``KafkaEventBus``        — Apache Kafka   (requires ``sagaz[kafka]``)
    - ``RabbitMQEventBus``     — RabbitMQ/AMQP  (requires ``sagaz[rabbitmq]``)

    Lifecycle
    ---------
    Call ``await bus.start()`` before publishing or subscribing with
    distributed backends.  In-process ``EventBus`` treats ``start``/``stop``
    as no-ops.
    """

    # ------------------------------------------------------------------
    # Subscription (abstract — every backend must implement)
    # ------------------------------------------------------------------

    @abstractmethod
    def subscribe(self, event_type: str, handler: HandlerT) -> None:
        """Register *handler* for *event_type* (``"*"`` = all events)."""

    @abstractmethod
    def unsubscribe(self, event_type: str, handler: HandlerT) -> None:
        """Remove *handler* from *event_type* subscribers."""

    # ------------------------------------------------------------------
    # Publishing (abstract)
    # ------------------------------------------------------------------

    @abstractmethod
    async def publish(self, event: Event) -> None:
        """Publish *event* to all registered handlers."""

    # ------------------------------------------------------------------
    # Lifecycle (optional — default implementations are no-ops)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect and start background reader, if applicable.

        No-op for in-process buses.  Distributed backends must override.
        """

    async def stop(self) -> None:
        """Disconnect and stop background reader, if applicable.

        No-op for in-process buses.  Distributed backends must override.
        """

    # ------------------------------------------------------------------
    # Testing helpers (default implementations return safe empty values)
    # ------------------------------------------------------------------

    @property
    def published(self) -> list[Event]:
        """Events published via this bus instance (empty if not tracked)."""
        return []

    def clear_history(self) -> None:
        """Discard recorded publish history (no-op if not tracked)."""

    def handler_count(self, event_type: str) -> int:
        """Number of handlers registered for *event_type*."""
        return 0


class EventBus(AbstractEventBus):
    """
    In-process publish/subscribe event bus.

    Handlers registered for an event type are awaited when an event of
    that type is published.  Wildcard ``"*"`` handlers receive all events.

    This bus is **not** thread-safe by design; use it within a single
    asyncio event loop.  For multi-process / distributed use, front it with a
    Kafka or RabbitMQ adapter.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[HandlerT]] = defaultdict(list)
        self._published: list[Event] = []

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, handler: HandlerT) -> None:
        """
        Register *handler* for *event_type*.

        Parameters
        ----------
        event_type:
            Exact event type string or ``"*"`` for all events.
        handler:
            Async callable ``(Event) -> None``.
        """
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
        Publish *event* to all registered handlers (specific + wildcard).

        All handlers are awaited sequentially.  Errors in individual handlers
        are logged but do not prevent other handlers from running.
        """
        self._published.append(event)
        handlers = list(self._handlers.get(event.event_type, []))
        handlers += list(self._handlers.get("*", []))

        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception("Handler %s raised on event %r", handler, event.event_type)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def published(self) -> list[Event]:
        """All events published since construction (for testing / debugging)."""
        return list(self._published)

    def clear_history(self) -> None:
        """Discard the recorded publish history."""
        self._published.clear()

    def handler_count(self, event_type: str) -> int:
        """Return the number of handlers registered for *event_type*."""
        return len(self._handlers.get(event_type, []))
