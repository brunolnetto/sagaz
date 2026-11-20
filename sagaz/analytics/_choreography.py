"""Choreographed sagas in the analytics pipeline (#459, ADR-029, ADR-043).

A :class:`~sagaz.choreography.ChoreographyTracker` with a saga storage saves
each choreographed transaction as a saga record named ``choreography``, with
its events, participants, failure and compensation reports in ``context``.
This module turns those records into two Silver tables:

- ``fact_choreography_event``: one row per event, with the hop latency from
  the event that caused it (``causation_id``);
- ``fact_choreography_transaction``: one row per transaction (accumulating
  snapshot), with its flow, status, duration, failure and compensations;
- ``fact_choreography_compensation``: one row per participant that reported
  compensating a transaction, with what it undid and what it failed to undo.

The *flow* of a transaction is the type of its first business event, such as
``order.created``. It plays the role of the saga name in orchestration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sagaz.choreography.events import COMPENSATE, COMPENSATED
from sagaz.choreography.tracker import RECORD_NAME

if TYPE_CHECKING:
    import duckdb

#: Transaction statuses that end a transaction.
FINISHED = frozenset({"completed", "compensated", "failed"})

TABLES_SQL = (
    """
    CREATE TABLE IF NOT EXISTS fact_choreography_transaction (
        tenant_id              TEXT NOT NULL,
        correlation_id         TEXT NOT NULL,
        flow                   TEXT NOT NULL,
        status                 TEXT NOT NULL,
        started_at             TIMESTAMP,
        ended_at               TIMESTAMP,
        duration_ms            DOUBLE,
        event_count            INTEGER DEFAULT 0,
        participant_count      INTEGER DEFAULT 0,
        failed_participant     TEXT,
        failed_event_type      TEXT,
        failure_reason         TEXT,
        compensations_undone   INTEGER DEFAULT 0,
        compensation_failures  INTEGER DEFAULT 0,
        PRIMARY KEY (tenant_id, correlation_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_choreography_event (
        tenant_id       TEXT NOT NULL,
        correlation_id  TEXT NOT NULL,
        flow            TEXT NOT NULL,
        event_id        TEXT,
        event_type      TEXT NOT NULL,
        kind            TEXT NOT NULL,
        participant     TEXT,
        occurred_at     TIMESTAMP,
        causation_id    TEXT,
        hop_ms          DOUBLE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_choreography_compensation (
        tenant_id       TEXT NOT NULL,
        correlation_id  TEXT NOT NULL,
        flow            TEXT NOT NULL,
        participant     TEXT NOT NULL,
        undone          INTEGER DEFAULT 0,
        failed          INTEGER DEFAULT 0
    )
    """,
)
TABLES = (
    "fact_choreography_event",
    "fact_choreography_compensation",
    "fact_choreography_transaction",
)


def is_choreography_record(record: dict[str, Any]) -> bool:
    return record.get("saga_name") == RECORD_NAME


def _naive_utc(raw: Any) -> datetime | None:
    if not raw:
        return None
    parsed = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def _kind(event_type: str) -> str:
    if event_type == COMPENSATE:
        return "compensate"
    if event_type == COMPENSATED:
        return "compensated"
    return "business"


def _ms(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None:
        return None
    return round((later - earlier).total_seconds() * 1000, 3)


def _sorted_events(status: dict[str, Any]) -> list[dict[str, Any]]:
    events = ({**e, "at": _naive_utc(e.get("at"))} for e in status.get("events") or [])
    return sorted(events, key=lambda e: (e["at"] is None, e["at"] or datetime.min))


def _flow(events: list[dict[str, Any]]) -> str:
    """The type of the transaction's first business event."""
    for event in events:
        if _kind(event.get("event_type", "")) == "business":
            return str(event["event_type"])
    return "unknown"


def _transaction_row(
    key: dict[str, Any], status: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    times = [e["at"] for e in events if e["at"] is not None]
    started_at = min(times, default=None)
    state = status.get("status") or "executing"
    ended_at = max(times, default=None) if state in FINISHED else None
    return {
        **key,
        "status": state,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": _ms(ended_at, started_at),
        "event_count": len(events),
        "participant_count": len(status.get("participants") or []),
        **_failure_columns(status),
    }


def _failure_columns(status: dict[str, Any]) -> dict[str, Any]:
    failure = status.get("failure") or {}
    reports = list((status.get("compensated_by") or {}).values())
    return {
        "failed_participant": failure.get("participant"),
        "failed_event_type": failure.get("failed_event_type"),
        "failure_reason": failure.get("reason"),
        "compensations_undone": sum(len(r.get("undone") or []) for r in reports),
        "compensation_failures": sum(len(r.get("failed") or []) for r in reports),
    }


def _event_rows(key: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    at_by_id = {e.get("event_id"): e["at"] for e in events}
    return [
        {
            **key,
            "event_id": e.get("event_id"),
            "event_type": e.get("event_type"),
            "kind": _kind(e.get("event_type", "")),
            "participant": e.get("source"),
            "occurred_at": e["at"],
            "causation_id": e.get("causation_id"),
            "hop_ms": _ms(e["at"], at_by_id.get(e.get("causation_id"))),
        }
        for e in events
    ]


def _compensation_rows(key: dict[str, Any], status: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **key,
            "participant": participant,
            "undone": len(report.get("undone") or []),
            "failed": len(report.get("failed") or []),
        }
        for participant, report in sorted((status.get("compensated_by") or {}).items())
    ]


def choreography_rows(
    record: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """The transaction row, event rows and compensation rows of one tracker record."""
    status = dict(record.get("context") or {})
    events = _sorted_events(status)
    key = {
        "tenant_id": status.get("tenant_id") or record.get("tenant_id") or "default",
        "correlation_id": status.get("correlation_id") or record["saga_id"],
        "flow": _flow(events),
    }
    return (
        _transaction_row(key, status, events),
        _event_rows(key, events),
        _compensation_rows(key, status),
    )


class _ChoreographyLoaderMixin:
    """Silver loaders for choreography records, mixed into the pipeline."""

    _conn: duckdb.DuckDBPyConnection

    def _ensure_choreography_schema(self) -> None:
        for ddl in TABLES_SQL:
            self._conn.execute(ddl)

    def load_choreography_records(self, records: list[dict[str, Any]]) -> int:
        """Load tracker records (``saga_name == "choreography"``); return how many."""
        self._ensure_choreography_schema()
        loaded = 0
        for record in records:
            if not is_choreography_record(record):
                continue
            transaction, events, compensations = choreography_rows(record)
            key = [transaction["tenant_id"], transaction["correlation_id"]]
            self._insert("fact_choreography_transaction", [transaction], replace=True)
            for table, rows in (
                ("fact_choreography_event", events),
                ("fact_choreography_compensation", compensations),
            ):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE tenant_id = ? AND correlation_id = ?",  # nosec B608
                    key,
                )
                self._insert(table, rows)
            loaded += 1
        return loaded

    def _insert(self, table: str, rows: list[dict[str, Any]], *, replace: bool = False) -> None:
        """Insert *rows* (dicts with the same keys) into *table*, a module constant."""
        if not rows:
            return
        columns = list(rows[0])
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        self._conn.executemany(
            f"{verb} INTO {table} ({', '.join(columns)})"  # nosec B608 - fixed names
            f" VALUES ({', '.join('?' for _ in columns)})",
            [list(row.values()) for row in rows],
        )

    def _reset_choreography(self) -> None:
        self._ensure_choreography_schema()
        for table in TABLES:
            self._conn.execute(f"DELETE FROM {table}")  # nosec B608 - fixed table names
