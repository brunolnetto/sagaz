"""Event recording for the declarative saga engine (ADR-033, #57)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sagaz.core.events import SagaEvent, SagaFailed, SagaRolledBack, StepFailed

if TYPE_CHECKING:
    from sagaz.core.decorators import Saga
    from sagaz.core.storage.event_store import SagaEventRecorder


class _EventSourcingMixin:
    """Records a run's events when its saga is event-sourced; a no-op otherwise."""

    saga: Saga
    _needs_forward_recovery: str | None

    def _init_event_sourcing(self) -> None:
        # Set by run() for event-sourced sagas.
        self._recorder: SagaEventRecorder | None = None
        self._failed_step: str | None = None
        self._compensation_failed = False
        self._started = time.monotonic()

    async def _open_recorder(self, saga_name: str) -> None:
        """Start recording events if the saga is event-sourced (ADR-033)."""
        from sagaz.core.storage.event_store.recorder import (
            SagaEventRecorder,
            event_sourcing_settings,
        )

        settings = event_sourcing_settings(self.saga)
        if settings is None:
            return
        store, threshold = settings
        self._recorder = SagaEventRecorder(store, self.saga._saga_id, saga_name, threshold)
        await self._recorder.open()

    async def _record(self, event_type: type[SagaEvent], **fields: Any) -> None:
        if self._recorder is None:
            return
        step = self.saga._step_registry.get(fields.get("step_name", ""))
        if step is not None and step.region is not None:
            fields["metadata"] = {"region": step.region}  # where the step ran (ADR-034)
        await self._recorder.record(event_type(self.saga._saga_id, **fields))

    async def _record_outcome(self, error: Exception) -> None:
        # A saga that stopped to be recovered forward is recorded as failed, and a partially
        # committed one as rolled back: the event stream has no event of its own for them.
        if self._compensation_failed or self._needs_forward_recovery is not None:
            await self._record(
                SagaFailed,
                error_message=f"{type(error).__name__}: {error}",
                duration_ms=self._elapsed_ms(),
            )
        else:
            await self._record(SagaRolledBack, duration_ms=self._elapsed_ms())

    def _elapsed_ms(self, since: float | None = None) -> float:
        return round((time.monotonic() - (since or self._started)) * 1000, 3)

    async def _record_step_failure(
        self, step_id: str, error: BaseException, message: str | None = None
    ) -> None:
        self._failed_step = self._failed_step or step_id
        await self._record(
            StepFailed,
            step_name=step_id,
            error_type=type(error).__name__,
            error_message=message or str(error),
        )
