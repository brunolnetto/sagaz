"""Deliver the saga log's outbox to a choreography bus (ADR-041 phase 3, #466).

With the unified saga log, participants do not publish on the bus directly:
they write each event to the log and to the outbox in one database
transaction. A :class:`ChoreographyRelay` then claims the outbox messages and
publishes them on the bus in its native format. It is the standard
``OutboxWorker`` (leases, retries, dead letters, metrics) with an
:class:`EventBusBroker`; run it with a CDC source (ADR-011) to relay without
polling.

Delivery is at least once: a relay that crashes after publishing but before
marking a message sent publishes it again, and participants deduplicate by
``event_id``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from sagaz.choreography.events import AbstractEventBus, Event
from sagaz.core.outbox.brokers.base import BaseBroker
from sagaz.core.outbox.types import OutboxConfig, OutboxEvent
from sagaz.core.outbox.worker import OutboxWorker


class EventBusBroker(BaseBroker):
    """A message broker that publishes outbox messages on a choreography bus."""

    def __init__(self, bus: AbstractEventBus) -> None:
        super().__init__()
        self.bus = bus

    async def connect(self) -> None:
        self._connected = True  # the bus's lifecycle belongs to its owner

    async def close(self) -> None:
        self._connected = False

    async def health_check(self) -> bool:
        return True

    async def publish(
        self,
        topic: str,
        message: bytes,
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        body = json.loads(message)
        await self.bus.publish(Event.from_dict(body.get("payload", body)))

    async def publish_event(self, event: OutboxEvent, topic: str | None = None) -> None:
        await self.bus.publish(Event.from_dict(event.payload))


class ChoreographyRelay:
    """Publishes a saga log's outbox on *bus*.

    Args:
        outbox: The ``OutboxStorage`` the log writes to (``log.outbox_storage()``).
        bus: The choreography bus to publish on.
        poll_interval: Seconds between polls while running in the background.
        batch_size: Messages claimed per poll.
        max_retries: Failed publications of a message before it goes to the
            outbox dead letter.
    """

    def __init__(
        self,
        outbox: Any,
        bus: AbstractEventBus,
        *,
        poll_interval: float = 0.1,
        batch_size: int = 100,
        max_retries: int = 100,
    ) -> None:
        self.outbox = outbox
        self.worker = OutboxWorker(
            outbox,
            EventBusBroker(bus),
            OutboxConfig(
                batch_size=batch_size,
                poll_interval_seconds=poll_interval,
                max_retries=max_retries,
            ),
            on_event_published=self._published,
        )
        self._sent = 0
        self.poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None
        self._ready = False

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        # Marked first: if the relay is cancelled while the outbox connects,
        # close() still releases what was opened.
        self._ready = True
        initialize = getattr(self.outbox, "initialize", None)
        if callable(initialize):
            await initialize()

    async def relay(self) -> int:
        """Publish the pending messages now; return how many were published.

        Publishing can trigger handlers that write more messages (on an
        in-process bus), so this repeats while messages get published. A batch
        that publishes nothing (the bus is down) stops it: the failed messages
        are retried on the next call, up to ``max_retries`` times.
        """
        await self._ensure_ready()
        total = 0
        while True:
            self._sent = 0
            await self.worker.process_batch()
            if not self._sent:
                return total
            total += self._sent

    async def _published(self, event: OutboxEvent) -> None:
        self._sent += 1

    async def start(self) -> None:
        """Relay in the background, every ``poll_interval`` seconds."""
        await self._ensure_ready()  # connect here, never inside the cancellable task
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._poll())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def close(self) -> None:
        """Stop, and release the outbox storage's connections."""
        await self.stop()
        close = getattr(self.outbox, "close", None)
        if self._ready and callable(close):
            await close()
        self._ready = False

    async def _poll(self) -> None:
        while True:
            await self.relay()
            await asyncio.sleep(self.poll_interval)
