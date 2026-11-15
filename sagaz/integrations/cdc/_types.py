"""Types shared by the CDC sources and the CDC worker mode (ADR-011)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sagaz.core.outbox.types import OutboxEvent


class CDCError(Exception):
    """Raised when a CDC source cannot be read or a change cannot be decoded."""


@dataclass(frozen=True)
class CDCChange:
    """One outbox row insert captured from the database's change stream.

    ``committed_at`` is when the inserting transaction committed, used to
    measure CDC lag. ``position`` is opaque to the worker (a WAL LSN, a Kafka
    offset...) and is handed back to :meth:`CDCSource.ack` once the change has
    been processed.
    """

    event: OutboxEvent
    committed_at: datetime | None
    position: Any


@runtime_checkable
class CDCSource(Protocol):
    """A stream of outbox inserts, delivered in commit order.

    ``changes()`` yields batches; after processing a batch the worker calls
    ``ack(position)`` with the position of its last change, after which the
    source may discard everything up to it (advance the replication slot,
    commit the consumer offset). Changes not yet acknowledged are delivered
    again after a restart, so delivery is at least once.
    """

    name: str

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def changes(self) -> AsyncIterator[list[CDCChange]]: ...

    async def ack(self, position: Any) -> None: ...
