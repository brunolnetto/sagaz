"""
Saga Pattern - Distributed Transactions with Compensation (Production-Ready)

Enables multi-step business processes with automatic rollback capability.
Unlike traditional ACID transactions, Sagas use compensating transactions to undo failed steps.

Uses python-statemachine for robust state management with full async support.

Features:
- ✅ Full async/await support with proper state machine integration
- ✅ Idempotent operations with deduplication keys
- ✅ Retry logic with exponential backoff
- ✅ Timeout protection per step
- ✅ Comprehensive error handling with partial compensation recovery
- ✅ Context passing between steps
- ✅ Guard conditions for state transitions
- ✅ Detailed observability and logging
- ✅ Thread-safe execution with locks
- ✅ Saga versioning and migration support

Example - Trade Execution Saga:
    Step 1: Reserve funds         → Compensation: Unreserve funds
    Step 2: Send order to Binance → Compensation: Cancel order
    Step 3: Update position       → Compensation: Revert position
    Step 4: Log trade             → Compensation: Delete trade log

If any step fails, all previous steps are compensated (undone) in reverse order.

State Machine:
    PENDING → EXECUTING → COMPLETED
                     ↘ COMPENSATING → ROLLED_BACK
                     ↘ FAILED (unrecoverable compensation failure)

    Step states:
    PENDING → EXECUTING → COMPLETED
                     ↘ COMPENSATING → COMPENSATED
                     ↘ FAILED (unrecoverable)

Usage:
    saga = TradeSaga()
    await saga.add_step(
        name="reserve_funds",
        action=reserve_funds_action,
        compensation=unreserve_funds_compensation,
        timeout=10.0,
        retry_attempts=3
    )
    result = await saga.execute()  # Returns SagaResult with full details
"""

import asyncio
import logging
from abc import ABC
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from sagaz.core.replay import ReplayConfig, SagaSnapshot, SnapshotStrategy
    from sagaz.core.storage.base import SagaStorage
    from sagaz.core.storage.interfaces.snapshot import SnapshotStorage

from statemachine.exceptions import TransitionNotAllowed

from sagaz.core.context import SagaContext
from sagaz.core.exceptions import (
    SagaCompensationError,
    SagaExecutionError,
    SagaStepError,
    SagaTimeoutError,
)
from sagaz.core.saga._compensation import _SagaCompensationMixin
from sagaz.core.saga._dag import DAGExecutor
from sagaz.core.saga._executor import _StepExecutor
from sagaz.core.saga._snapshot import _SagaSnapshotMixin
from sagaz.core.saga._step import SagaStep
from sagaz.core.saga._step_execution import StepExecutor
from sagaz.core.saga._visualization import _SagaVisualizationMixin
from sagaz.core.types import ParallelFailureStrategy, SagaResult, SagaStatus, SagaStepStatus
from sagaz.core.execution.state_machine import SagaStateMachine

# Configure logging
logger = logging.getLogger(__name__)


