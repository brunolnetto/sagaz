"""Copy the old storage layout into the unified saga log (ADR-041, #464).

``unify(url)`` reads, from the database at *url*:

- sagas and their steps (any saga storage, through ``export_all()``), including
  the ``ChoreographyTracker``'s records;
- the ADR-033 event store (``saga_events``, ``saga_event_snapshots``);
- choreography participant state (``choreography_*``), the outbox consumers'
  ``consumer_inbox`` and the replay snapshots (``saga_snapshots``);

and writes them into the unified tables of the same database (or of
*target_url*). The old tables are left untouched. Running it again changes
nothing: transactions are inserted once, activities and snapshots are upserted,
deliveries are claimed once, and a transaction's log is only filled while empty.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sagaz.choreography.events import COMPENSATE, COMPENSATED
from sagaz.core.events import SagaEvent
from sagaz.core.storage.saga_log import _codec as codec
from sagaz.core.storage.saga_log._base import SagaLogStore
from sagaz.core.storage.saga_log._model import (
    ORCHESTRATOR,
    TRANSACTION_MARKER,
    Activity,
    Coordination,
    Deadline,
    EventKind,
    LogEvent,
    LogWrite,
    Snapshot,
    SnapshotKind,
    Transaction,
    status_changed,
)
from sagaz.core.tenant import system_scope, tenant_scope

FINISHED = frozenset({"completed", "rolled_back", "failed", "compensated"})
OLD_TABLES = (
    "saga_events",
    "saga_event_snapshots",
    "choreography_actions",
    "choreography_transactions",
    "choreography_deliveries",
    "choreography_deadlines",
    "consumer_inbox",
    "saga_snapshots",
)


@dataclass
class MigrationReport:
    """What was (or, in a dry run, would be) copied, by kind."""

    counts: Counter[str] = field(default_factory=Counter)
    dry_run: bool = False

    def add(self, kind: str, n: int = 1) -> None:
        self.counts[kind] += n


def _value(raw: Any) -> Any:
    return getattr(raw, "value", raw)


def _when(raw: Any) -> datetime | None:
    return codec.as_datetime(raw) if raw else None


def _json(raw: Any) -> Any:
    return json.loads(raw) if isinstance(raw, str) else raw


# -- sagas, steps and tracker records -----------------------------------------------


def _step_activity(tid: str, step: dict[str, Any]) -> Activity:
    executed = _when(step.get("executed_at"))
    return Activity(
        tid,
        str(step["name"]),
        ORCHESTRATOR,
        str(step["name"]),
        status=str(_value(step.get("status")) or "pending"),
        attempt=int(step.get("retry_count") or 0) + 1,
        result=step.get("result"),
        error=step.get("error"),
        started_at=executed,
        ended_at=_when(step.get("compensated_at")) or executed,
        duration_ms=step.get("duration_ms"),
    )


def _orchestrated(record: dict[str, Any]) -> LogWrite:
    tid, status = record["saga_id"], str(_value(record.get("status")) or "executing")
    transaction = Transaction(
        tid,
        record.get("saga_name") or "unknown",
        Coordination.ORCHESTRATED,
        status=status,
        initiator=ORCHESTRATOR,
        started_at=_when(record.get("created_at")) or datetime.now(UTC),
        ended_at=_when(record.get("updated_at")) if status in FINISHED else None,
        context=dict(record.get("context") or {}),
    )
    steps = [s for s in record.get("steps") or [] if s.get("name")]
    return LogWrite(transaction=transaction, activities=[_step_activity(tid, s) for s in steps])


def _kind(event_type: str) -> EventKind:
    if event_type == COMPENSATE:
        return EventKind.COMPENSATE
    if event_type == COMPENSATED:
        return EventKind.COMPENSATED
    return EventKind.BUSINESS


def _payload(kind: EventKind, source: Any, status: dict[str, Any]) -> dict[str, Any]:
    """The tracker kept compensation data beside its events; put it back on them."""
    if kind == EventKind.COMPENSATE:
        return dict(status.get("failure") or {})
    if kind == EventKind.COMPENSATED:
        return dict((status.get("compensated_by") or {}).get(source) or {})
    return {}


def _tracked_events(tid: str, status: dict[str, Any]) -> list[LogEvent]:
    events = []
    for e in sorted(status.get("events") or [], key=lambda e: str(e.get("at"))):
        kind = _kind(str(e.get("event_type")))
        events.append(
            LogEvent(
                tid,
                str(e.get("event_type")),
                kind,
                event_id=str(e.get("event_id")),
                source=e.get("source"),
                causation_id=e.get("causation_id"),
                payload=_payload(kind, e.get("source"), status),
                occurred_at=_when(e.get("at")) or datetime.now(UTC),
            )
        )
    return events


def _choreographed(record: dict[str, Any]) -> LogWrite:
    status = dict(record.get("context") or {})
    tid = status.get("correlation_id") or record["saga_id"]
    events = _tracked_events(tid, status)
    state = status.get("status") or "executing"
    transaction = _flow_transaction(tid, state, events)
    if events and state != "executing":  # what the tracker records on the log
        at = events[-1].occurred_at
        events.append(
            status_changed(tid, state, "executing", source=transaction.initiator, occurred_at=at)
        )
    return LogWrite(transaction=transaction, events=events)


def _flow_transaction(tid: str, state: str, events: list[LogEvent]) -> Transaction:
    """A choreographed transaction: its flow and initiator come from its first business event."""
    first = next((e for e in events if e.kind == EventKind.BUSINESS), None)
    if not events:
        return Transaction(tid, "unknown", Coordination.CHOREOGRAPHED, status=state)
    return Transaction(
        tid,
        first.event_type if first else "unknown",
        Coordination.CHOREOGRAPHED,
        status=state,
        initiator=first.source if first else None,
        started_at=events[0].occurred_at,
        ended_at=events[-1].occurred_at if state in FINISHED else None,
    )


# -- event store and participant state ----------------------------------------------


def _lifecycle(row: dict[str, Any]) -> LogEvent:
    body = SagaEvent.from_dict(_json(row["body"]))
    return LogEvent(
        row["saga_id"],
        body.event_type,
        EventKind.LIFECYCLE,
        event_id=body.event_id,
        source=ORCHESTRATOR,
        payload={**body.payload, "saga_name": body.saga_name},
        occurred_at=body.occurred_at,
        event_version=body.event_version,
    )


def _action(row: dict[str, Any]) -> Activity:
    body = _json(row["body"])
    return Activity(
        row["correlation_id"],
        f"{row['participant']}:{row['event_id']}",
        row["participant"],
        str(body.get("event_type")),
        status="completed",
        triggered_by=row["event_id"],
        started_at=_when(body.get("created_at")),
    )


def _marker(row: dict[str, Any]) -> Activity:
    return Activity(
        row["correlation_id"],
        f"{row['participant']}:{TRANSACTION_MARKER}",
        row["participant"],
        TRANSACTION_MARKER,
        status=row["state"],
        ended_at=_when(row.get("ended_at")),
    )


class Unifier:
    """Copies old-layout rows into a :class:`SagaLogStore` (see :func:`unify`)."""

    def __init__(self, log: SagaLogStore, report: MigrationReport) -> None:
        self.log, self.report = log, report

    async def _write(self, tenant: str, batch: LogWrite, kind: str) -> None:
        self.report.add(kind)
        if self.report.dry_run:
            return
        with tenant_scope(tenant):
            if batch.events and await self.log.events(batch.events[0].transaction_id):
                batch.events = []  # this transaction's log was already copied
            await self.log.write(batch)

    async def sagas(self, records: list[dict[str, Any]]) -> None:
        from sagaz.choreography.tracker import RECORD_NAME
        from sagaz.versioning.registry import VERSION_RECORD_SAGA_NAME

        for record in records:
            name = record.get("saga_name")
            tenant = record.get("tenant_id") or "default"
            if name == VERSION_RECORD_SAGA_NAME:
                continue
            if name == RECORD_NAME:
                await self._write(tenant, _choreographed(record), "choreographed transactions")
            else:
                await self._write(tenant, _orchestrated(record), "orchestrated transactions")

    async def event_store(self, rows: list[dict[str, Any]]) -> None:
        streams: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            streams.setdefault((row["tenant_id"], row["saga_id"]), []).append(row)
        for (tenant, tid), stream in streams.items():
            events = [_lifecycle(r) for r in sorted(stream, key=lambda r: r["sequence"])]
            first = SagaEvent.from_dict(_json(stream[0]["body"]))
            transaction = Transaction(
                tid,
                first.saga_name or "unknown",
                Coordination.ORCHESTRATED,
                status=_status_from(events),
                initiator=ORCHESTRATOR,
                started_at=events[0].occurred_at,
                ended_at=events[-1].occurred_at if _status_from(events) in FINISHED else None,
            )
            await self._write(
                tenant, LogWrite(transaction=transaction, events=events), "event streams"
            )

    async def participant_state(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        for row in tables.get("choreography_actions", []):
            await self._write(row["tenant_id"], LogWrite(activities=[_action(row)]), "actions")
        for row in tables.get("choreography_transactions", []):
            await self._write(row["tenant_id"], LogWrite(activities=[_marker(row)]), "markers")
        for row in tables.get("choreography_deadlines", []):
            deadline = Deadline(
                row["correlation_id"],
                row["participant"],
                codec.as_datetime(row["due_at"]),  # type: ignore[arg-type]
            )
            await self._write(row["tenant_id"], LogWrite(deadline=deadline), "deadlines")

    async def deliveries(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        rows = [
            (r["tenant_id"], r["participant"], r["event_id"])
            for r in tables.get("choreography_deliveries", [])
        ] + [
            ("default", r["consumer_name"], str(r["event_id"]))
            for r in tables.get("consumer_inbox", [])
        ]
        for tenant, participant, event_id in rows:
            self.report.add("deliveries")
            if not self.report.dry_run:
                with tenant_scope(tenant):
                    await self.log.claim_delivery(participant, event_id)

    async def snapshots(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        snapshots = [
            Snapshot(
                r["saga_id"],
                r["sequence"],
                _json(r["state"]),
                SnapshotKind.PROJECTION,
                r["tenant_id"],
                codec.as_datetime(r["created_at"]),  # type: ignore[arg-type]
            )
            for r in tables.get("saga_event_snapshots", [])
        ] + [
            Snapshot(
                str(r["saga_id"]),
                int(r["step_index"]),
                codec.loads(codec.dumps(r)),
                SnapshotKind.REPLAY,
                r.get("tenant_id") or "default",
            )
            for r in tables.get("saga_snapshots", [])
        ]
        for snapshot in snapshots:
            self.report.add("snapshots")
            if not self.report.dry_run:
                with tenant_scope(snapshot.tenant_id):
                    await self.log.save_snapshot(snapshot)


def _status_from(events: list[LogEvent]) -> str:
    terminal = {
        "SagaCompleted": "completed",
        "SagaRolledBack": "rolled_back",
        "SagaFailed": "failed",
    }
    for event in reversed(events):
        if event.event_type in terminal:
            return terminal[event.event_type]
    return "executing"


async def unify(
    saga_storage: Any,
    log: SagaLogStore,
    old_tables: dict[str, list[dict[str, Any]]],
    *,
    dry_run: bool = False,
) -> MigrationReport:
    """Copy *saga_storage*'s sagas and the *old_tables* rows into *log*."""
    report = MigrationReport(dry_run=dry_run)
    unifier = Unifier(log, report)
    with system_scope():
        records = [r async for r in saga_storage.export_all()]
    await unifier.sagas(records)
    await unifier.event_store(old_tables.get("saga_events", []))
    await unifier.participant_state(old_tables)
    await unifier.deliveries(old_tables)
    await unifier.snapshots(old_tables)
    return report


