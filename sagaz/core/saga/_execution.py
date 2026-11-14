"""Saga execution mixin - sequential/DAG run flow and failure handling for imperative Saga."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from statemachine.exceptions import TransitionNotAllowed

from sagaz.core.exceptions import SagaCompensationError, SagaExecutionError
from sagaz.core.types import SagaResult, SagaStatus

if TYPE_CHECKING:
    from sagaz.core.context import SagaContext
    from sagaz.core.execution.state_machine import SagaStateMachine
    from sagaz.core.replay import ReplayConfig
    from sagaz.core.saga._step import SagaStep
    from sagaz.core.saga._step_execution import StepExecutor

# Keep the original logger name so log records are unchanged by the split.
logger = logging.getLogger("sagaz.core.saga")


class _SagaExecutionMixin:
    """Mixin implementing the body of ``Saga.execute()`` (planning, modes, outcomes)."""

    # Attributes provided by the concrete Saga host.
    name: str
    steps: list["SagaStep"]
    completed_steps: list["SagaStep"]
    context: "SagaContext"
    status: SagaStatus
    error: Exception | None
    compensation_errors: list[Exception]
    execution_batches: list[set[str]]
    replay_config: "ReplayConfig | None"
    _state_machine: "SagaStateMachine"
    _executed_step_keys: set[str]
    _has_dependencies: bool
    _step_executor: "StepExecutor"

    if TYPE_CHECKING:
        # Methods provided by sibling mixins on the concrete Saga host.
        def _build_execution_batches(self) -> list[set[str]]: ...

        async def _execute_dag(self) -> SagaResult: ...

        async def _capture_snapshot(
            self, step_name: str, step_index: int, before: bool = True
        ) -> None: ...

        async def _compensate_all(self) -> None: ...

    async def _execute_inner(self, start_time) -> SagaResult:
        """Inner execution logic."""
        # Handle empty saga
        if not self.steps:
            return self._empty_saga_result(start_time)

        # Build execution plan
        plan_error = self._build_plan()
        if plan_error:
            return self._planning_failure_result(plan_error, start_time)

        # Start state machine
        try:
            await self._state_machine.start()
        except TransitionNotAllowed as e:
            msg = f"Cannot start saga: {e}"
            raise SagaExecutionError(msg) from e

        # Execute based on mode
        if self._has_dependencies:
            return await self._execute_dag_mode(start_time)
        return await self._execute_sequential_mode(start_time)

    def _empty_saga_result(self, start_time) -> SagaResult:
        """Result for saga with no steps."""
        logger.info(f"Saga {self.name} has no steps - completing immediately")
        return SagaResult(
            success=True,
            saga_name=self.name,
            status=SagaStatus.COMPLETED,
            completed_steps=0,
            total_steps=0,
            execution_time=(datetime.now() - start_time).total_seconds(),
            context=self.context,
        )

    def _build_plan(self) -> Exception | None:
        """Build execution batches. Returns error if failed."""
        try:
            self.execution_batches = self._build_execution_batches()
            logger.info(f"Saga {self.name} execution plan: {len(self.execution_batches)} batches")
            return None
        except ValueError as ve:
            self.error = ve
            logger.error(f"Saga {self.name} failed during planning: {ve}")
            return ve

    def _planning_failure_result(self, error, start_time) -> SagaResult:
        """Result for planning failure."""
        return SagaResult(
            success=False,
            saga_name=self.name,
            status=SagaStatus.FAILED,
            completed_steps=0,
            total_steps=len(self.steps),
            error=error,
            execution_time=(datetime.now() - start_time).total_seconds(),
        )

    async def _execute_dag_mode(self, start_time) -> SagaResult:
        """Execute in DAG/parallel mode."""
        logger.info(f"Executing saga {self.name} in DAG mode")
        result = await self._execute_dag()

        if result.success:
            await self._state_machine.succeed()
        else:
            await self._finalize_dag_failure()

        return result

    async def _finalize_dag_failure(self):
        """Finalize state machine after DAG failure."""
        try:
            await self._state_machine.fail()
            await self._state_machine.finish_compensation()
        except TransitionNotAllowed:
            await self._state_machine.fail_unrecoverable()

    async def _execute_sequential_mode(self, start_time) -> SagaResult:
        """Execute in sequential mode."""
        logger.info(f"Executing saga {self.name} in sequential mode")

        for i, step in enumerate(self.steps):
            if step.idempotency_key in self._executed_step_keys:
                logger.info(f"Skipping step '{step.name}' - already executed (idempotent)")
                continue

            # Capture snapshot before step execution
            await self._capture_snapshot(step.name, i, before=True)

            await self._execute_step_with_retry(step)
            self.completed_steps.append(step)
            self._executed_step_keys.add(step.idempotency_key)

            # Capture snapshot after step execution
            await self._capture_snapshot(step.name, i, before=False)

        await self._state_machine.succeed()

        # Capture completion snapshot if configured
        if self.replay_config and self.replay_config.enable_snapshots:
            await self._capture_snapshot("__completed__", len(self.steps), before=False)

        return SagaResult(
            success=True,
            saga_name=self.name,
            status=SagaStatus.COMPLETED,
            completed_steps=len(self.completed_steps),
            total_steps=len(self.steps),
            execution_time=(datetime.now() - start_time).total_seconds(),
            context=self.context,
        )

    async def _handle_execution_failure(self, error: Exception, start_time) -> SagaResult:
        """Handle execution failure with compensation."""
        self.error = error
        logger.error(f"Saga {self.name} failed: {error}", exc_info=True)

        try:
            await self._state_machine.fail()
        except TransitionNotAllowed:
            return self._no_compensation_result(error, start_time)

        return await self._attempt_compensation(error, start_time)

    def _no_compensation_result(self, error, start_time) -> SagaResult:
        """Result when no compensation needed."""
        self.status = SagaStatus.ROLLED_BACK
        return SagaResult(
            success=False,
            saga_name=self.name,
            status=SagaStatus.ROLLED_BACK,
            completed_steps=0,
            total_steps=len(self.steps),
            error=error,
            execution_time=(datetime.now() - start_time).total_seconds(),
            context=self.context,
        )

    async def _attempt_compensation(self, error, start_time) -> SagaResult:
        """Attempt to compensate and return result."""
        try:
            await self._compensate_all()
            await self._state_machine.finish_compensation()

            return SagaResult(
                success=False,
                saga_name=self.name,
                status=SagaStatus.ROLLED_BACK,
                completed_steps=len(self.completed_steps),
                total_steps=len(self.steps),
                error=error,
                execution_time=(datetime.now() - start_time).total_seconds(),
                context=self.context,
                compensation_errors=self.compensation_errors,
            )

        except SagaCompensationError:
            await self._state_machine.compensation_failed()

            return SagaResult(
                success=False,
                saga_name=self.name,
                status=SagaStatus.FAILED,
                completed_steps=len(self.completed_steps),
                total_steps=len(self.steps),
                error=error,
                execution_time=(datetime.now() - start_time).total_seconds(),
                compensation_errors=self.compensation_errors,
            )

    async def _execute_step_with_retry(self, step: "SagaStep") -> None:
        """Delegate to StepExecutor"""
        await self._step_executor.execute_step_with_retry(step)

    async def _execute_step(self, step: "SagaStep") -> None:
        """Delegate to StepExecutor"""
        await self._step_executor.execute_step(step)
