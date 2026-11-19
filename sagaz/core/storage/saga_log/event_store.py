"""The ADR-033 event store as a view on the unified saga log (ADR-041 phase 2, #465).

An orchestrated saga with ``storage_layout = "unified"`` records through this
adapter. Each lifecycle event becomes **one** atomic ``LogWrite``:

- the event itself, appended to ``saga_log_event`` (kind ``lifecycle``);
- the step's ``saga_activity`` (status, attempt, region, result, error,
  duration) for step events;
- the transaction's ``saga_transaction`` row: inserted on ``SagaStarted``, and
  moved through ``executing`` → ``compensating`` → ``completed`` /
  ``rolled_back`` / ``failed`` with version-checked status changes.

So the current state and the log are written together and cannot diverge.
Reading returns the lifecycle events as ``SagaEvent``s, which is what the
projection, the recorder and ``sagaz event-log`` consume.
"""

from __future__ import annotations

from typing import Any

from sagaz.core.events import (
    CompensationStarted,
    SagaCompleted,
    SagaEvent,
    SagaFailed,
    SagaRolledBack,
    SagaStarted,
    StepCompensated,
    StepCompensationFailed,
    StepExecuted,
    StepFailed,
)
from sagaz.core.storage.event_store._base import SagaEventStore, SagaSnapshot
from sagaz.core.storage.saga_log._base import SagaLogStore
from sagaz.core.storage.saga_log._model import (
    ORCHESTRATOR,
    Activity,
    Coordination,
    EventKind,
    LogEvent,
    LogWrite,
    Snapshot,
    SnapshotKind,
    StatusChange,
    Transaction,
)

#: Transaction status after each saga-level event.
_STATUS: dict[type[SagaEvent], str] = {
    CompensationStarted: "compensating",
    SagaCompleted: "completed",
    SagaRolledBack: "rolled_back",
    SagaFailed: "failed",
}
#: Activity status after each step-level event.
_ACTIVITY: dict[type[SagaEvent], str] = {
    StepExecuted: "completed",
    StepFailed: "failed",
    StepCompensated: "compensated",
    StepCompensationFailed: "compensation_failed",
}


def _to_log_event(event: SagaEvent, participant: str) -> LogEvent:
    return LogEvent(
        transaction_id=event.saga_id,
        event_type=event.event_type,
        kind=EventKind.LIFECYCLE,
        event_id=event.event_id,
        source=participant,
        payload={**event.payload, "saga_name": event.saga_name, "metadata": event.metadata},
        occurred_at=event.occurred_at,
        event_version=event.event_version,
        tenant_id=event.tenant_id,
    )


def _to_saga_event(entry: LogEvent) -> SagaEvent:
    payload = dict(entry.payload)
    return SagaEvent.from_dict(
        {
            "event_type": entry.event_type,
            "saga_id": entry.transaction_id,
            "event_id": entry.event_id,
            "occurred_at": entry.occurred_at.isoformat(),
            "sequence": entry.sequence,
            "saga_name": payload.pop("saga_name", ""),
            "tenant_id": entry.tenant_id,
            "event_version": entry.event_version,
            "metadata": payload.pop("metadata", None) or {},
            "payload": payload,
        }
    )