async def read_old_tables(url: str) -> dict[str, list[dict[str, Any]]]:
    """Every row of the old-layout tables that exist at *url* (all tenants)."""
    if url.startswith(("postgresql://", "postgres://")):
        return await _read_postgresql(url)
    if url.startswith("sqlite://"):
        return await _read_sqlite(url[len("sqlite://") :])
    return {}  # memory:// and redis:// keep no such tables


async def _read_postgresql(url: str) -> dict[str, list[dict[str, Any]]]:
    import asyncpg

    conn = await asyncpg.connect(url)
    try:
        await conn.execute("SELECT set_config('app.tenant_id', '*', false)")  # all tenants
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in OLD_TABLES:
            if await conn.fetchval("SELECT to_regclass($1)", table) is not None:
                rows = await conn.fetch(f"SELECT * FROM {table}")  # nosec B608 - fixed names
                tables[table] = [dict(r) for r in rows]
        return tables
    finally:
        await conn.close()


async def _read_sqlite(path: str) -> dict[str, list[dict[str, Any]]]:
    import aiosqlite

    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        present = {row[0] for row in await cursor.fetchall()}
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in OLD_TABLES:
            if table in present:
                cursor = await conn.execute(f"SELECT * FROM {table}")  # nosec B608 - fixed names
                tables[table] = [dict(r) for r in await cursor.fetchall()]
        return tables
