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
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from sagaz.storage.base import SagaStorage

from statemachine.exceptions import TransitionNotAllowed

from sagaz.exceptions import (
    SagaCompensationError,
    SagaExecutionError,
    SagaStepError,
    SagaTimeoutError,
)
from sagaz.state_machine import SagaStateMachine
from sagaz.types import ParallelFailureStrategy, SagaResult, SagaStatus, SagaStepStatus

# Configure logging
logger = logging.getLogger(__name__)


class _StepExecutor:
    """Helper class to wrap SagaStep for strategy execution"""

    def __init__(self, step: "SagaStep", saga_context: "SagaContext"):
        self.step = step
        self.saga_context = saga_context
        self.result = None
        self.error: Exception | None = None
        self.completed = False

    async def execute(self) -> Any:
        """Execute the step action and store result or error"""
        try:
            result = await self.step.action(self.saga_context)
            self.result = result
            self.step.result = result
            # Store result in context for dependent steps
            self.saga_context.set(self.step.name, result)
            self.completed = True
            return result
        except Exception as e:
            self.error = e
            self.step.error = e
            raise

    async def compensate(self) -> None:
        """Execute the step compensation if available"""
        if self.step.compensation:
            await self.step.compensation(self.result, self.saga_context)

    @property
    def name(self) -> str:
        return self.step.name


