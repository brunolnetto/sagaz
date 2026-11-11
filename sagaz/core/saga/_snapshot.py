"""Saga snapshot/replay and status mixin for the imperative Saga class."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from asyncio import Lock

    from sagaz.core.execution.state_machine import SagaStateMachine
    from sagaz.core.replay import ReplayConfig, SagaSnapshot, SnapshotStrategy
    from sagaz.core.saga._step import SagaStep
    from sagaz.core.storage.interfaces.snapshot import SnapshotStorage

from statemachine.exceptions import TransitionNotAllowed

from sagaz.core.context import SagaContext
from sagaz.core.exceptions import SagaExecutionError
from sagaz.core.types import SagaResult, SagaStatus

logger = logging.getLogger(__name__)


class _SagaSnapshotMixin:
    """Mixin adding status reporting and snapshot/replay support to the Saga class."""

    # Attributes provided by the concrete Saga host.
    name: str
    version: str
    saga_id: str
    status: SagaStatus
    steps: list[SagaStep]
    completed_steps: list[SagaStep]
    context: SagaContext
    started_at: datetime | None
    completed_at: datetime | None
    error: Exception | None
    compensation_errors: list[Exception]
    replay_config: ReplayConfig | None
    snapshot_storage: SnapshotStorage | None
    _state_machine: SagaStateMachine
    _executing: bool
    _execution_lock: Lock

    if TYPE_CHECKING:

        async def _execute_step_with_retry(self, step: SagaStep) -> None: ...
        async def _handle_execution_failure(
            self, error: Exception, start_time: datetime
        ) -> SagaResult: ...

    # =========================================================================
    # Status Reporting
    # =========================================================================

    @property
    def current_state(self) -> str:
        """Get current state name"""
        return self._state_machine.current_state.name  # type: ignore[union-attr, no-any-return]

    @property
    def state_configuration(self) -> list[str]:
        """Return active state values in a serializable representation."""
        values = [str(value) for value in self._state_machine.configuration_values]
        return values or [self.status.value]

    def get_status(self) -> dict[str, Any]:
        """Get detailed saga status"""
        return {
            "saga_id": self.saga_id,
            "name": self.name,
            "version": self.version,
            "status": self.status.value,
            "current_state": self.current_state,
            "configuration": self.state_configuration,
            "total_steps": len(self.steps),
            "completed_steps": len(self.completed_steps),
            "steps": [self._get_step_status(step) for step in self.steps],
            "started_at": self._format_datetime(self.started_at),
            "completed_at": self._format_datetime(self.completed_at),
            "error": str(self.error) if self.error else None,
            "compensation_errors": [str(e) for e in self.compensation_errors],
        }

    def _get_step_status(self, step) -> dict[str, Any]:
        """Get status dict for a single step."""
        return {
            "name": step.name,
            "status": step.status.value,
            "retry_count": step.retry_count,
            "error": str(step.error) if step.error else None,
            "executed_at": self._format_datetime(step.executed_at),
            "compensated_at": self._format_datetime(step.compensated_at),
        }

    @staticmethod
    def _format_datetime(dt: datetime | None) -> str | None:
        """Format datetime to ISO string or None."""
        return dt.isoformat() if dt else None

    # =========================================================================
    # Replay & Snapshot Support
    # =========================================================================

    def _should_capture_snapshot(self, strategy: SnapshotStrategy, before: bool) -> bool:
        """Check if snapshot should be captured based on strategy."""
        from sagaz.core.replay import SnapshotStrategy

        if strategy == SnapshotStrategy.BEFORE_EACH_STEP and before:
            return True
        if strategy == SnapshotStrategy.AFTER_EACH_STEP and not before:
            return True
        if strategy == SnapshotStrategy.ON_COMPLETION and self.status == SagaStatus.COMPLETED:
            return True
        return strategy == SnapshotStrategy.ON_FAILURE and self.status == SagaStatus.FAILED

    async def _capture_snapshot(self, step_name: str, step_index: int, before: bool = True) -> None:
        """
        Capture a snapshot of current saga state.

        Args:
            step_name: Name of the step being executed
            step_index: Index of the step
            before: If True, snapshot taken before step; if False, after step
        """
        if not self.replay_config or not self.replay_config.enable_snapshots:
            return

        if not self.snapshot_storage:
            logger.warning("Snapshot capture enabled but no snapshot_storage configured")
            return

        from sagaz.core.replay import SagaSnapshot

        if not self._should_capture_snapshot(self.replay_config.snapshot_strategy, before):
            return

        try:
            snapshot = SagaSnapshot.create(
                saga_id=UUID(self.saga_id),
                saga_name=self.name,
                step_name=step_name,
                step_index=step_index,
                status=self.status.value,
                context=self.context.data.copy(),
                completed_steps=[s.name for s in self.completed_steps],
                retention_until=self.replay_config.get_retention_until(),
                configuration=self.state_configuration,
            )
            await self.snapshot_storage.save_snapshot(snapshot)
            logger.debug(
                f"Snapshot captured for saga {self.saga_id} at step '{step_name}' "
                f"({'before' if before else 'after'})"
            )
        except Exception as e:
            logger.error(f"Failed to capture snapshot: {e}", exc_info=True)

    async def execute_from_snapshot(
        self,
        snapshot: SagaSnapshot,
        context_override: dict[str, Any] | None = None,
    ) -> SagaResult:
        """
        Resume saga execution from a snapshot.

        Args:
            snapshot: Snapshot to resume from
            context_override: Optional context overrides

        Returns:
            SagaResult with execution outcome

        Raises:
            SagaExecutionError: If saga cannot be resumed
        """
        async with self._execution_lock:
            if self._executing:
                msg = "Saga is already executing"
                raise SagaExecutionError(msg)

            self._executing = True
            start_time = datetime.now()

            try:
                # Restore context from snapshot
                self.context = SagaContext(_saga_id=self.saga_id)
                self.context.data = snapshot.context.copy()

                # Apply context overrides
                if context_override:
                    self.context.data.update(context_override)
                    logger.info(
                        f"Applied {len(context_override)} context overrides to saga {self.saga_id}"
                    )

                # Mark completed steps as executed (idempotency)
                completed_step_names = set(snapshot.completed_steps)
                self._executed_step_keys = {
                    step.idempotency_key for step in self.steps if step.name in completed_step_names
                }

                # Start state machine execution
                try:
                    await self._state_machine.start()
                except TransitionNotAllowed as e:
                    msg = f"Cannot start saga from snapshot: {e}"
                    raise SagaExecutionError(msg) from e

                logger.info(
                    f"Resuming saga {self.name} from step '{snapshot.step_name}' "
                    f"({len(completed_step_names)} steps already completed)"
                )

                # Execute remaining steps (sequential mode for now)
                for i, step in enumerate(self.steps):
                    if step.idempotency_key in self._executed_step_keys:
                        logger.info(f"Skipping step '{step.name}' - already completed")
                        self.completed_steps.append(step)
                        continue

                    # Capture snapshot before executing
                    await self._capture_snapshot(step.name, i, before=True)

                    await self._execute_step_with_retry(step)
                    self.completed_steps.append(step)
                    self._executed_step_keys.add(step.idempotency_key)

                    # Capture snapshot after executing
                    await self._capture_snapshot(step.name, i, before=False)

                await self._state_machine.succeed()

                return SagaResult(
                    success=True,
                    saga_name=self.name,
                    status=SagaStatus.COMPLETED,
                    completed_steps=len(self.completed_steps),
                    total_steps=len(self.steps),
                    execution_time=(datetime.now() - start_time).total_seconds(),
                    context=self.context,
                )

            except Exception as e:
                return await self._handle_execution_failure(e, start_time)

            finally:
                self._executing = False
