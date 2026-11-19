"""Records of the unified saga log (ADR-041)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
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


@dataclass(frozen=True)
class StatusChange:
    """Move a transaction to *status*, if it is still at *expected_version*."""

    transaction_id: str
    status: str
    expected_version: int
    ended_at: datetime | None = None
    context: dict[str, Any] | None = None


@dataclass
class LogWrite:
    """Everything one participant writes at one point, applied atomically.

    In order: insert the transaction if new, apply the status change, append the
    events (numbered per transaction), upsert the activities, set and clear
    deadlines.
    """

    transaction: Transaction | None = None
    status: StatusChange | None = None
    events: list[LogEvent] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)
    deadline: Deadline | None = None
    clear_deadlines: list[tuple[str, str]] = field(default_factory=list)  # (transaction, owner)
