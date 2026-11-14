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
from sagaz.core.execution.state_machine import SagaStateMachine
from sagaz.core.saga._compensation import _SagaCompensationMixin
from sagaz.core.saga._dag import DAGExecutor
from sagaz.core.saga._dag_delegation import _SagaDAGDelegationMixin
from sagaz.core.saga._execution import _SagaExecutionMixin
from sagaz.core.saga._executor import _StepExecutor
from sagaz.core.saga._lifecycle import _SagaLifecycleMixin
from sagaz.core.saga._snapshot import _SagaSnapshotMixin
from sagaz.core.saga._step import SagaStep
from sagaz.core.saga._step_execution import StepExecutor
from sagaz.core.saga._visualization import _SagaVisualizationMixin
from sagaz.core.types import ParallelFailureStrategy, SagaResult, SagaStatus, SagaStepStatus

# Configure logging
logger = logging.getLogger(__name__)


class Saga(
    _SagaLifecycleMixin,
    _SagaDAGDelegationMixin,
    _SagaExecutionMixin,
    _SagaVisualizationMixin,
    _SagaCompensationMixin,
    _SagaSnapshotMixin,
    ABC,
):
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
