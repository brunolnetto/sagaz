"""Records of the unified saga log (ADR-041)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


#: Participant recorded for the steps of an orchestrated saga whose engine did
#: not name one (and for sagas migrated from the old layout).
ORCHESTRATOR = "orchestrator"

#: ``Activity.name`` of a participant's per-transaction marker: ``completed``
#: when its part of the transaction ended, ``compensated`` once it compensated
#: (the tombstone of #446).
TRANSACTION_MARKER = "__transaction__"


class Coordination(StrEnum):
    ORCHESTRATED = "orchestrated"
    CHOREOGRAPHED = "choreographed"


class EventKind(StrEnum):
    LIFECYCLE = "lifecycle"  # orchestrated saga lifecycle (ADR-033 events)
    BUSINESS = "business"  # a choreography business event
    COMPENSATE = "compensate"  # choreography.compensate
    COMPENSATED = "compensated"  # choreography.compensated


class SnapshotKind(StrEnum):
    PROJECTION = "projection"  # ADR-033 snapshot + tail
    REPLAY = "replay"  # ADR-024 replay / time travel


class ConcurrencyError(RuntimeError):
    """A transaction changed since it was read (``expected_version`` mismatch)."""


#: The lifecycle event recording a choreographed transaction's status change
#: (payload ``{"status": ..., "previous": ...}``): written by the choreography
#: tracker, so the log alone tells every transaction's status.
STATUS_CHANGED = "TransactionStatusChanged"


@dataclass
class Transaction:
    """One distributed transaction: an orchestrated saga or a choreographed flow."""

    transaction_id: str
    flow: str
    coordination: Coordination
    status: str = "executing"
    initiator: str | None = None
    tenant_id: str = "default"
    started_at: datetime = field(default_factory=_now)
    ended_at: datetime | None = None
    context: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    updated_at: datetime = field(default_factory=_now)


@dataclass
class Activity:
    """One unit of work by one participant: a step, or a handled event."""

    transaction_id: str
    activity_id: str
    participant: str
    name: str
    status: str = "executing"
    attempt: int = 1
    region: str | None = None
    triggered_by: str | None = None
    result: Any = None
    error: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: float | None = None
    tenant_id: str = "default"


@dataclass(frozen=True)
class LogEvent:
    """An entry of a transaction's append-only log; ``sequence`` is set on write."""

    transaction_id: str
    event_type: str
    kind: EventKind
    event_id: str = field(default_factory=_new_id)
    source: str | None = None
    causation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=_now)
    sequence: int = 0
    event_version: int = 1
    tenant_id: str = "default"


@dataclass(frozen=True)
class Snapshot:
    transaction_id: str
    sequence: int
    state: dict[str, Any]
    kind: SnapshotKind = SnapshotKind.PROJECTION
    tenant_id: str = "default"
    created_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class Participant:
    """A service taking part in sagas, and the database role it writes as."""

    name: str
    region: str | None = None
    owner: str | None = None
    db_role: str | None = None
    tenant_id: str = "default"


@dataclass(frozen=True)
class Deadline:
    transaction_id: str
    owner: str
    due_at: datetime
    claimed_until: datetime | None = None
    tenant_id: str = "default"


def ended_at(
    started_at: datetime, observed: datetime, duration_ms: float | None = None
) -> datetime:
    """When a transaction that started at *started_at* ended: never before it started (#653).

    *observed* is the wall-clock time of the event that ended it. Wall clocks are not
    monotonic (NTP and hypervisors step them back), and a choreographed transaction's
    events come from different services' clocks, so *observed* can be earlier than
    *started_at*. Only then is *observed* replaced: the transaction ends ``duration_ms``
    after it started, the duration its saga measured on a monotonic clock, or at
    ``started_at`` without one. An end observed at or after the start is kept as it is,
    so the log and the event stream agree on it.
    """
    if observed >= started_at:
        return observed
    return started_at + timedelta(milliseconds=max(duration_ms or 0.0, 0.0))


@dataclass(frozen=True)
class StatusChange:
    """Move a transaction to *status*, if it is still at *expected_version*."""

    transaction_id: str
    status: str
    expected_version: int
    ended_at: datetime | None = None
    context: dict[str, Any] | None = None


@dataclass(frozen=True)
class OutboxMessage:
    """A message to publish once the write commits (transactional outbox).

    The store inserts it into the outbox table of the same database, in the same
    transaction as the rest of the write; an outbox relay publishes it later.
    """

    transaction_id: str
    event_type: str
    payload: dict[str, Any]
    log_event_id: str | None = None
    partition_key: str | None = None
    aggregate_type: str = "saga"


@dataclass
class LogWrite:
    """Everything one participant writes at one point, applied atomically.

    In order: insert the transaction if new, apply the status change, append the
    events (numbered per transaction), upsert the activities, set and clear
    deadlines, and queue the outbox messages.

    With ``guard`` set to a participant, that participant's activities and
    deadline are dropped when it already ended its part of the transaction (its
    ``TRANSACTION_MARKER`` activity exists): late actions are not recorded (#446).
    A marker that says ``compensated`` stays ``compensated``.
    """

    transaction: Transaction | None = None
    status: StatusChange | None = None
    events: list[LogEvent] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)
    deadline: Deadline | None = None
    clear_deadlines: list[tuple[str, str]] = field(default_factory=list)  # (transaction, owner)
    publish: list[OutboxMessage] = field(default_factory=list)
    guard: str | None = None

    def guarded_transactions(self) -> set[str]:
        """Transactions whose ``guard`` participant rows this write touches."""
        if self.guard is None:
            return set()
        ids = {a.transaction_id for a in self.activities if a.participant == self.guard}
        if self.deadline is not None and self.deadline.owner == self.guard:
            ids.add(self.deadline.transaction_id)
        return ids

    def drop_guarded(self, ended: set[str]) -> None:
        """Drop the guard participant's non-marker activities and deadline in *ended*."""
        self.activities = [
            a
            for a in self.activities
            if not (
                a.participant == self.guard
                and a.transaction_id in ended
                and a.name != TRANSACTION_MARKER
            )
        ]
        if self.deadline is not None and self.deadline.transaction_id in ended:
            self.deadline = None


@dataclass(frozen=True)
class ExportedEvent:
    """A committed log event with its transaction's coordination and flow."""

    event: LogEvent
    coordination: str | None = None
    flow: str | None = None


@dataclass(frozen=True)
class ExportBatch:
    """Committed events in log order, and the position to resume after them.

    ``position`` is opaque and backend-specific; it is ``None`` only when the
    batch is empty and the reader had no position yet.
    """

    events: list[ExportedEvent]
    position: str | None

    def __bool__(self) -> bool:
        return bool(self.events)


def status_changed(
    transaction_id: str,
    status: str,
    previous: str,
    *,
    source: str | None,
    occurred_at: datetime,
    causation_id: str | None = None,
) -> LogEvent:
    """The :data:`STATUS_CHANGED` lifecycle event of a choreographed transaction."""
    return LogEvent(
        transaction_id,
        STATUS_CHANGED,
        EventKind.LIFECYCLE,
        source=source,
        causation_id=causation_id,
        payload={"status": status, "previous": previous},
        occurred_at=occurred_at,
    )
