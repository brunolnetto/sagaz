"""Event schema, bounded fan-out hub and SSE stream plumbing for the visualization server."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import ServerSentEvent

EventType = Literal[
    "saga.started",
    "saga.completed",
    "saga.failed",
    "step.started",
    "step.succeeded",
    "step.failed",
    "step.compensation_started",
    "step.compensated",
]


class VisualizationEvent(BaseModel):
    """Allowlisted event schema. Arbitrary Saga context is deliberately rejected."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: EventType
    saga_id: str = Field(min_length=1, max_length=256)
    saga_name: str = Field(min_length=1, max_length=256)
    step_name: str | None = Field(default=None, min_length=1, max_length=256)
    error_type: str | None = Field(default=None, max_length=256)
    occurred_at: datetime


@dataclass(eq=False, slots=True)
class _Subscription:
    queue: asyncio.Queue[dict[str, Any]]
    dropped: int = 0


class EventHub:
    """Bounded, process-local fan-out hub owned by one FastAPI application."""

    def __init__(
        self,
        queue_size: int = 100,
        max_subscribers: int = 100,
    ) -> None:
        if queue_size < 1:
            message = "queue_size must be positive"
            raise ValueError(message)
        if max_subscribers < 1:
            message = "max_subscribers must be positive"
            raise ValueError(message)

        self.queue_size = queue_size
        self.max_subscribers = max_subscribers
        self._subscribers: set[_Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> _Subscription | None:
        if len(self._subscribers) >= self.max_subscribers:
            return None

        subscription = _Subscription(asyncio.Queue(maxsize=self.queue_size))
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: _Subscription) -> None:
        self._subscribers.discard(subscription)

    def publish(self, event: dict[str, Any]) -> int:
        """Fan out an event, dropping oldest queued messages on overflow."""
        delivered = 0

        for subscription in tuple(self._subscribers):
            queue = subscription.queue

            if queue.full():
                try:
                    queue.get_nowait()
                    subscription.dropped += 1
                except asyncio.QueueEmpty:
                    pass

            try:
                queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                # Defensive: queue operations are synchronous on this event loop.
                subscription.dropped += 1

        return delivered


def _sse_stream(
    hub: EventHub,
    subscription: _Subscription,
    *,
    accept: Callable[[dict[str, Any]], bool] | None = None,
    initial: list[ServerSentEvent] | None = None,
) -> AsyncIterator[ServerSentEvent]:
    async def stream() -> AsyncIterator[ServerSentEvent]:
        try:
            for message in initial or ():
                yield message
            while True:
                event = await subscription.queue.get()

                if subscription.dropped:
                    dropped = subscription.dropped
                    subscription.dropped = 0
                    yield ServerSentEvent(
                        event="gap",
                        data=json.dumps({"dropped": dropped}),
                    )

                if accept is not None and not accept(event):
                    continue

                yield ServerSentEvent(
                    id=event["event_id"],
                    data=json.dumps(event, separators=(",", ":")),
                )
        finally:
            hub.unsubscribe(subscription)

    return stream()
