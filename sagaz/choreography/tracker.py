"""Status of choreographed transactions, projected from their events (ADR-029, #56).

A :class:`ChoreographyTracker` listens to every event on the bus and keeps, per
correlation id, what happened: the events seen, the participants that emitted
them, a failure and the compensations reported. Because it only reads the event
stream, it needs no cooperation from the participants and there is a single
writer: run one tracker (for example next to ``sagaz choreography status``).

With a saga storage, each transaction is saved as a saga record named
``choreography`` in its tenant's scope, so any process can read it.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.choreography.events import COMPENSATE, COMPENSATED, AbstractEventBus, Event
from sagaz.core.tenant import tenant_scope
from sagaz.core.types import SagaStatus

#: Saga name of the records the tracker writes.
RECORD_NAME = "choreography"

EXECUTING, COMPLETED, COMPENSATING, COMPENSATED_STATUS, FAILED = (
    "executing",
    "completed",
    "compensating",
    "compensated",
    "failed",
)
#: Reported (never stored) for an executing transaction with no recent event (#449).
STALLED = "stalled"
_SAGA_STATUS = {
    EXECUTING: SagaStatus.EXECUTING,
    COMPLETED: SagaStatus.COMPLETED,
    COMPENSATING: SagaStatus.COMPENSATING,
    COMPENSATED_STATUS: SagaStatus.ROLLED_BACK,
    FAILED: SagaStatus.FAILED,
}


@dataclass
class TransactionStatus:
    """What is known about one choreographed transaction."""

    correlation_id: str
    tenant_id: str = "default"
    status: str = EXECUTING
    events: list[dict[str, Any]] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)
    failure: dict[str, Any] | None = None
    compensated_by: dict[str, dict[str, Any]] = field(default_factory=dict)
    completion_seen: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransactionStatus:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def apply(self, event: Event, completion_events: frozenset[str]) -> None:
        """Fold one event into the status."""
        self.events.append(
            {
                "event_type": event.event_type,
                "event_id": event.event_id,
                "source": event.source,
                "at": event.created_at.isoformat(),
                "causation_id": event.causation_id,
            }
        )
        self._note_participant(event)
        if event.event_type == COMPENSATE:
            self.failure = self.failure or dict(event.data)
        elif event.event_type == COMPENSATED:
            participant = event.data.get("participant") or event.source or "?"
            self.compensated_by[participant] = dict(event.data)
        elif event.event_type in completion_events:
            self.completion_seen = True
        self.status = self._derive()

    def _note_participant(self, event: Event) -> None:
        """Participants are the sources of business events (not compensation reports)."""
        business = event.event_type not in (COMPENSATE, COMPENSATED)
        if business and event.source and event.source not in self.participants:
            self.participants.append(event.source)

    def _derive(self) -> str:
        """Status from the facts gathered so far, whatever order events arrived in."""
        if self.failure is None:
            return COMPLETED if self.completion_seen else EXECUTING
        failed_participant = self.failure.get("participant")
        expected = {p for p in self.participants if p != failed_participant}
        if not expected <= set(self.compensated_by):
            return COMPENSATING
        broken = any(report.get("failed") for report in self.compensated_by.values())
        return FAILED if broken else COMPENSATED_STATUS


class ChoreographyTracker:
    """Projects every event on *bus* into per-transaction status.

    Parameters
    ----------
    bus:
        The bus to observe (subscribes to ``"*"`` on :meth:`start`).
    storage:
        Optional saga storage; without it the status is kept in memory.
    completion_events:
        Event types that complete a transaction successfully.
    stall_after:
        Report an executing transaction as ``"stalled"`` when its last event is
        older than this (a ``timedelta`` or seconds). The tracker only reports
        it; deadlines (``begin(..., deadline=...)``) compensate.
    """

    def __init__(
        self,
        bus: AbstractEventBus,
        storage: Any | None = None,
        completion_events: tuple[str, ...] | frozenset[str] = (),
        stall_after: timedelta | float | None = None,
    ) -> None:
        self._bus = bus
        self._stall_after = _as_timedelta(stall_after)
        self._storage = storage
        self._completion_events = frozenset(completion_events)
        self._memory: dict[str, TransactionStatus] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        self._bus.subscribe("*", self.observe)

    async def stop(self) -> None:
        self._bus.unsubscribe("*", self.observe)

    async def observe(self, event: Event) -> None:
        """Record *event* in its transaction (events without a correlation id are ignored)."""
        if not event.saga_id:
            return
        lock = self._locks.setdefault(event.saga_id, asyncio.Lock())
        async with lock:
            with tenant_scope(event.tenant_id):
                status = await self._stored(event.saga_id) or TransactionStatus(
                    event.saga_id, tenant_id=event.tenant_id
                )
                status.apply(event, self._completion_events)
                await self._save(status)

    async def status(self, correlation_id: str) -> TransactionStatus | None:
        """The status of *correlation_id* in the current tenant scope, if known."""
        if self._storage is None:
            status = self._memory.get(correlation_id)
        else:
            status = await load_status(self._storage, correlation_id)
        return stalled_view(status, self._stall_after)

    async def _stored(self, correlation_id: str) -> TransactionStatus | None:
        if self._storage is None:
            return self._memory.get(correlation_id)
        return await load_status(self._storage, correlation_id)

    async def _save(self, status: TransactionStatus) -> None:
        if self._storage is None:
            self._memory[status.correlation_id] = status
            return
        await self._storage.save_saga_state(
            status.correlation_id,
            RECORD_NAME,
            _SAGA_STATUS[status.status],
            [],
            status.to_dict(),
        )


def _as_timedelta(value: timedelta | float | None) -> timedelta | None:
    if value is None or isinstance(value, timedelta):
        return value
    return timedelta(seconds=value)


def stalled_view(
    status: TransactionStatus | None,
    stall_after: timedelta | float | None,
    now: datetime | None = None,
) -> TransactionStatus | None:
    """*status*, reported as ``"stalled"`` if it is executing with no event for *stall_after*."""
    limit = _as_timedelta(stall_after)
    if status is None or limit is None or status.status != EXECUTING or not status.events:
        return status
    last = max(datetime.fromisoformat(e["at"]) for e in status.events)
    if (now or datetime.now(UTC)) - last <= limit:
        return status
    return replace(status, status=STALLED)


async def load_status(storage: Any, correlation_id: str) -> TransactionStatus | None:
    """Read a transaction's status from *storage* (current tenant scope)."""
    record = await storage.load_saga_state(correlation_id)
    if not record or record.get("saga_name") != RECORD_NAME:
        return None
    return TransactionStatus.from_dict(record.get("context") or {})
