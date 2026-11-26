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
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sagaz.choreography._observe import DEFAULT_LISTENER_TIMEOUT, Listeners
from sagaz.choreography._transaction_hooks import Change, announce
from sagaz.choreography.events import COMPENSATE, COMPENSATED, AbstractEventBus, Event
from sagaz.core.storage.saga_log._model import LogWrite, ended_at
from sagaz.core.tenant import tenant_scope
from sagaz.core.types import SagaStatus

if TYPE_CHECKING:
    from sagaz.core.listeners import SagaListener
    from sagaz.core.storage.interfaces import SagaStorage
    from sagaz.core.storage.saga_log import SagaLogStore

from sagaz.choreography._status import (  # re-exported: their public home stays here
    COMPENSATING,
    COMPLETED,
    EXECUTING,
    FAILED,
    RECORD_NAME,
    ROLLED_BACK,
)

#: A rolled-back transaction's status before 2.6.0, when choreography named it apart
#: from orchestration (#572). Still read, never written.
OLD_ROLLED_BACK = "compensated"


def transaction_status(value: str) -> str:
    """*value*, with the pre-2.6.0 ``"compensated"`` read as ``"rolled_back"`` (#572).

    A transaction that was undone is ``rolled_back`` in both coordination styles;
    ``compensated`` is a step's (or a participant's) status.
    """
    return ROLLED_BACK if value == OLD_ROLLED_BACK else value


