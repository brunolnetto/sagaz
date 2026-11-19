"""The unified saga log (ADR-041): one OLTP model for orchestrated and choreographed sagas."""

from __future__ import annotations

from sagaz.core.storage.saga_log._base import SagaLogStore
from sagaz.core.storage.saga_log._model import (
    ORCHESTRATOR,
    STATUS_CHANGED,
    TRANSACTION_MARKER,
    Activity,
    ConcurrencyError,
    Coordination,
    Deadline,
    EventKind,
    ExportBatch,
    ExportedEvent,
    LogEvent,
    LogWrite,
    OutboxMessage,
    Participant,
    Snapshot,
    SnapshotKind,
    StatusChange,
    Transaction,
    status_changed,
)
from sagaz.core.storage.saga_log.export import ExportSink, SagaLogExporter, SagaLogReader
from sagaz.core.storage.saga_log.memory import InMemorySagaLogStore


def create_saga_log_store(url: str) -> SagaLogStore:
    """A saga log store for *url*: ``memory://``, ``sqlite://<path>`` or ``postgresql://...``."""
    if url.startswith("memory://"):
        return InMemorySagaLogStore()
    if url.startswith("sqlite://"):
        from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore

        return SQLiteSagaLogStore(url[len("sqlite://") :] or ":memory:")
    if url.startswith(("postgresql://", "postgres://")):
        from sagaz.core.storage.saga_log.postgresql import PostgreSQLSagaLogStore

        return PostgreSQLSagaLogStore(url)
    msg = f"Unsupported saga log URL {url!r}: use memory://, sqlite:// or postgresql://"
    raise ValueError(msg)


__all__ = [
    "ORCHESTRATOR",
    "STATUS_CHANGED",
    "TRANSACTION_MARKER",
    "Activity",
    "ConcurrencyError",
    "Coordination",
    "Deadline",
    "EventKind",
    "ExportBatch",
    "ExportSink",
    "ExportedEvent",
    "InMemorySagaLogStore",
    "LogEvent",
    "LogWrite",
    "OutboxMessage",
    "Participant",
    "SagaLogExporter",
    "SagaLogReader",
    "SagaLogStore",
    "Snapshot",
    "SnapshotKind",
    "StatusChange",
    "Transaction",
    "create_saga_log_store",
    "status_changed",
]
