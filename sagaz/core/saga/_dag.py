"""
DAG (Directed Acyclic Graph) execution logic for Saga pattern

Handles:
- Dependency graph validation and connectivity checks
- Topological sorting for parallel execution batches
- DAG execution orchestration
- Strategy-based parallel failure handling
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sagaz.core.execution.graph._types import CompensationFailureStrategy
from sagaz.core.types import ParallelFailureStrategy, SagaResult, SagaStatus

if TYPE_CHECKING:
    from sagaz.core.saga import Saga
    from sagaz.core.saga._step import SagaStep

logger = logging.getLogger(__name__)


class DAGExecutor:
    """Handles DAG validation and execution for saga parallel processing"""

    def __init__(self, saga: "Saga"):
        self.saga = saga

    def validate_connected_graph(self) -> None:
        """
        Validate that all steps form a single connected component.

        For DAG sagas (with dependencies), we require all steps to be reachable
        from each other via the undirected dependency graph. This prevents
        confusing scenarios where disconnected step groups run independently.

        Raises:
            ValueError: If the saga has disconnected step components.
        """
        if not self.saga._has_dependencies or len(self.saga.steps) <= 1:
            return  # Sequential sagas or single-step sagas are always connected

        step_names = {step.name for step in self.saga.steps}
        adjacency = self._build_adjacency_list(step_names)
        visited = self._bfs_reachable(adjacency, step_names)
        self._check_connectivity(step_names, visited, adjacency)

    def _build_adjacency_list(self, step_names: set[str]) -> dict[str, set[str]]:
        """Build undirected adjacency list for connectivity check."""
        adjacency: dict[str, set[str]] = {name: set() for name in step_names}
        for name, deps in self.saga.step_dependencies.items():
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
                f"Saga '{self.saga.name}' has {len(components)} disconnected step groups: "
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

    def build_execution_batches(self) -> list[set[str]]:
        """
        Build execution batches for DAG parallel execution

        Returns list of sets, where each set contains steps that can run in parallel
        """
        if not self.saga._has_dependencies:
            return [{step.name} for step in self.saga.steps]

        # Validate that all steps form a connected graph
        self.validate_connected_graph()

        return self._build_dag_batches()

    def _build_dag_batches(self) -> list[set[str]]:
        """Build batches using topological sort for DAG execution."""
        batches = []
        executed: set[str] = set()
        remaining = {step.name for step in self.saga.steps}

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
        return {name for name in remaining if self.saga.step_dependencies[name].issubset(executed)}

    def _format_dependency_error(self, remaining: set[str], executed: set[str]) -> str:
        """Format error message for circular/missing dependencies."""
        missing_deps = [
            f"{name} needs {self.saga.step_dependencies[name] - executed}"
            for name in remaining
            if self.saga.step_dependencies[name] - executed
        ]
        return f"Circular or missing dependencies detected: {missing_deps}"

    async def execute_dag(self) -> SagaResult:
        """Execute saga using DAG parallel execution"""
        from sagaz.core.saga._executor import _StepExecutor

        start_time = datetime.now()
        step_map = {step.name: step for step in self.saga.steps}
        strategy = self._get_parallel_strategy()

        try:
            # Execute each batch in sequence
            for batch_idx, batch in enumerate(self.saga.execution_batches):
                batch_error = await self._execute_batch(batch_idx, batch, step_map, strategy)

                if batch_error:
                    await self.saga._compensate_all()
                    return self._build_dag_result(
                        start_time, success=False, status=SagaStatus.ROLLED_BACK, error=batch_error
                    )

            return self._build_dag_result(start_time, success=True, status=SagaStatus.COMPLETED)

        except Exception as e:
            logger.error(f"DAG execution failed for saga {self.saga.name}: {e}")
            return self._build_dag_result(
                start_time,
                success=False,
                status=SagaStatus.FAILED,
                error=e,
            )

    def _get_parallel_strategy(self) -> Any:
        """Get the parallel execution strategy implementation."""
        from sagaz.core.strategies.fail_fast import FailFastStrategy
        from sagaz.core.strategies.fail_fast_grace import FailFastWithGraceStrategy
        from sagaz.core.strategies.wait_all import WaitAllStrategy

        if self.saga.failure_strategy == ParallelFailureStrategy.FAIL_FAST:
            return FailFastStrategy()
        if self.saga.failure_strategy == ParallelFailureStrategy.WAIT_ALL:
            return WaitAllStrategy()
        return FailFastWithGraceStrategy()

    async def _execute_batch(
        self, batch_idx: int, batch: set, step_map: dict, strategy: Any
    ) -> Exception | None:
        """Execute a single batch. Returns exception if failed, None if success."""
        from sagaz.core.saga._executor import _StepExecutor

        logger.info(
            f"Executing batch {batch_idx + 1}/{len(self.saga.execution_batches)}: {batch}"
        )

        batch_executors = [
            _StepExecutor(step_map[step_name], self.saga.context) for step_name in batch
        ]

        try:
            await strategy.execute_parallel_steps(batch_executors)
            self._mark_batch_completed(batch, step_map)
            return None

        except Exception as batch_error:
            logger.error(f"Batch {batch_idx + 1} failed: {batch_error}")
            self._mark_completed_executors(batch_executors)
            return batch_error

    def _mark_batch_completed(self, batch: set, step_map: dict) -> None:
        """Mark all steps in batch as completed."""
        for step_name in batch:
            step = step_map[step_name]
            self.saga.completed_steps.append(step)
            self.saga._executed_step_keys.add(step.idempotency_key)
            logger.info(f"Step '{step_name}' completed successfully")

    def _mark_completed_executors(self, executors: list) -> None:
        """Mark any executors that completed before failure."""
        for executor in executors:
            if executor.completed and executor.step not in self.saga.completed_steps:
                step = executor.step
                self.saga.completed_steps.append(step)
                self.saga._executed_step_keys.add(step.idempotency_key)
                logger.info(f"Step '{step.name}' completed before batch failure")

    def _build_dag_result(
        self,
        start_time: datetime,
        success: bool,
        status: SagaStatus,
        error: Exception | None = None,
    ) -> SagaResult:
        """Build a SagaResult for DAG execution."""
        execution_time = (datetime.now() - start_time).total_seconds()
        return SagaResult(
            success=success,
            saga_name=self.saga.name,
            status=status,
            completed_steps=len(self.saga.completed_steps),
            total_steps=len(self.saga.steps),
            error=error,
            execution_time=execution_time,
            context=self.saga.context,
            compensation_errors=self.saga.compensation_errors if not success else [],
        )
