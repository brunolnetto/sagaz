"""Choreography participant state on the unified saga log (ADR-041 phase 3, #466).

Replaces the ``choreography_*`` tables with the unified ones:

- a completed action is a ``saga_activity`` of the participant (its triggering
  event kept as the activity's ``result``, for compensation);
- the end of a participant's part of a transaction is its ``__transaction__``
  marker activity (``completed`` or ``compensated``: the #446 tombstone);
- handled deliveries are ``saga_delivery`` rows, deadlines ``saga_deadline`` rows.

And it makes publishing atomic: :meth:`publish` writes the published event to
the log, the triggering action it completes, the transaction (for the first
event) and an outbox message, in **one** database transaction. A
``ChoreographyRelay`` then delivers the outbox to the bus, so a crash can no
longer lose the state change or the event.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from datetime import datetime, timedelta

from sagaz.choreography.events import COMPENSATE, COMPENSATED, Event
from sagaz.choreography.state._base import Deadline, ParticipantState
from sagaz.core.storage.saga_log import (
    TRANSACTION_MARKER,
    Activity,
    Coordination,
    EventKind,
    LogEvent,
    LogWrite,
    OutboxMessage,
    SagaLogStore,
    Transaction,
)
from sagaz.core.storage.saga_log import Deadline as LogDeadline
from sagaz.core.tenant import tenant_scope

COMPLETED, COMPENSATED_STATUS = "completed", "compensated"


def _kind(event_type: str) -> EventKind:
    if event_type == COMPENSATE:
        return EventKind.COMPENSATE
    if event_type == COMPENSATED:
        return EventKind.COMPENSATED
    return EventKind.BUSINESS


def to_log_event(event: Event) -> LogEvent:
    """A choreography event as a saga log entry."""
    return LogEvent(
        transaction_id=event.saga_id or "",
        event_type=event.event_type,
        kind=_kind(event.event_type),
        event_id=event.event_id,
        source=event.source,
        causation_id=event.causation_id,
        payload=dict(event.data),
        occurred_at=event.created_at,
        tenant_id=event.tenant_id,
    )


def from_log_event(entry: LogEvent) -> Event:
    """A saga log entry back as a choreography event."""
    return Event(
        entry.event_type,
        dict(entry.payload),
        saga_id=entry.transaction_id,
        event_id=entry.event_id,
        created_at=entry.occurred_at,
        tenant_id=entry.tenant_id,
        causation_id=entry.causation_id,
        source=entry.source,
    )


def _action(participant: str, event: Event) -> Activity:
    return Activity(
        event.saga_id or "",
        f"{participant}:{event.event_id}",
        participant,
        event.event_type,
        status=COMPLETED,
        triggered_by=event.event_id,
        result=event.to_dict(),
        started_at=event.created_at,
    )


def _marker(participant: str, transaction_id: str, status: str) -> Activity:
    return Activity(
        transaction_id,
        f"{participant}:{TRANSACTION_MARKER}",
        participant,
        TRANSACTION_MARKER,
        status=status,
    )


class UnifiedParticipantState(ParticipantState):
    """Participant state, and atomic publishing, on a :class:`SagaLogStore`."""

    def __init__(self, log: SagaLogStore) -> None:
        self.log = log

    async def record_action(self, participant: str, event: Event) -> None:
        if event.saga_id:
            await self.log.write(
                LogWrite(activities=[_action(participant, event)], guard=participant)
            )

    async def finish(
        self, participant: str, correlation_id: str, *, compensated: bool
    ) -> list[Event]:
        status = COMPENSATED_STATUS if compensated else COMPLETED
        # Only the first finish of a participant's part returns its actions, so
        # two concurrent compensation requests never undo twice.
        first = await self.log.claim_delivery(participant, f"finish:{correlation_id}")
        actions = await self._actions(participant, correlation_id) if first else []
        await self.log.write(
            LogWrite(
                activities=[_marker(participant, correlation_id, status)],
                clear_deadlines=[(correlation_id, participant)],
            )
        )
        return actions

    async def _actions(self, participant: str, correlation_id: str) -> list[Event]:
        rows = [
            a
            for a in await self.log.activities(correlation_id)
            if a.participant == participant
            and a.name != TRANSACTION_MARKER
            and a.status == COMPLETED
            and isinstance(a.result, dict)
        ]
        rows.sort(key=lambda a: (a.started_at is None, a.started_at or datetime.min))
        return [Event.from_dict(a.result) for a in rows if a.result]

    async def was_compensated(self, participant: str, correlation_id: str) -> bool:
        return any(
            a.participant == participant
            and a.name == TRANSACTION_MARKER
            and a.status == COMPENSATED_STATUS
            for a in await self.log.activities(correlation_id)
        )

    async def first_delivery(self, participant: str, event_id: str) -> bool:
        return await self.log.claim_delivery(participant, event_id)

    async def set_deadline(self, participant: str, correlation_id: str, due_at: datetime) -> None:
        await self.log.write(
            LogWrite(deadline=LogDeadline(correlation_id, participant, due_at), guard=participant)
        )

    async def claim_due_deadlines(
        self, participants: Collection[str], now: datetime, lease: timedelta, limit: int = 100
    ) -> list[Deadline]:
        due = await self.log.claim_due_deadlines(participants, now, lease, limit)
        return [Deadline(d.tenant_id, d.owner, d.transaction_id, d.due_at) for d in due]

    async def publish(
        self,
        participant: str,
        event: Event,
        send: Callable[[Event], Awaitable[None]],
        *,
        cause: Event | None = None,
        remember: bool = False,
        begin: bool = False,
    ) -> None:
        if not event.saga_id:  # no transaction to record it in
            await send(event)
            return
        batch = LogWrite(
            events=[to_log_event(event)],
            publish=[
                OutboxMessage(
                    event.saga_id,
                    event.event_type,
                    event.to_dict(),
                    log_event_id=event.event_id,
                    partition_key=event.saga_id,
                    aggregate_type="choreography",
                )
            ],
            guard=participant,
        )
        if remember and cause is not None and cause.saga_id:
            batch.activities.append(_action(participant, cause))
        if begin:
            batch.transaction = Transaction(
                event.saga_id,
                event.event_type,
                Coordination.CHOREOGRAPHED,
                initiator=participant,
                started_at=event.created_at,
            )
        with tenant_scope(event.tenant_id):
            await self.log.write(batch)
