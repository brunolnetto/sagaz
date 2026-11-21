"""Bugs found by the feature × mode audit in the classic engine (#549, #558, #559)."""

from __future__ import annotations

import asyncio
import time

import pytest

from sagaz import Saga, action
from sagaz.core.exceptions import SagaTimeoutError
from sagaz.core.saga import Saga as ClassicSaga
from sagaz.core.types import SagaStatus
from sagaz.dry_run import DryRunEngine, DryRunMode


async def ok(ctx):
    return 1


async def boom(ctx):
    msg = "declined"
    raise ValueError(msg)


def recorder(undone: list[str], name: str):
    async def undo(result, ctx):
        undone.append(name)

    return undo


class TestPivots:
    """#549: a completed pivot and its ancestors are not compensated."""

    async def test_sequential(self):
        undone: list[str] = []
        saga = ClassicSaga("order")
        saga.retry_backoff_base = 0
        await saga.add_step("reserve", ok, recorder(undone, "reserve"))
        await saga.add_step("charge", ok, recorder(undone, "charge"), pivot=True)
        await saga.add_step("notify", ok, recorder(undone, "notify"))
        await saga.add_step("ship", boom, max_retries=0)
        result = await saga.execute()
        assert result.status == SagaStatus.ROLLED_BACK
        assert undone == ["notify"]  # after the pivot only
        assert saga.steps[0].tainted is True

    async def test_dag_locks_only_the_pivot_s_ancestors(self):
        undone: list[str] = []
        saga = ClassicSaga("order")
        saga.retry_backoff_base = 0
        await saga.add_step("reserve", ok, recorder(undone, "reserve"), dependencies=set())
        await saga.add_step("audit", ok, recorder(undone, "audit"), dependencies=set())
        await saga.add_step(
            "charge", ok, recorder(undone, "charge"), dependencies={"reserve"}, pivot=True
        )
        await saga.add_step("ship", boom, dependencies={"charge", "audit"}, max_retries=0)
        await saga.execute()
        assert undone == ["audit"]  # reserve is the pivot's ancestor; audit is not

    async def test_without_a_pivot_everything_is_compensated(self):
        undone: list[str] = []
        saga = ClassicSaga("order")
        await saga.add_step("reserve", ok, recorder(undone, "reserve"))
        await saga.add_step("charge", ok, recorder(undone, "charge"))
        await saga.add_step("ship", boom, max_retries=0)
        await saga.execute()
        assert undone == ["charge", "reserve"]


class TestDagSteps:
    """#559: DAG steps retry, time out and may be sync, like sequential steps."""

    async def test_retries(self):
        calls: list[int] = []

        async def flaky(ctx):
            calls.append(1)
            if len(calls) < 3:
                msg = "down"
                raise ConnectionError(msg)
            return "ok"

        saga = ClassicSaga("dag")
        saga.retry_backoff_base = 0
        await saga.add_step("flaky", flaky, dependencies=set(), max_retries=3)
        result = await saga.execute()
        assert (result.status, len(calls)) == (SagaStatus.COMPLETED, 3)

    async def test_timeouts(self):
        async def slow(ctx):
            await asyncio.sleep(1)

        saga = ClassicSaga("dag")
        await saga.add_step("slow", slow, dependencies=set(), timeout=0.05, max_retries=0)
        started = time.monotonic()
        result = await saga.execute()
        assert time.monotonic() - started < 0.5
        assert isinstance(result.error, SagaTimeoutError)

    async def test_sync_steps(self):
        saga = ClassicSaga("dag")
        await saga.add_step("a", lambda ctx: {"a": 1}, dependencies=set())
        await saga.add_step("b", ok, dependencies={"a"})
        result = await saga.execute()
        assert result.status == SagaStatus.COMPLETED
        assert saga.context.get("a") == {"a": 1}


class TestDryRunOrder:
    """#558: the dry run plans steps the way each engine runs them."""

    @staticmethod
    async def groups(saga):
        result = await DryRunEngine().run(saga, {}, DryRunMode.SIMULATE)
        return result.parallel_groups

    async def test_classic_dag(self):
        saga = ClassicSaga("d")
        await saga.add_step("a", ok, dependencies=set())
        await saga.add_step("b", ok, dependencies={"a"})
        await saga.add_step("c", ok, dependencies={"a"})
        assert [sorted(g) for g in await self.groups(saga)] == [["a"], ["b", "c"]]

    async def test_classic_sequential(self):
        saga = ClassicSaga("s")
        await saga.add_step("a", ok)
        await saga.add_step("b", ok)
        assert await self.groups(saga) == [["a"], ["b"]]

    async def test_sagaz_saga_runs_steps_without_dependencies_in_parallel(self):
        class Parallel(Saga):
            saga_name = "p"

            @action("a")
            async def a(self, ctx): ...

            @action("b")
            async def b(self, ctx): ...

        assert [sorted(g) for g in await self.groups(Parallel())] == [["a", "b"]]


@pytest.mark.parametrize("dag", [False, True])
async def test_a_failure_still_reports_the_step(dag):
    saga = ClassicSaga("x")
    kwargs = {"dependencies": set()} if dag else {}
    await saga.add_step("only", boom, max_retries=0, **kwargs)
    result = await saga.execute()
    assert result.status == SagaStatus.ROLLED_BACK
    assert "declined" in str(result.error)
