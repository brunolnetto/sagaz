"""The ``SagaLogStore`` interface (ADR-041)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sagaz.core.storage.saga_log._model import (
    Activity,
    Deadline,
    ExportBatch,
    LogEvent,
    LogWrite,
    Participant,
    Snapshot,
    SnapshotKind,
    Transaction,
)

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces import OutboxStorage


class SagaLogStore(ABC):
    """Storage of the unified saga log, for orchestrated and choreographed sagas.

    Every operation acts in the current tenant scope (ADR-020); reads in the
    system scope span all tenants.
    """

    # -- writes ------------------------------------------------------------------

    @abstractmethod
    async def write(self, batch: LogWrite) -> list[LogEvent]:
        """Apply *batch* atomically; return its events with their sequences.

        Raises ``ConcurrencyError`` if ``batch.status`` expects another version.
        """

    @abstractmethod
    async def register_participant(self, participant: Participant) -> None:
        """Add or update a participant (and the database role it writes as)."""

    @abstractmethod
    async def claim_delivery(self, participant: str, event_id: str) -> bool:
        """Record that *participant* consumed *event_id*: True the first time only."""

    @abstractmethod
    async def save_snapshot(self, snapshot: Snapshot) -> None:
        """Store *snapshot* (replacing one at the same sequence and kind)."""

    @abstractmethod
    async def claim_due_deadlines(
        self, owners: Collection[str], now: datetime, lease: timedelta, limit: int = 100
    ) -> list[Deadline]:
        """Claim deadlines of *owners* due at *now*, in every tenant, for *lease*."""

    @abstractmethod
    def outbox_storage(self) -> OutboxStorage:
        """An ``OutboxStorage`` over the outbox this store writes ``LogWrite.publish`` to.

        Give it to an ``OutboxWorker`` (or use it with CDC) to relay the messages.
        """

    # -- reads -------------------------------------------------------------------

    @abstractmethod
    async def get_transaction(self, transaction_id: str) -> Transaction | None: ...

    @abstractmethod
    async def list_transactions(
        self,
        *,
        flow: str | None = None,
        coordination: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[Transaction]:
        """Transactions, newest first."""

    @abstractmethod
    async def activities(self, transaction_id: str) -> list[Activity]:
        """The transaction's activities, oldest first."""

    @abstractmethod
    async def events(self, transaction_id: str, after_sequence: int = 0) -> list[LogEvent]:
        """The transaction's log entries after *after_sequence*, in order."""

    @abstractmethod
    async def latest_snapshot(
        self, transaction_id: str, kind: SnapshotKind = SnapshotKind.PROJECTION
    ) -> Snapshot | None: ...

    @abstractmethod
    async def participants(self) -> list[Participant]: ...

    # -- lifecycle -----------------------------------------------------------------

    # -- export (ADR-013) --------------------------------------------------------

    async def read_committed(self, after: str | None = None, limit: int = 500) -> ExportBatch:
        """Committed events of every tenant after *after*, in an order no later
        commit can be inserted before (call in ``system_scope()`` under RLS)."""
        raise NotImplementedError(type(self).__name__)

    async def load_cursor(self, name: str) -> str | None:
        """The position the exporter *name* acknowledged last."""
        raise NotImplementedError(type(self).__name__)

    async def save_cursor(self, name: str, position: str) -> None:
        """Remember *position* as acknowledged by the exporter *name*."""
        raise NotImplementedError(type(self).__name__)

    async def close(self) -> None:
        """Release connections."""

    async def __aenter__(self) -> SagaLogStore:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
