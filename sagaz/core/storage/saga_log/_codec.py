"""Row <-> record conversion shared by the SQL saga log stores."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from sagaz.core.events import json_safe
from sagaz.core.storage.saga_log._model import (
    Activity,
    Coordination,
    Deadline,
    EventKind,
    LogEvent,
    Participant,
    Snapshot,
    SnapshotKind,
    Transaction,
)

TRANSACTION_COLUMNS = (
    "tenant_id", "transaction_id", "flow", "coordination", "status", "initiator",
    "started_at", "ended_at", "context", "version", "updated_at",
)  # fmt: skip
ACTIVITY_COLUMNS = (
    "tenant_id", "transaction_id", "activity_id", "participant", "name", "status", "attempt",
    "region", "triggered_by", "result", "error", "started_at", "ended_at", "duration_ms",
)  # fmt: skip
EVENT_COLUMNS = (
    "tenant_id", "transaction_id", "sequence", "event_id", "event_type", "kind", "source",
    "causation_id", "payload", "occurred_at", "event_version",
)  # fmt: skip
JSON_COLUMNS = frozenset({"context", "result", "payload", "state"})


def dumps(value: Any) -> str:
    return json.dumps(json_safe(value))


def loads(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def transaction_values(t: Transaction, tenant: str) -> list[Any]:
    return [
        tenant, t.transaction_id, t.flow, str(t.coordination), t.status, t.initiator,
        t.started_at, t.ended_at, dumps(t.context), t.version, t.updated_at,
    ]  # fmt: skip


def activity_values(a: Activity, tenant: str) -> list[Any]:
    return [
        tenant, a.transaction_id, a.activity_id, a.participant, a.name, a.status, a.attempt,
        a.region, a.triggered_by, dumps(a.result), a.error, a.started_at, a.ended_at,
        a.duration_ms,
    ]  # fmt: skip


def event_values(e: LogEvent, tenant: str, sequence: int) -> list[Any]:
    return [
        tenant, e.transaction_id, sequence, e.event_id, e.event_type, str(e.kind), e.source,
        e.causation_id, dumps(e.payload), e.occurred_at, e.event_version,
    ]  # fmt: skip


class Row(Protocol):
    """A database row read by column name: a dict, an asyncpg ``Record`` or a ``sqlite3.Row``."""

    def __getitem__(self, key: str, /) -> Any: ...


def to_transaction(row: Row) -> Transaction:
    return Transaction(
        transaction_id=row["transaction_id"],
        flow=row["flow"],
        coordination=Coordination(row["coordination"]),
        status=row["status"],
        initiator=row["initiator"],
        tenant_id=row["tenant_id"],
        started_at=as_datetime(row["started_at"]),  # type: ignore[arg-type]
        ended_at=as_datetime(row["ended_at"]),
        context=loads(row["context"]) or {},
        version=row["version"],
        updated_at=as_datetime(row["updated_at"]),  # type: ignore[arg-type]
    )


def to_activity(row: Row) -> Activity:
    return Activity(
        transaction_id=row["transaction_id"],
        activity_id=row["activity_id"],
        participant=row["participant"],
        name=row["name"],
        status=row["status"],
        attempt=row["attempt"],
        region=row["region"],
        triggered_by=row["triggered_by"],
        result=loads(row["result"]),
        error=row["error"],
        started_at=as_datetime(row["started_at"]),
        ended_at=as_datetime(row["ended_at"]),
        duration_ms=row["duration_ms"],
        tenant_id=row["tenant_id"],
    )


def to_event(row: Row) -> LogEvent:
    return LogEvent(
        transaction_id=row["transaction_id"],
        event_type=row["event_type"],
        kind=EventKind(row["kind"]),
        event_id=row["event_id"],
        source=row["source"],
        causation_id=row["causation_id"],
        payload=loads(row["payload"]) or {},
        occurred_at=as_datetime(row["occurred_at"]),  # type: ignore[arg-type]
        sequence=row["sequence"],
        event_version=row["event_version"],
        tenant_id=row["tenant_id"],
    )


def to_snapshot(row: Row) -> Snapshot:
    return Snapshot(
        transaction_id=row["transaction_id"],
        sequence=row["sequence"],
        state=loads(row["state"]) or {},
        kind=SnapshotKind(row["kind"]),
        tenant_id=row["tenant_id"],
        created_at=as_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


def to_participant(row: Row) -> Participant:
    return Participant(
        name=row["name"],
        region=row["region"],
        owner=row["owner"],
        db_role=row["db_role"],
        tenant_id=row["tenant_id"],
    )


def to_deadline(row: Row) -> Deadline:
    return Deadline(
        transaction_id=row["transaction_id"],
        owner=row["owner"],
        due_at=as_datetime(row["due_at"]),  # type: ignore[arg-type]
        claimed_until=as_datetime(row["claimed_until"]),
        tenant_id=row["tenant_id"],
    )
