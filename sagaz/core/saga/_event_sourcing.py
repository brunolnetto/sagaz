"""Event recording for the imperative ``sagaz.core.saga.Saga`` (ADR-033, #450).

Records the same events as the declarative engine, in sequential and DAG
mode. A saga records when it is given an ``event_store``; without one, every
hook is a no-op.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

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
    json_safe,
)

if TYPE_CHECKING:
    from sagaz.core.context import SagaContext
    from sagaz.core.storage.event_store import SagaEventRecorder, SagaEventStore
    from sagaz.core.storage.saga_log import SagaLogStore

logger = logging.getLogger("sagaz.core.saga")


def _root_cause(error: BaseException) -> BaseException:
    """The user's exception behind sagaz's step wrappers (``raise ... from``)."""
    return error.__cause__ or error


class _SagaEventSourcingMixin:
    """Hooks the imperative engine calls at each lifecycle transition."""

    # Attributes provided by the concrete Saga host.
    name: str
    saga_id: str
    context: SagaContext
    _event_store: SagaEventStore | None
    _snapshot_threshold: int

    def _init_event_sourcing(
        self,
        event_store: SagaEventStore | str | None,
        snapshot_threshold: int,
        saga_log: SagaLogStore | str | None = None,
        participant: str | None = None,
    ) -> None:
        if saga_log is not None:  # the unified saga log (ADR-041)
            from sagaz.core.storage.event_store.recorder import _unified_store

            event_store = _unified_store(saga_log, participant)
        if isinstance(event_store, str):
            from sagaz.core.storage.event_store.recorder import _as_store

            event_store = _as_store(event_store)
        self._event_store = event_store
        self._snapshot_threshold = snapshot_threshold
        self._recorder: SagaEventRecorder | None = None
        self._es_failure: tuple[str, str, str] | None = None
        self._es_compensation_failed = False
        self._es_finished = False
        self._es_started = time.monotonic()

    async def _es_open(self) -> None:
        """Start recording a run (called on entering EXECUTING)."""
        if self._event_store is None:
            return
        from sagaz.core.storage.event_store import SagaEventRecorder

        self._es_failure, self._es_compensation_failed, self._es_finished = None, False, False
        self._es_started = time.monotonic()
        self._recorder = SagaEventRecorder(
            self._event_store, self.saga_id, self.name, self._snapshot_threshold
        )
        await self._recorder.open()
        await self._es_record(SagaStarted, initial_context=json_safe(self.context.data))

    async def _es_record(self, event_type: type[SagaEvent], **fields: Any) -> None:
        if self._recorder is not None:
            await self._recorder.record(event_type(self.saga_id, **fields))

    def _es_elapsed_ms(self) -> float:
        return round((time.monotonic() - self._es_started) * 1000, 3)

    async def _es_step_executed(
        self, step_name: str, result: Any, duration_ms: float, attempt: int = 1
    ) -> None:
        await self._es_record(
            StepExecuted,
            step_name=step_name,
            step_result=json_safe(result),
            duration_ms=round(duration_ms, 3),
            metadata={"attempt": attempt},
        )

    async def _es_step_failed(self, step_name: str, error: BaseException, attempt: int = 1) -> None:
        cause = _root_cause(error)
        failure = (step_name, type(cause).__name__, str(cause) or type(cause).__name__)
        self._es_failure = self._es_failure or failure
        await self._es_record(
            StepFailed,
            step_name=step_name,
            error_type=failure[1],
            error_message=failure[2],
            metadata={"attempt": attempt},
        )

    async def _es_compensation_started(self) -> None:
        step, error_type, message = self._es_failure or ("", "", "")
        await self._es_record(
            CompensationStarted, failed_step=step, error_type=error_type, error_message=message
        )

    async def _es_step_compensated(self, step_name: str) -> None:
        await self._es_record(StepCompensated, step_name=step_name)

    async def _es_step_compensation_failed(self, step_name: str, error: BaseException) -> None:
        self._es_compensation_failed = True
        cause = _root_cause(error)
        await self._es_record(
            StepCompensationFailed,
            step_name=step_name,
            error_type=type(cause).__name__,
            error_message=str(cause) or type(cause).__name__,
        )

    async def _es_finish(self, outcome: str) -> None:
        """Record the run's one terminal event.

        *outcome* is ``"completed"`` or how the run ended otherwise. Like the
        declarative engine, a failed run is ``SagaFailed`` only when a
        compensation failed; otherwise every completed step was undone (maybe
        none), which is ``SagaRolledBack`` whatever state the machine reached.
        """
        if self._recorder is None or self._es_finished:
            return
        self._es_finished = True
        duration_ms = self._es_elapsed_ms()
        if outcome == "completed":
            await self._es_record(SagaCompleted, duration_ms=duration_ms)
        elif not self._es_compensation_failed:
            await self._es_record(SagaRolledBack, duration_ms=duration_ms)
        else:
            _step, error_type, message = self._es_failure or ("", "", "")
            reason = f"{error_type}: {message}" if error_type else "compensation failed"
            await self._es_record(SagaFailed, error_message=reason, duration_ms=duration_ms)
