"""Saga DAG delegation mixin - forwards DAG planning/execution to ``DAGExecutor``."""

from typing import TYPE_CHECKING

from sagaz.core.types import SagaResult, SagaStatus

if TYPE_CHECKING:
    from sagaz.core.saga._dag import DAGExecutor


class _SagaDAGDelegationMixin:
    """Mixin exposing DAG helpers on the Saga by delegating to ``self._dag_executor``."""

    # Attributes provided by the concrete Saga host.
    _dag_executor: "DAGExecutor"

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