class Saga(_SagaVisualizationMixin, _SagaCompensationMixin, _SagaSnapshotMixin, ABC):
    """
    Production-ready base class for saga implementations with state machine

    Concrete sagas should:
    1. Inherit from Saga
    2. Define steps in constructor or add_step calls
    3. Call execute() to run the saga
    4. Handle SagaResult appropriately
    """

    def __init__(
        self,
        name: str = "Saga",
        version: str = "1.0",
        failure_strategy: ParallelFailureStrategy = ParallelFailureStrategy.FAIL_FAST_WITH_GRACE,
        retry_backoff_base: float = 0.01,  # Base timeout for exponential backoff (seconds)
        replay_config: "ReplayConfig | None" = None,
        snapshot_storage: "SnapshotStorage | None" = None,
    ):
        self.name = name
        self.version = version
        self.saga_id = str(uuid4())
        self.status = SagaStatus.PENDING
        self.steps: list[SagaStep] = []
        self.completed_steps: list[SagaStep] = []
        self.context = SagaContext(_saga_id=self.saga_id)
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.error: Exception | None = None
        self.compensation_errors: list[Exception] = []
        self._state_machine = SagaStateMachine(self)
        self._executing = False
        self._execution_lock = asyncio.Lock()
        self._executed_step_keys: set[str] = set()  # For idempotency
        self.retry_backoff_base = retry_backoff_base  # Configurable retry backoff base

        # DAG/Parallel execution support
        self.step_dependencies: dict[str, set[str]] = {}  # step_name -> set of dependency names
        self.execution_batches: list[set[str]] = []
        self.failure_strategy = failure_strategy
        self._has_dependencies = False  # Track if any step has explicit dependencies

        # Replay support
        self.replay_config = replay_config
        self.snapshot_storage = snapshot_storage

        # Executor instances
        self._dag_executor = DAGExecutor(self)
        self._step_executor = StepExecutor(self)

    async def _on_enter_executing(self) -> None:
        """Callback: entering EXECUTING state"""
        self.status = SagaStatus.EXECUTING
        self.started_at = datetime.now()
        self.completed_steps = []
        logger.info(f"Saga {self.name} [{self.saga_id}] entering EXECUTING state")

    async def _on_enter_compensating(self) -> None:
        """Callback: entering COMPENSATING state"""
        self.status = SagaStatus.COMPENSATING
        logger.warning(
            f"Saga {self.name} [{self.saga_id}] entering COMPENSATING state - "
            f"rolling back {len(self.completed_steps)} steps"
        )

    async def _on_enter_completed(self) -> None:
        """Callback: entering COMPLETED state"""
        self.status = SagaStatus.COMPLETED
        self.completed_at = datetime.now()
        execution_time = (
            (self.completed_at - self.started_at).total_seconds() if self.started_at else 0
        )
        logger.info(
            f"Saga {self.name} [{self.saga_id}] COMPLETED successfully in {execution_time:.2f}s"
        )

    async def _on_enter_rolled_back(self) -> None:
        """Callback: entering ROLLED_BACK state"""
        self.status = SagaStatus.ROLLED_BACK
        self.completed_at = datetime.now()
        execution_time = (
            (self.completed_at - self.started_at).total_seconds() if self.started_at else 0
        )
        logger.info(f"Saga {self.name} [{self.saga_id}] ROLLED_BACK after {execution_time:.2f}s")

    async def _on_enter_failed(self) -> None:
        """Callback: entering FAILED state (unrecoverable)"""
        self.status = SagaStatus.FAILED
        self.completed_at = datetime.now()
        logger.error(
            f"Saga {self.name} [{self.saga_id}] FAILED - unrecoverable error during compensation"
        )

    async def add_step(
        self,
        name: str,
        action: Callable[..., Any],
        compensation: Callable[..., Any] | None = None,
        timeout: float = 30.0,
        compensation_timeout: float = 30.0,
        max_retries: int = 3,
        idempotency_key: str | None = None,
        dependencies: set[str] | None = None,
        pivot: bool = False,
    ) -> None:
        """
        Add a step to the saga

        Args:
            name: Step name
            action: Forward action to execute (can be sync or async)
            compensation: Rollback action (can be sync or async)
            timeout: Timeout in seconds for action execution
            compensation_timeout: Timeout in seconds for compensation
            max_retries: Maximum retry attempts for action
            idempotency_key: Custom idempotency key (auto-generated if None)
            dependencies: Optional set of step names this step depends on.
                         If None: Sequential execution (depends on previous step)
                         If empty set or specified: Parallel DAG execution
            pivot: If True, marks this step as a point of no return (v1.3.0).
                   Once a pivot step completes, its ancestors become tainted
                   and cannot be rolled back. Use for irreversible actions like
                   payment charges, external API calls with side effects, etc.
        """
        self._validate_can_add_step(name)
        step = self._create_step(
            name,
            action,
            compensation,
            timeout,
            compensation_timeout,
            max_retries,
            idempotency_key,
            pivot,
        )
        self.steps.append(step)
        self._register_dependencies(name, dependencies)
        logger.debug(f"Added step '{name}' to saga {self.name} (pivot={pivot})")

    def _validate_can_add_step(self, name: str) -> None:
        """Validate that a step can be added."""
        if self._executing:
            msg = "Cannot add steps while saga is executing"
            raise SagaExecutionError(msg)
        if any(s.name == name for s in self.steps):
            msg = f"Step '{name}' already exists"
            raise ValueError(msg)

    def _create_step(
        self,
        name: str,
        action: Callable,
        compensation: Callable | None,
        timeout: float,
        compensation_timeout: float,
        max_retries: int,
        idempotency_key: str | None,
        pivot: bool = False,
    ) -> "SagaStep":
        """Create a new SagaStep instance."""
        return SagaStep(
            name=name,
            action=action,
            compensation=compensation,
            timeout=timeout,
            compensation_timeout=compensation_timeout,
            max_retries=max_retries,
            idempotency_key=idempotency_key or str(uuid4()),
            pivot=pivot,
        )

    def _register_dependencies(self, name: str, dependencies: set[str] | None) -> None:
        """Register step dependencies for DAG execution."""
        if dependencies is not None:
            self._has_dependencies = True
            self.step_dependencies[name] = dependencies
        else:
            self.step_dependencies[name] = set()

    def set_failure_strategy(self, strategy: ParallelFailureStrategy) -> None:
        """Set the failure strategy for parallel execution"""
        self.failure_strategy = strategy
        logger.info(f"Saga {self.name} failure strategy set to {strategy.value}")

    def _validate_connected_graph(self) -> None:
        """Delegate to DAGExecutor"""
        self._dag_executor.validate_connected_graph()

    def _build_adjacency_list(self, step_names: set[str]) -> dict[str, set[str]]:
        """Delegate to DAGExecutor"""
        return self._dag_executor._build_adjacency_list(step_names)

    def _bfs_reachable(self, adjacency: dict[str, set[str]], step_names: set[str]) -> set[str]:
        """Delegate to DAGExecutor"""
        return self._dag_executor._bfs_reachable(adjacency, step_names)

    def _check_connectivity(
        self, step_names: set[str], visited: set[str], adjacency: dict[str, set[str]]
    ) -> None:
        """Delegate to DAGExecutor"""
        self._dag_executor._check_connectivity(step_names, visited, adjacency)

    def _find_connected_components(
        self, adjacency: dict[str, set[str]], step_names: set[str]
    ) -> list[set[str]]:
        """Delegate to DAGExecutor"""
        return self._dag_executor._find_connected_components(adjacency, step_names)

    def _build_execution_batches(self) -> list[set[str]]:
        """Delegate to DAGExecutor"""
        return self._dag_executor.build_execution_batches()

    def _build_dag_batches(self) -> list[set[str]]:
        """Delegate to DAGExecutor"""
        return self._dag_executor._build_dag_batches()

    def _find_ready_steps(self, remaining: set[str], executed: set[str]) -> set[str]:
        """Delegate to DAGExecutor"""
        return self._dag_executor._find_ready_steps(remaining, executed)

    def _format_dependency_error(self, remaining: set[str], executed: set[str]) -> str:
        """Delegate to DAGExecutor"""
        return self._dag_executor._format_dependency_error(remaining, executed)

    async def _execute_dag(self) -> SagaResult:
        """Delegate to DAGExecutor"""
        return await self._dag_executor.execute_dag()

    def _get_parallel_strategy(self):
        """Delegate to DAGExecutor"""
        return self._dag_executor._get_parallel_strategy()

    async def _execute_batch(
        self, batch_idx: int, batch: set, step_map: dict, strategy
    ) -> Exception | None:
        """Delegate to DAGExecutor"""
        return await self._dag_executor._execute_batch(batch_idx, batch, step_map, strategy)

    def _mark_batch_completed(self, batch: set, step_map: dict):
        """Delegate to DAGExecutor"""
        self._dag_executor._mark_batch_completed(batch, step_map)

    def _mark_completed_executors(self, executors: list):
        """Delegate to DAGExecutor"""
        self._dag_executor._mark_completed_executors(executors)

    def _build_dag_result(
        self, start_time, success: bool, status: SagaStatus, error: Exception | None = None
    ) -> SagaResult:
        """Delegate to DAGExecutor"""
        return self._dag_executor._build_dag_result(start_time, success, status, error)

    async def execute(self) -> SagaResult:
        """
        Execute the saga with full error handling and compensation

        Automatically detects execution mode:
        - Sequential: When no dependencies specified (traditional saga)
        - Parallel DAG: When dependencies are specified

        Returns:
            SagaResult: Detailed result of saga execution

        Raises:
            SagaExecutionError: If saga is already executing or in invalid state
        """
        async with self._execution_lock:
            if self._executing:
                msg = "Saga is already executing"
                raise SagaExecutionError(msg)

            self._executing = True
            start_time = datetime.now()

            try:
                return await self._execute_inner(start_time)

            except SagaExecutionError:
                raise

            except Exception as e:
                return await self._handle_execution_failure(e, start_time)

            finally:
                self._executing = False

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
            raise SagaExecutionError(msg)

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

    # =========================================================================
    # API Protection - Prevent mixing declarative and imperative approaches
    # =========================================================================

    async def run(self, *args, **kwargs):
        """
        The run() method is for declarative Saga. Use execute() for imperative Saga.

        Correct usage for imperative API:
            saga = Saga(name="MySaga")
            await saga.add_step("step1", action_fn, compensation_fn)
            result = await saga.execute()

        For declarative API with decorators, use the Saga class from sagaz.decorators:
            from sagaz import Saga, action, compensate

            class MySaga(Saga):
                saga_name = "my-saga"

                @action("step1")
                async def step1(self, ctx):
                    return {"result": "data"}

            saga = MySaga()
            result = await saga.run({"key": "value"})
        """
        msg = (
            "Cannot use run() on imperative Saga. "
            "Use execute() instead for imperative API. "
            "For declarative API with @action/@compensate decorators, "
            "use the Saga class from sagaz.decorators. "
            "See docstring for examples."
        )
        raise TypeError(msg)


__all__ = ["Saga", "SagaStep"]
