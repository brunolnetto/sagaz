"""
SagaEventStore — abstract interface and SQLite backend for event-sourced storage.

The event store persists an append-only stream of ``SagaEvent`` objects.
A snapshot mechanism limits stream replay cost for long-running sagas.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sagaz.core.events import (
    SagaEvent,
    event_type_from_name,
)

# ---------------------------------------------------------------------------
# Snapshot value object
# ---------------------------------------------------------------------------


@dataclass
class SagaSnapshot:
    """Materialized saga state at a given event sequence number."""

    saga_id: str
    sequence: int
    state: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class SagaEventStore(ABC):
    """
    Append-only event store for saga domain events.

    Implementations persist events to durable storage; ``load_stream`` returns
    them in sequence order for replay.
    """

    @abstractmethod
    async def append(self, event: SagaEvent) -> int:
        """
        Persist *event* and return its sequence number.

        Parameters
        ----------
        event:
            A ``SagaEvent`` subclass instance.

        Returns
        -------
        int
            1-based sequence number assigned to this event.
        """

    @abstractmethod
    async def load_stream(self, saga_id: str) -> list[SagaEvent]:
        """
        Return all events for *saga_id* in sequence order.
        """

    @abstractmethod
    async def load_stream_after(self, saga_id: str, after_sequence: int) -> list[SagaEvent]:
        """
        Return events for *saga_id* with sequence > *after_sequence*.
        """

    @abstractmethod
    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """Persist a snapshot for *saga_id* at *sequence*."""

    @abstractmethod
    async def load_latest_snapshot(self, saga_id: str) -> SagaSnapshot | None:
        """Return the most recent snapshot for *saga_id*, or *None*."""


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS saga_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    saga_id     TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    occurred_at TEXT    NOT NULL
)
"""

_CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS saga_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    saga_id    TEXT    NOT NULL,
    sequence   INTEGER NOT NULL,
    state      TEXT    NOT NULL,
    created_at TEXT    NOT NULL
)
"""

_INSERT_EVENT = """
INSERT INTO saga_events (saga_id, event_type, payload, occurred_at)
VALUES (?, ?, ?, ?)
"""

_SELECT_STREAM = """
SELECT id, event_type, payload
FROM saga_events
WHERE saga_id = ?
ORDER BY id
"""

_SELECT_STREAM_AFTER = """
SELECT id, event_type, payload
FROM saga_events
WHERE saga_id = ? AND id > ?
ORDER BY id
"""

_INSERT_SNAPSHOT = """
INSERT INTO saga_snapshots (saga_id, sequence, state, created_at)
VALUES (?, ?, ?, ?)
"""

_SELECT_LATEST_SNAPSHOT = """
SELECT sequence, state, created_at
FROM saga_snapshots
WHERE saga_id = ?
ORDER BY sequence DESC
LIMIT 1
"""


def _deserialize_event(event_type: str, payload: str) -> SagaEvent | None:
    cls = event_type_from_name(event_type)
    if cls is None:
        return None
    data = json.loads(payload)
    # Remove fields that are set by the dataclass itself (event_id, occurred_at)
    data.pop("event_type", None)
    data.pop("occurred_at", None)
    return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


class SQLiteEventStore(SagaEventStore):
    """
    SQLite-backed ``SagaEventStore`` suitable for development and testing.

    Parameters
    ----------
    db_path:
        Path to the SQLite file, or ``":memory:"`` for an in-process store.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(_CREATE_EVENTS)
            self._conn.execute(_CREATE_SNAPSHOTS)
            self._conn.commit()
        return self._conn

    async def append(self, event: SagaEvent) -> int:
        conn = self._get_conn()
        payload = json.dumps(event.to_dict())
        cursor = conn.execute(
            _INSERT_EVENT,
            (event.saga_id, type(event).__name__, payload, event.occurred_at.isoformat()),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def load_stream(self, saga_id: str) -> list[SagaEvent]:
        conn = self._get_conn()
        rows = conn.execute(_SELECT_STREAM, (saga_id,)).fetchall()
        events: list[SagaEvent] = []
        for row in rows:
            ev = _deserialize_event(row["event_type"], row["payload"])
            if ev is not None:
                events.append(ev)
        return events

    async def load_stream_after(self, saga_id: str, after_sequence: int) -> list[SagaEvent]:
        conn = self._get_conn()
        rows = conn.execute(_SELECT_STREAM_AFTER, (saga_id, after_sequence)).fetchall()
        events: list[SagaEvent] = []
        for row in rows:
            ev = _deserialize_event(row["event_type"], row["payload"])
            if ev is not None:
                events.append(ev)
        return events

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        conn = self._get_conn()
        conn.execute(
            _INSERT_SNAPSHOT,
            (
                snapshot.saga_id,
                snapshot.sequence,
                json.dumps(snapshot.state),
                snapshot.created_at.isoformat(),
            ),
        )
        conn.commit()

    async def load_latest_snapshot(self, saga_id: str) -> SagaSnapshot | None:
        conn = self._get_conn()
        row = conn.execute(_SELECT_LATEST_SNAPSHOT, (saga_id,)).fetchone()
        if row is None:
            return None
        return SagaSnapshot(
            saga_id=saga_id,
            sequence=row["sequence"],
            state=json.loads(row["state"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
