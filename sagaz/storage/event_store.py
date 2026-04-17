"""
SQLite-backed Event Store for saga event sourcing.

Provides an append-only, per-saga event stream with optional snapshot support.
Events are serialised to JSON and stored in a local SQLite database, making
this suitable for development, testing, and single-node deployments.

Usage::

    store = SQLiteEventStore()                     # in-memory (tests)
    store = SQLiteEventStore(db_path="events.db")  # persistent file

    seq = await store.append(SagaStarted(saga_id="s1", saga_name="OrderSaga"))
    events = await store.load_stream("s1")
    await store.save_snapshot(SagaSnapshot("s1", seq, projection.to_dict()))
    snap = await store.load_latest_snapshot("s1")
    store.close()
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from sagaz.core.events import SagaEvent, event_type_from_name

# ---------------------------------------------------------------------------
# SagaSnapshot
# ---------------------------------------------------------------------------


@dataclass
class SagaSnapshot:
    """A point-in-time snapshot of a saga's projection state.

    Parameters
    ----------
    saga_id:
        The saga this snapshot belongs to.
    sequence:
        The event sequence number at which the snapshot was taken.
    state:
        A plain-dict representation of the saga's projection at that sequence.
    """

    saga_id: str
    sequence: int
    state: dict[str, Any]


# ---------------------------------------------------------------------------
# SQLiteEventStore
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saga_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    saga_id     TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saga_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    saga_id     TEXT NOT NULL,
    sequence    INTEGER NOT NULL,
    state       TEXT NOT NULL
);
"""


class SQLiteEventStore:
    """Async-compatible SQLite event store.

    Parameters
    ----------
    db_path:
        Path to the SQLite file.  Defaults to ``:memory:`` (in-process,
        no persistence — ideal for tests).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Event stream
    # ------------------------------------------------------------------

    async def append(self, event: SagaEvent) -> int:
        """Persist *event* and return its sequence number (1-based)."""
        payload = json.dumps(event.to_dict())
        cursor = self._conn.execute(
            "INSERT INTO saga_events (saga_id, event_type, payload) VALUES (?, ?, ?)",
            (event.saga_id, type(event).__name__, payload),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def load_stream(self, saga_id: str) -> list[SagaEvent]:
        """Return all events for *saga_id* in insertion order."""
        rows = self._conn.execute(
            "SELECT event_type, payload FROM saga_events WHERE saga_id = ? ORDER BY id",
            (saga_id,),
        ).fetchall()
        return [self._deserialise(event_type, payload) for event_type, payload in rows]

    async def load_stream_after(self, saga_id: str, *, after_sequence: int) -> list[SagaEvent]:
        """Return events for *saga_id* whose sequence number exceeds *after_sequence*."""
        rows = self._conn.execute(
            "SELECT event_type, payload FROM saga_events WHERE saga_id = ? AND id > ? ORDER BY id",
            (saga_id, after_sequence),
        ).fetchall()
        return [self._deserialise(event_type, payload) for event_type, payload in rows]

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """Persist *snapshot* for later retrieval."""
        self._conn.execute(
            "INSERT INTO saga_snapshots (saga_id, sequence, state) VALUES (?, ?, ?)",
            (snapshot.saga_id, snapshot.sequence, json.dumps(snapshot.state)),
        )
        self._conn.commit()

    async def load_latest_snapshot(self, saga_id: str) -> SagaSnapshot | None:
        """Return the most-recent snapshot for *saga_id*, or ``None``."""
        row = self._conn.execute(
            "SELECT sequence, state FROM saga_snapshots"
            " WHERE saga_id = ? ORDER BY sequence DESC LIMIT 1",
            (saga_id,),
        ).fetchone()
        if row is None:
            return None
        sequence, state_json = row
        return SagaSnapshot(saga_id=saga_id, sequence=sequence, state=json.loads(state_json))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deserialise(event_type: str, payload: str) -> SagaEvent:
        data: dict[str, Any] = json.loads(payload)
        cls = event_type_from_name(event_type)
        if cls is None:
            msg = f"Unknown event type: {event_type!r}"
            raise ValueError(msg)
        # Remove base fields that conflict with frozen dataclass defaults
        data.pop("event_type", None)
        data.pop("occurred_at", None)
        data.pop("event_id", None)
        data.pop("metadata", None)
        saga_id = data.pop("saga_id")
        return cls(saga_id=saga_id, **data)  # type: ignore[return-value]
