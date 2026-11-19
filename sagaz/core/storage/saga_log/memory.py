"""In-memory saga log, for unit tests and single-process development."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.core.storage._tenancy import scoped_tenant, write_tenant
from sagaz.core.storage.saga_log._base import SagaLogStore
from sagaz.core.storage.saga_log._model import (
    TRANSACTION_MARKER,
    Activity,
    ConcurrencyError,
    Deadline,
    LogEvent,
    LogWrite,
    OutboxMessage,
    Participant,
    Snapshot,
    SnapshotKind,
    Transaction,
)

Key = tuple[str, str]  # (tenant_id, transaction_id)
COMPENSATED_MARKER = "compensated"
ENDED_MARKERS = frozenset({"completed", COMPENSATED_MARKER})


def _keeps_compensated(previous: Activity | None, new: Activity) -> bool:
    """A participant's marker never goes back from compensated to completed."""
    return (
        previous is not None
        and new.name == TRANSACTION_MARKER
        and previous.status == COMPENSATED_MARKER
    )


def _outbox_event(message: OutboxMessage) -> Any:
    from sagaz.core.outbox.types import OutboxEvent

    return OutboxEvent(
        saga_id=message.transaction_id,
        aggregate_type=message.aggregate_type,
        aggregate_id=message.transaction_id,
        event_type=message.event_type,
        payload=message.payload,
        headers={"log_event_id": message.log_event_id} if message.log_event_id else {},
        partition_key=message.partition_key,
    )