class Saga(ABC):
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
    ):
        self.name = name
        self.version = version
        self.saga_id = str(uuid4())
        self.status = SagaStatus.PENDING
        self.steps: list[SagaStep] = []
        self.completed_steps: list[SagaStep] = []
        self.context = SagaContext()
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
        """
        self._validate_can_add_step(name)
        step = self._create_step(
            name, action, compensation, timeout, compensation_timeout, max_retries, idempotency_key
        )
        self.steps.append(step)
        self._register_dependencies(name, dependencies)
        logger.debug(f"Added step '{name}' to saga {self.name}")

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
        """
        Validate that all steps form a single connected component.

        For DAG sagas (with dependencies), we require all steps to be reachable
        from each other via the undirected dependency graph. This prevents
        confusing scenarios where disconnected step groups run independently.

        Raises:
            ValueError: If the saga has disconnected step components.
        """
        if not self._has_dependencies or len(self.steps) <= 1:
            return  # Sequential sagas or single-step sagas are always connected

        step_names = {step.name for step in self.steps}
        adjacency = self._build_adjacency_list(step_names)
        visited = self._bfs_reachable(adjacency, step_names)
        self._check_connectivity(step_names, visited, adjacency)

    def _build_adjacency_list(self, step_names: set[str]) -> dict[str, set[str]]:
        """Build undirected adjacency list for connectivity check."""
        adjacency: dict[str, set[str]] = {name: set() for name in step_names}
        for name, deps in self.step_dependencies.items():
            for dep in deps:
                if dep in step_names:
                    adjacency[name].add(dep)
                    adjacency[dep].add(name)
        return adjacency

    def _bfs_reachable(self, adjacency: dict[str, set[str]], step_names: set[str]) -> set[str]:
        """BFS to find all reachable nodes from first step."""
        start = next(iter(step_names))
        visited: set[str] = set()
        queue = [start]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            queue.extend(adjacency[node] - visited)
        return visited

    def _check_connectivity(
        self, step_names: set[str], visited: set[str], adjacency: dict[str, set[str]]
    ) -> None:
        """Raise error if steps are not all connected."""
        unreachable = step_names - visited
        if unreachable:
            components = self._find_connected_components(adjacency, step_names)
            msg = (
                f"Saga '{self.name}' has {len(components)} disconnected step groups: "
                f"{[sorted(c) for c in components]}. "
                f"All steps must be connected via dependencies. "
                "Consider splitting into separate sagas or adding connecting dependencies."
            )
            raise ValueError(msg)

    def _find_connected_components(
        self, adjacency: dict[str, set[str]], step_names: set[str]
    ) -> list[set[str]]:
        """Find all connected components in the step graph."""
        components = []
        remaining = step_names.copy()

        while remaining:
            start = next(iter(remaining))
            component: set[str] = set()
            queue = [start]

            while queue:
                node = queue.pop(0)
                if node in component:
                    continue
                component.add(node)
                queue.extend(adjacency[node] - component)

            components.append(component)
            remaining -= component

        return components

    def to_mermaid(
        self,
        direction: str = "TB",
        show_compensation: bool = True,
        highlight_trail: dict[str, Any] | None = None,
        show_state_markers: bool = True,
    ) -> str:
        """
        Generate a Mermaid flowchart diagram of the saga.

        Shows a decision tree where each step can succeed (go to next) or fail
        (trigger compensation chain backwards).

        Colors:
        - Success path: green styling
        - Failure/compensation path: amber/yellow styling
        - Highlighted trail: bold styling for executed steps

        Args:
            direction: Flowchart direction - "TB" (top-bottom), "LR" (left-right)
            show_compensation: If True, show compensation nodes and fail branches
            highlight_trail: Optional dict with execution trail info
            show_state_markers: If True, show initial (●) and final (◎) state nodes

        Returns:
            Mermaid diagram string that can be rendered in markdown.
        """
        from sagaz.mermaid import HighlightTrail, MermaidGenerator, StepInfo

        # Convert steps to StepInfo format
        steps = [
            StepInfo(
                name=s.name,
                has_compensation=s.compensation is not None,
                depends_on=set(self.step_dependencies.get(s.name, set())),
            )
            for s in self.steps
        ]

        # Create generator and generate diagram
        generator = MermaidGenerator(
            steps=steps,
            direction=direction,
            show_compensation=show_compensation,
            show_state_markers=show_state_markers,
            highlight_trail=HighlightTrail.from_dict(highlight_trail),
        )

        return generator.generate()

    async def to_mermaid_with_execution(
        self,
        saga_id: str,
        storage: "SagaStorage",
        direction: str = "TB",
        show_compensation: bool = True,
        show_state_markers: bool = True,
    ) -> str:
        """
        Generate Mermaid diagram with execution trail from storage.

        Args:
            saga_id: The saga execution ID to visualize
            storage: SagaStorage instance to fetch execution data from
            direction: Flowchart direction
            show_compensation: If True, show compensation nodes
            show_state_markers: If True, show initial/final nodes

        Returns:
            Mermaid diagram with highlighted execution trail.
        """
        saga_data = await storage.load_saga_state(saga_id)

        if not saga_data:
            return self.to_mermaid(direction, show_compensation, None, show_state_markers)

        # Parse steps to build highlight trail
        steps_data = saga_data.get("steps", [])
        completed_steps = set()
        failed_step = None
        compensated_steps = set()

        for step in steps_data:
            status = step.get("status")
            name = step.get("name")

            if status == "completed":
                completed_steps.add(name)
            elif status == "failed":
                failed_step = name
            elif status == "compensated":
                compensated_steps.add(name)
                # A compensated step must have completed first
                completed_steps.add(name)
            elif status == "compensating":
                compensated_steps.add(name)
                completed_steps.add(name)

        highlight_trail = {
            "completed_steps": list(completed_steps),
            "failed_step": failed_step,
            "compensated_steps": list(compensated_steps),
        }

        return self.to_mermaid(direction, show_compensation, highlight_trail, show_state_markers)

    def to_mermaid_markdown(
        self,
        direction: str = "TB",
        show_compensation: bool = True,
        highlight_trail: dict[str, Any] | None = None,
        show_state_markers: bool = True,
    ) -> str:
        """
        Generate a Mermaid diagram wrapped in markdown code fence.

        Args:
            direction: Flowchart direction
            show_compensation: If True, show compensation nodes and flows
            highlight_trail: Optional execution trail to highlight
            show_state_markers: If True, show initial/final nodes

        Returns:
            Mermaid diagram in markdown format.
        """
        return f"```mermaid\n{self.to_mermaid(direction, show_compensation, highlight_trail, show_state_markers)}\n```"

    def _build_execution_batches(self) -> list[set[str]]:
        """
        Build execution batches for DAG parallel execution

        Returns list of sets, where each set contains steps that can run in parallel
        """
        if not self._has_dependencies:
            return [{step.name} for step in self.steps]

        # Validate that all steps form a connected graph
        self._validate_connected_graph()

        return self._build_dag_batches()

    def _build_dag_batches(self) -> list[set[str]]:
        """Build batches using topological sort for DAG execution."""
        batches = []
        executed: set[str] = set()
        remaining = {step.name for step in self.steps}

        while remaining:
            ready = self._find_ready_steps(remaining, executed)
            if not ready:
                raise ValueError(self._format_dependency_error(remaining, executed))
            batches.append(ready)
            executed.update(ready)
            remaining -= ready

        return batches

    def _find_ready_steps(self, remaining: set[str], executed: set[str]) -> set[str]:
        """Find steps whose dependencies are satisfied."""
        return {name for name in remaining if self.step_dependencies[name].issubset(executed)}

    def _format_dependency_error(self, remaining: set[str], executed: set[str]) -> str:
        """Format error message for circular/missing dependencies."""
        missing_deps = [
            f"{name} needs {self.step_dependencies[name] - executed}"
            for name in remaining
            if self.step_dependencies[name] - executed
        ]
        return f"Circular or missing dependencies detected: {missing_deps}"

    async def _execute_dag(self) -> SagaResult:
        """Execute saga using DAG parallel execution"""
        start_time = datetime.now()
        step_map = {step.name: step for step in self.steps}
        strategy = self._get_parallel_strategy()

        try:
            # Execute each batch in sequence
            for batch_idx, batch in enumerate(self.execution_batches):
                batch_error = await self._execute_batch(batch_idx, batch, step_map, strategy)

                if batch_error:
                    await self._compensate_all()
                    return self._build_dag_result(
                        start_time, success=False, status=SagaStatus.ROLLED_BACK, error=batch_error
                    )

            return self._build_dag_result(start_time, success=True, status=SagaStatus.COMPLETED)

        except Exception as e:
            logger.error(f"DAG execution failed for saga {self.name}: {e}")
            return self._build_dag_result(
                start_time, success=False, status=SagaStatus.FAILED, error=e
            )

    def _get_parallel_strategy(self):
        """Get the parallel execution strategy implementation."""
        from sagaz.strategies.fail_fast import FailFastStrategy
        from sagaz.strategies.fail_fast_grace import FailFastWithGraceStrategy
        from sagaz.strategies.wait_all import WaitAllStrategy

        if self.failure_strategy == ParallelFailureStrategy.FAIL_FAST:
            return FailFastStrategy()
        if self.failure_strategy == ParallelFailureStrategy.WAIT_ALL:
            return WaitAllStrategy()
        return FailFastWithGraceStrategy()

    async def _execute_batch(
        self, batch_idx: int, batch: set, step_map: dict, strategy
    ) -> Exception | None:
        """Execute a single batch. Returns exception if failed, None if success."""
        logger.info(f"Executing batch {batch_idx + 1}/{len(self.execution_batches)}: {batch}")

        batch_executors = [_StepExecutor(step_map[step_name], self.context) for step_name in batch]

        try:
            await strategy.execute_parallel_steps(batch_executors)
            self._mark_batch_completed(batch, step_map)
            return None

        except Exception as batch_error:
            logger.error(f"Batch {batch_idx + 1} failed: {batch_error}")
            self._mark_completed_executors(batch_executors)
            return batch_error

    def _mark_batch_completed(self, batch: set, step_map: dict):
        """Mark all steps in batch as completed."""
        for step_name in batch:
            step = step_map[step_name]
            self.completed_steps.append(step)
            self._executed_step_keys.add(step.idempotency_key)
            logger.info(f"Step '{step_name}' completed successfully")

    def _mark_completed_executors(self, executors: list):
        """Mark any executors that completed before failure."""
        for executor in executors:
            if executor.completed and executor.step not in self.completed_steps:
                step = executor.step
                self.completed_steps.append(step)
                self._executed_step_keys.add(step.idempotency_key)
                logger.info(f"Step '{step.name}' completed before batch failure")

    def _build_dag_result(
        self, start_time, success: bool, status: SagaStatus, error: Exception | None = None
    ) -> SagaResult:
        """Build a SagaResult for DAG execution."""
        execution_time = (datetime.now() - start_time).total_seconds()
        return SagaResult(
            success=success,
            saga_name=self.name,
            status=status,
            completed_steps=len(self.completed_steps),
            total_steps=len(self.steps),
            error=error,
            execution_time=execution_time,
            context=self.context,
            compensation_errors=self.compensation_errors if not success else [],
        )

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

        for step in self.steps:
            if step.idempotency_key in self._executed_step_keys:
                logger.info(f"Skipping step '{step.name}' - already executed (idempotent)")
                continue

            await self._execute_step_with_retry(step)
            self.completed_steps.append(step)
            self._executed_step_keys.add(step.idempotency_key)

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
        """Execute a step with retry logic and exponential backoff"""
        last_error: SagaTimeoutError | SagaStepError | None = None
        total_attempts = step.max_retries + 1  # Initial attempt + retries

        for attempt in range(total_attempts):
            try:
                step.retry_count = attempt
                await self._execute_step(step)
                return  # Success!

            except SagaTimeoutError as e:
                last_error = e
                logger.warning(
                    f"Step '{step.name}' timed out (attempt {attempt + 1}/{total_attempts})"
                )

            except SagaStepError as e:
                last_error = e
                logger.warning(
                    f"Step '{step.name}' failed (attempt {attempt + 1}/{total_attempts}): {e}"
                )

            # Exponential backoff before retry (configurable base timeout)
            if attempt < total_attempts - 1:
                backoff_time = self.retry_backoff_base * (2**attempt)
                logger.info(f"Retrying step '{step.name}' in {backoff_time}s...")
                await asyncio.sleep(backoff_time)

        # All retries exhausted
        step.error = last_error
        assert last_error is not None, "last_error should be set after exhausting retries"
        raise last_error

    async def _execute_step(self, step: "SagaStep") -> None:
        """Execute a single step with timeout"""
        try:
            step.status = SagaStepStatus.EXECUTING
            logger.info(f"Executing step: {step.name}")

            # Execute with timeout
            step.result = await asyncio.wait_for(
                self._invoke(step.action, self.context), timeout=step.timeout
            )

            # Store result in context for next steps
            self.context.set(step.name, step.result)

            step.status = SagaStepStatus.COMPLETED
            step.executed_at = datetime.now()
            logger.info(f"Step '{step.name}' completed successfully")

        except TimeoutError:
            step.status = SagaStepStatus.FAILED
            error = SagaTimeoutError(f"Step '{step.name}' timed out after {step.timeout}s")
            step.error = error
            raise error

        except Exception as e:
            step.status = SagaStepStatus.FAILED
            step.error = e
            msg = f"Step '{step.name}' failed: {e!s}"
            raise SagaStepError(msg)

    async def _compensate_all(self) -> None:
        """
        Compensate all completed steps in reverse order
        Continues even if some compensations fail, collecting all errors
        """
        compensation_errors = await self._run_compensations()
        if compensation_errors:
            self._raise_compensation_error(compensation_errors)

    async def _run_compensations(self) -> list[SagaCompensationError]:
        """Execute all compensations, collecting errors."""
        errors = []
        for step in reversed(self.completed_steps):
            if step.compensation:
                error = await self._try_compensate_step(step)
                if error:
                    errors.append(error)
        return errors

    async def _try_compensate_step(self, step: "SagaStep") -> SagaCompensationError | None:
        """Try to compensate a step, returning error if failed."""
        try:
            await self._compensate_step_with_retry(step)
            return None
        except SagaCompensationError as e:
            self.compensation_errors.append(e)
            logger.error(f"Compensation failed for step '{step.name}': {e}")
            return e

    def _raise_compensation_error(self, errors: list[SagaCompensationError]) -> None:
        """Raise aggregate compensation error."""
        error_summary = "; ".join(str(e) for e in errors)
        msg = f"Failed to compensate {len(errors)} steps: {error_summary}"
        raise SagaCompensationError(msg)

    async def _compensate_step_with_retry(self, step: "SagaStep") -> None:
        """Compensate a step with retry logic"""
        last_error: SagaCompensationError | None = None
        max_comp_retries = 3

        for attempt in range(max_comp_retries):
            try:
                await self._compensate_step(step)
                return  # Success!

            except SagaCompensationError as e:
                last_error = e
                logger.warning(
                    f"Compensation for '{step.name}' failed "
                    f"(attempt {attempt + 1}/{max_comp_retries})"
                )

            # Exponential backoff (uses configurable base timeout)
            if attempt < max_comp_retries - 1:
                backoff_time = self.retry_backoff_base * (2**attempt)
                await asyncio.sleep(backoff_time)

        # All retries exhausted
        assert last_error is not None, "last_error should be set after exhausting retries"
        raise last_error

    async def _compensate_step(self, step: "SagaStep") -> None:
        """Compensate a single step with timeout"""
        try:
            step.status = SagaStepStatus.COMPENSATING
            logger.info(f"Compensating step: {step.name}")

            # Type assertion - compensation must exist if _compensate_step is called
            assert step.compensation is not None, f"No compensation defined for step '{step.name}'"

            # Pass the step result to compensation for context
            await asyncio.wait_for(
                self._invoke(step.compensation, step.result, self.context),
                timeout=step.compensation_timeout,
            )

            step.status = SagaStepStatus.COMPENSATED
            step.compensated_at = datetime.now()
            logger.info(f"Step '{step.name}' compensated successfully")

        except TimeoutError:
            step.status = SagaStepStatus.FAILED
            msg = f"Compensation for '{step.name}' timed out after {step.compensation_timeout}s"
            raise SagaCompensationError(msg)

        except Exception as e:
            step.status = SagaStepStatus.FAILED
            step.error = e
            msg = f"Compensation for step '{step.name}' failed: {e!s}"
            raise SagaCompensationError(msg)

    @staticmethod
    async def _invoke(func: Callable[..., Any], *args, **kwargs) -> Any:
        """Invoke function (handle both sync and async)"""
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    @property
    def current_state(self) -> str:
        """Get current state name"""
        return self._state_machine.current_state.name  # type: ignore[no-any-return]

    def get_status(self) -> dict[str, Any]:
        """Get detailed saga status"""
        return {
            "saga_id": self.saga_id,
            "name": self.name,
            "version": self.version,
            "status": self.status.value,
            "current_state": self.current_state,
            "total_steps": len(self.steps),
            "completed_steps": len(self.completed_steps),
            "steps": [self._get_step_status(step) for step in self.steps],
            "started_at": self._format_datetime(self.started_at),
            "completed_at": self._format_datetime(self.completed_at),
            "error": str(self.error) if self.error else None,
            "compensation_errors": [str(e) for e in self.compensation_errors],
        }

    def _get_step_status(self, step: "SagaStep") -> dict[str, Any]:
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


@dataclass
class SagaContext:
    """Context passed between saga steps for data sharing"""

    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        """Set a value in the context"""
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the context"""
        return self.data.get(key, default)

    def has(self, key: str) -> bool:
        """Check if a key exists in the context"""
        return key in self.data


@dataclass
class SagaStep:
    """Represents a single step in a saga with full metadata"""

    name: str
    action: Callable[..., Any]  # Forward action
    compensation: Callable[..., Any] | None = None  # Rollback action
    status: SagaStepStatus = field(default=SagaStepStatus.PENDING)
    result: Any | None = None
    error: Exception | None = None
    executed_at: datetime | None = None
    compensated_at: datetime | None = None
    idempotency_key: str = field(default_factory=lambda: str(uuid4()))
    retry_attempts: int = 0
    max_retries: int = 3
    timeout: float = 30.0  # seconds
    compensation_timeout: float = 30.0
    retry_count: int = 0

    def __hash__(self):
        return hash(self.idempotency_key)
