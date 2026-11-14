"""Tests for the imperative Saga's delegation to DAGExecutor and StepExecutor."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from sagaz.core.saga import Saga, SagaStep
from sagaz.core.types import SagaStatus


@pytest.fixture
def saga() -> Saga:
    saga = Saga(name="delegation")
    saga._dag_executor = MagicMock()
    saga._step_executor = MagicMock()
    return saga


SYNC_DELEGATES = [
    ("_validate_connected_graph", "validate_connected_graph", ()),
    ("_build_adjacency_list", "_build_adjacency_list", ({"a"},)),
    ("_bfs_reachable", "_bfs_reachable", ({"a": set()}, {"a"})),
    ("_check_connectivity", "_check_connectivity", ({"a"}, {"a"}, {"a": set()})),
    ("_find_connected_components", "_find_connected_components", ({"a": set()}, {"a"})),
    ("_build_execution_batches", "build_execution_batches", ()),
    ("_build_dag_batches", "_build_dag_batches", ()),
    ("_find_ready_steps", "_find_ready_steps", ({"a"}, set())),
    ("_format_dependency_error", "_format_dependency_error", ({"a"}, set())),
    ("_get_parallel_strategy", "_get_parallel_strategy", ()),
    ("_mark_batch_completed", "_mark_batch_completed", ({"a"}, {})),
    ("_mark_completed_executors", "_mark_completed_executors", ([],)),
    ("_build_dag_result", "_build_dag_result", (0, True, SagaStatus.COMPLETED, None)),
]


@pytest.mark.parametrize(("saga_method", "executor_method", "args"), SYNC_DELEGATES)
def test_sync_dag_delegates_forward_to_dag_executor(saga, saga_method, executor_method, args):
    result = getattr(saga, saga_method)(*args)

    target = getattr(saga._dag_executor, executor_method)
    target.assert_called_once_with(*args)
    if saga_method not in {
        "_validate_connected_graph",
        "_check_connectivity",
        "_mark_batch_completed",
        "_mark_completed_executors",
    }:
        assert result is target.return_value


@pytest.mark.asyncio
async def test_execute_dag_delegates_to_dag_executor(saga):
    saga._dag_executor.execute_dag = AsyncMock(return_value="dag-result")

    assert await saga._execute_dag() == "dag-result"
    saga._dag_executor.execute_dag.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_execute_batch_delegates_to_dag_executor(saga):
    saga._dag_executor._execute_batch = AsyncMock(return_value=None)

    assert await saga._execute_batch(0, {"a"}, {}, "strategy") is None
    saga._dag_executor._execute_batch.assert_awaited_once_with(0, {"a"}, {}, "strategy")


@pytest.mark.asyncio
async def test_step_execution_delegates_to_step_executor(saga):
    step = SagaStep(name="s", action=lambda ctx: None)
    saga._step_executor.execute_step_with_retry = AsyncMock()
    saga._step_executor.execute_step = AsyncMock()

    await saga._execute_step_with_retry(step)
    await saga._execute_step(step)

    saga._step_executor.execute_step_with_retry.assert_awaited_once_with(step)
    saga._step_executor.execute_step.assert_awaited_once_with(step)