class InMemorySagaLogStore(SagaLogStore):
    def __init__(self) -> None:
        self._transactions: dict[Key, Transaction] = {}
        self._activities: dict[Key, dict[str, Activity]] = {}
        self._events: dict[Key, list[LogEvent]] = {}
        self._event_ids: set[str] = set()
        self._snapshots: dict[tuple[str, str, str], dict[int, Snapshot]] = {}
        self._participants: dict[Key, Participant] = {}
        self._deliveries: set[tuple[str, str, str]] = set()
        self._deadlines: dict[tuple[str, str, str], Deadline] = {}
        self._lock = asyncio.Lock()
        from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

        self._outbox = InMemoryOutboxStorage()

    def outbox_storage(self) -> Any:
        return self._outbox

    # -- writes ------------------------------------------------------------------

    async def write(self, batch: LogWrite) -> list[LogEvent]:
        tenant = write_tenant()
        async with self._lock:
            self._check(tenant, batch)
            batch.drop_guarded(
                {t for t in batch.guarded_transactions() if self._ended(tenant, t, batch.guard)}
            )
            if batch.transaction is not None:
                key = (tenant, batch.transaction.transaction_id)
                self._transactions.setdefault(
                    key, replace(copy.deepcopy(batch.transaction), tenant_id=tenant)
                )
            if batch.status is not None:
                self._apply_status(tenant, batch)
            stored = [self._append(tenant, event) for event in batch.events]
            for activity in batch.activities:
                self._upsert_activity(tenant, activity)
            self._apply_deadlines(tenant, batch)
        for message in batch.publish:
            await self._outbox.insert(_outbox_event(message))
        return stored

    def _upsert_activity(self, tenant: str, activity: Activity) -> None:
        activities = self._activities.setdefault((tenant, activity.transaction_id), {})
        stored = replace(copy.deepcopy(activity), tenant_id=tenant)
        if _keeps_compensated(activities.get(activity.activity_id), activity):
            stored = replace(stored, status=COMPENSATED_MARKER)
        activities[activity.activity_id] = stored

    def _apply_deadlines(self, tenant: str, batch: LogWrite) -> None:
        if batch.deadline is not None:
            d = batch.deadline
            self._deadlines[(tenant, d.transaction_id, d.owner)] = replace(d, tenant_id=tenant)
        for transaction_id, owner in batch.clear_deadlines:
            self._deadlines.pop((tenant, transaction_id, owner), None)

    def _ended(self, tenant: str, transaction_id: str, participant: str | None) -> bool:
        return any(
            a.participant == participant
            and a.name == TRANSACTION_MARKER
            and a.status in ENDED_MARKERS
            for a in self._activities.get((tenant, transaction_id), {}).values()
        )

    def _check(self, tenant: str, batch: LogWrite) -> None:
        """Validate the whole batch before changing anything (atomicity)."""
        if batch.status is not None:
            current = self._transactions.get((tenant, batch.status.transaction_id))
            if current is None and batch.transaction is not None:
                current = batch.transaction
            if current is None or current.version != batch.status.expected_version:
                found = None if current is None else current.version
                msg = (
                    f"Transaction {batch.status.transaction_id} is at version {found}, "
                    f"expected {batch.status.expected_version}"
                )
                raise ConcurrencyError(msg)
        ids = [e.event_id for e in batch.events]
        if len(set(ids)) != len(ids) or self._event_ids.intersection(ids):
            msg = "Duplicate event_id in the saga log"
            raise ValueError(msg)

    def _apply_status(self, tenant: str, batch: LogWrite) -> None:
        change = batch.status
        assert change is not None
        key = (tenant, change.transaction_id)
        current = self._transactions[key]
        self._transactions[key] = replace(
            current,
            status=change.status,
            ended_at=change.ended_at or current.ended_at,
            context=copy.deepcopy(change.context)
            if change.context is not None
            else current.context,
            version=current.version + 1,
            updated_at=datetime.now(UTC),
        )

    def _append(self, tenant: str, event: LogEvent) -> LogEvent:
        stream = self._events.setdefault((tenant, event.transaction_id), [])
        stored = replace(event, tenant_id=tenant, sequence=len(stream) + 1)
        stream.append(stored)
        self._event_ids.add(stored.event_id)
        return stored

    async def register_participant(self, participant: Participant) -> None:
        tenant = write_tenant()
        self._participants[(tenant, participant.name)] = replace(participant, tenant_id=tenant)

    async def claim_delivery(self, participant: str, event_id: str) -> bool:
        key = (write_tenant(), participant, event_id)
        if key in self._deliveries:
            return False
        self._deliveries.add(key)
        return True

    async def save_snapshot(self, snapshot: Snapshot) -> None:
        tenant = write_tenant()
        bucket = self._snapshots.setdefault((tenant, snapshot.transaction_id, snapshot.kind), {})
        bucket[snapshot.sequence] = replace(snapshot, tenant_id=tenant)

    async def claim_due_deadlines(
        self, owners: Collection[str], now: datetime, lease: timedelta, limit: int = 100
    ) -> list[Deadline]:
        claimed: list[Deadline] = []
        for key, deadline in sorted(self._deadlines.items(), key=lambda kv: kv[1].due_at):
            if len(claimed) == limit:
                break
            if deadline.owner not in owners or deadline.due_at > now:
                continue
            if deadline.claimed_until is not None and deadline.claimed_until > now:
                continue
            self._deadlines[key] = replace(deadline, claimed_until=now + lease)
            claimed.append(deadline)
        return claimed

    # -- reads -------------------------------------------------------------------

    def _visible(self, tenant: str) -> bool:
        scope = scoped_tenant()
        return scope is None or scope == tenant

    async def get_transaction(self, transaction_id: str) -> Transaction | None:
        for (tenant, tid), transaction in self._transactions.items():
            if tid == transaction_id and self._visible(tenant):
                return copy.deepcopy(transaction)
        return None

    async def list_transactions(
        self,
        *,
        flow: str | None = None,
        coordination: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[Transaction]:
        found = [
            copy.deepcopy(t)
            for (tenant, _), t in self._transactions.items()
            if self._visible(tenant)
            and flow in (None, t.flow)
            and coordination in (None, t.coordination)
            and status in (None, t.status)
        ]
        return sorted(found, key=lambda t: t.started_at, reverse=True)[:limit]

    async def activities(self, transaction_id: str) -> list[Activity]:
        rows = [
            a
            for (tenant, tid), bucket in self._activities.items()
            if tid == transaction_id and self._visible(tenant)
            for a in bucket.values()
        ]
        return copy.deepcopy(rows)

    async def events(self, transaction_id: str, after_sequence: int = 0) -> list[LogEvent]:
        return [
            e
            for (tenant, tid), stream in sorted(self._events.items())
            if tid == transaction_id and self._visible(tenant)
            for e in stream
            if e.sequence > after_sequence
        ]

    async def latest_snapshot(
        self, transaction_id: str, kind: SnapshotKind = SnapshotKind.PROJECTION
    ) -> Snapshot | None:
        candidates = [
            s
            for (tenant, tid, k), bucket in self._snapshots.items()
            if tid == transaction_id and k == kind and self._visible(tenant)
            for s in bucket.values()
        ]
        return max(candidates, key=lambda s: s.sequence, default=None)

    async def participants(self) -> list[Participant]:
        return sorted(
            (p for (tenant, _), p in self._participants.items() if self._visible(tenant)),
            key=lambda p: p.name,
        )