class SagaLogEventStore(SagaEventStore):
    """Records and reads orchestrated saga events on a :class:`SagaLogStore`.

    Args:
        log: The unified saga log.
        participant: Who runs the steps (``Activity.participant`` and the
            events' ``source``): the service name. Defaults to ``"orchestrator"``.
    """

    def __init__(self, log: SagaLogStore, participant: str = ORCHESTRATOR) -> None:
        self.log = log
        self.participant = participant
        # The context a transaction accumulates (initial context + step
        # results), written to saga_transaction when the saga ends.
        self._contexts: dict[str, dict[str, Any]] = {}

    async def append(self, event: SagaEvent) -> SagaEvent:
        batch = LogWrite(events=[_to_log_event(event, self.participant)])
        await self._add_state(batch, event)
        (stored,) = await self.log.write(batch)
        return _to_saga_event(stored)

    async def _add_state(self, batch: LogWrite, event: SagaEvent) -> None:
        tid = event.saga_id
        if isinstance(event, SagaStarted):
            await self._start(batch, event)
        elif type(event) in _ACTIVITY:
            batch.activities.append(self._activity(event))
            if isinstance(event, StepExecuted) and isinstance(event.step_result, dict):
                self._contexts.setdefault(tid, {}).update(event.step_result)
        elif type(event) in _STATUS:
            await self._change_status(batch, event, _STATUS[type(event)])

    async def _start(self, batch: LogWrite, event: SagaStarted) -> None:
        self._contexts[event.saga_id] = dict(event.initial_context)
        existing = await self.log.get_transaction(event.saga_id)
        if existing is None:
            batch.transaction = Transaction(
                event.saga_id,
                event.saga_name or "unknown",
                Coordination.ORCHESTRATED,
                initiator=self.participant,
                started_at=event.occurred_at,
                context=dict(event.initial_context),
            )
            return
        # A re-run with the same saga id starts the transaction again.
        batch.status = StatusChange(
            event.saga_id, "executing", existing.version, context=dict(event.initial_context)
        )

    async def _change_status(self, batch: LogWrite, event: SagaEvent, status: str) -> None:
        current = await self.log.get_transaction(event.saga_id)
        if current is None:  # its start was not recorded (e.g. the log was down)
            batch.transaction = Transaction(
                event.saga_id,
                event.saga_name or "unknown",
                Coordination.ORCHESTRATED,
                initiator=self.participant,
                started_at=event.occurred_at,
            )
            version = 1
        else:
            version = current.version
        ended = status in ("completed", "rolled_back", "failed")
        batch.status = StatusChange(
            event.saga_id,
            status,
            version,
            ended_at=event.occurred_at if ended else None,
            context=self._contexts.pop(event.saga_id, None) if ended else None,
        )

    def _activity(self, event: SagaEvent) -> Activity:
        payload = event.payload
        failed = isinstance(event, (StepFailed, StepCompensationFailed))
        executed = isinstance(event, StepExecuted)
        return Activity(
            event.saga_id,
            str(payload["step_name"]),
            self.participant,
            str(payload["step_name"]),
            status=_ACTIVITY[type(event)],
            attempt=int(event.metadata.get("attempt") or 1),
            region=event.metadata.get("region"),
            result=payload.get("step_result") if executed else None,
            error=f"{payload['error_type']}: {payload['error_message']}" if failed else None,
            ended_at=event.occurred_at,
            duration_ms=payload.get("duration_ms") if executed else None,
        )

    # -- reads (the ADR-033 view) ---------------------------------------------------

    async def load_stream(self, saga_id: str) -> list[SagaEvent]:
        return await self.load_stream_after(saga_id, 0)

    async def load_stream_after(self, saga_id: str, after_sequence: int) -> list[SagaEvent]:
        entries = await self.log.events(saga_id, after_sequence)
        return [_to_saga_event(e) for e in entries if e.kind == EventKind.LIFECYCLE]

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        await self.log.save_snapshot(
            Snapshot(
                snapshot.saga_id,
                snapshot.sequence,
                snapshot.state,
                SnapshotKind.PROJECTION,
                snapshot.tenant_id,
                snapshot.created_at,
            )
        )

    async def load_latest_snapshot(self, saga_id: str) -> SagaSnapshot | None:
        snapshot = await self.log.latest_snapshot(saga_id, SnapshotKind.PROJECTION)
        if snapshot is None:
            return None
        return SagaSnapshot(
            snapshot.transaction_id,
            snapshot.sequence,
            snapshot.state,
            snapshot.tenant_id,
            snapshot.created_at,
        )

    async def close(self) -> None:
        await self.log.close()