#: Reported (never stored) for an executing transaction with no recent event (#449).
STALLED = "stalled"
_SAGA_STATUS = {
    EXECUTING: SagaStatus.EXECUTING,
    COMPLETED: SagaStatus.COMPLETED,
    COMPENSATING: SagaStatus.COMPENSATING,
    ROLLED_BACK: SagaStatus.ROLLED_BACK,
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
        status = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        status.status = transaction_status(status.status)  # stored before 2.6.0
        return status

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

    def initiators(self) -> list[str]:
        """The participants that started the transaction: sources of uncaused events."""
        found: list[str] = []
        for seen in self.events:
            source = seen.get("source")
            first = seen.get("causation_id") is None and seen["event_type"] != COMPENSATE
            if first and source and source not in found:
                found.append(source)
        return found

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
        return FAILED if broken else ROLLED_BACK


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
    listeners:
        ``SagaListener`` instances told about whole transactions, once each (#563):
        ``on_saga_start`` when the tracker first records a transaction,
        ``on_saga_complete`` when it becomes ``completed``, ``on_saga_failed`` when
        it becomes ``rolled_back`` or ``failed``. The saga name is ``"choreography"``;
        ``ctx`` holds the correlation id, tenant, ``initiators``, ``participants``
        and ``status``. The participants' own steps are the engine's listeners.
        Run one tracker: two would each tell their listeners.
    listener_timeout:
        Seconds an async listener call may take (default 5) before it is
        cancelled, logged and skipped; ``None`` waits as long as it takes.
    """

    def __init__(
        self,
        bus: AbstractEventBus,
        storage: SagaStorage | None = None,
        completion_events: tuple[str, ...] | frozenset[str] = (),
        stall_after: timedelta | float | None = None,
        saga_log: SagaLogStore | None = None,
        listeners: Iterable[SagaListener] = (),
        listener_timeout: float | None = DEFAULT_LISTENER_TIMEOUT,
    ) -> None:
        self._bus = bus
        self._listeners = Listeners(listeners, listener_timeout)
        self.listeners: list[SagaListener] = self._listeners.items
        # Observations in flight per transaction: its lock is dropped when none is.
        self._in_flight: dict[str, int] = {}
        # Transactions whose start was announced: a redelivered first event is not.
        self._announced: OrderedDict[str, None] = OrderedDict()
        self._log = saga_log
        self._stall_after = _as_timedelta(stall_after)
        self._storage = storage
        self._completion_events = frozenset(completion_events)
        self._memory: dict[str, TransactionStatus] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        self._bus.subscribe("*", self.observe)

    async def stop(self) -> None:
        self._bus.unsubscribe("*", self.observe)

    async def _observe_log(self, event: Event) -> Change | None:
        """Unified log (ADR-041): the status is a projection of the log; keep the
        transaction row's status in step with it, and record each change as a
        ``TransactionStatusChanged`` lifecycle event, so that the log alone
        tells a choreographed transaction's status (ADR-013 exports it)."""
        from sagaz.core.storage.saga_log import ConcurrencyError, StatusChange

        log = self._log
        assert log is not None
        status = await status_from_log(log, event.saga_id or "", self._completion_events)
        current = await log.get_transaction(event.saga_id or "")
        if status is None or current is None:
            return None
        started = bool(status.events) and status.events[0]["event_id"] == event.event_id
        if current.status == status.status:
            return Change(started, status.status, status)
        ended = status.status in (COMPLETED, ROLLED_BACK, FAILED)
        change = StatusChange(
            current.transaction_id,
            status.status,
            current.version,
            # Events come from different services' clocks: never before it started (#653).
            ended_at=ended_at(current.started_at, event.created_at) if ended else None,
        )
        try:
            await log.write(LogWrite(status=change, events=[_transition(current, status, event)]))
        except ConcurrencyError:  # another tracker moved it (and tells its listeners)
            return Change(started, status.status, status)
        return Change(started, current.status, status)

    async def observe(self, event: Event) -> None:
        """Record *event* in its transaction (events without a correlation id are ignored)."""
        if not event.saga_id:
            return
        key = event.saga_id
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._in_flight[key] = self._in_flight.get(key, 0) + 1
        try:
            async with lock:
                with tenant_scope(event.tenant_id):
                    if self._log is not None:
                        change = await self._observe_log(event)
                    else:
                        change = await self._observe_stored(event)
        finally:
            self._in_flight[key] -= 1
            if not self._in_flight[key]:  # nobody else waits: the lock is not needed
                del self._in_flight[key]
                self._locks.pop(key, None)
        if change is not None and self.listeners:
            await announce(self._listeners, self._announced, change)

    async def _observe_stored(self, event: Event) -> Change:
        stored = await self._stored(event.saga_id or "")
        status = stored or TransactionStatus(event.saga_id or "", tenant_id=event.tenant_id)
        before = status.status if stored is not None else None
        status.apply(event, self._completion_events)
        await self._save(status)
        return Change(stored is None, before, status)

    async def status(self, correlation_id: str) -> TransactionStatus | None:
        """The status of *correlation_id* in the current tenant scope, if known."""
        if self._log is not None:
            status = await status_from_log(self._log, correlation_id, self._completion_events)
            return stalled_view(status, self._stall_after)
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


def _transition(current: Any, status: TransactionStatus, event: Event) -> Any:
    """The lifecycle event recording *current*'s move to *status*.

    It is caused by the last log event the projection folded: on an in-process
    bus, handlers may have logged later events before *event* is observed.
    """
    from sagaz.core.storage.saga_log import status_changed

    last = status.events[-1] if status.events else {"event_id": event.event_id}
    return status_changed(
        current.transaction_id,
        status.status,
        current.status,
        source=current.initiator,  # the row's owner, who may update it
        causation_id=last["event_id"],
        occurred_at=datetime.fromisoformat(last["at"]) if "at" in last else event.created_at,
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


async def status_from_log(
    log: SagaLogStore, correlation_id: str, completion_events: frozenset[str] | tuple[str, ...] = ()
) -> TransactionStatus | None:
    """A transaction's status projected from the unified saga log (ADR-041).

    Folds the transaction's log entries like the tracker folds bus events. If no
    completion event is configured here, a transaction whose row a tracker
    already marked ``completed`` is reported as completed.
    """
    from sagaz.choreography.state.unified import from_log_event

    entries = await log.events(correlation_id)
    if not entries:
        return None
    status = TransactionStatus(correlation_id, tenant_id=entries[0].tenant_id)
    for entry in entries:
        if entry.kind == "lifecycle":  # the tracker's own status changes
            continue
        status.apply(from_log_event(entry), frozenset(completion_events))
    transaction = await log.get_transaction(correlation_id)
    if transaction is not None and transaction.status == COMPLETED and status.status == EXECUTING:
        status.status = COMPLETED
    return status


async def load_status(storage: SagaStorage, correlation_id: str) -> TransactionStatus | None:
    """Read a transaction's status from *storage* (current tenant scope)."""
    record = await storage.load_saga_state(correlation_id)
    if not record or record.get("saga_name") != RECORD_NAME:
        return None
    return TransactionStatus.from_dict(record.get("context") or {})
