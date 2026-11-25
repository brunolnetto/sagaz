"""What the other steps of a parallel level do when one fails (#567)."""

from __future__ import annotations

import asyncio
import time

import pytest

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.decorators._parallel import failure_strategy, grace_period, run_level
from sagaz.core.exceptions import SagaDefinitionError, SagaFailedError
from sagaz.core.types import ParallelFailureStrategy

SLOW = 0.4  # how long the slow step takes; the failing one fails after 0.02 s


def checkout(log: list[str], strategy: object, grace: float = 2.0) -> Saga:
    """Three steps in one level: ``quick`` completes, ``decline`` fails, ``slow`` runs on."""

    class Checkout(Saga):
        saga_name = "checkout"

        @action("quick")
        async def quick(self, ctx):
            log.append("quick done")

        @compensate("quick")
        async def undo_quick(self, ctx):
            log.append("quick undone")

        @action("decline")
        async def decline(self, ctx):
            await asyncio.sleep(0.02)
            msg = "card declined"
            raise RuntimeError(msg)

        @action("slow")
        async def slow(self, ctx):
            try:
                await asyncio.sleep(SLOW)
            except asyncio.CancelledError:
                log.append("slow cancelled")
                raise
            log.append("slow done")

        @compensate("slow")
        async def undo_slow(self, ctx):
            log.append("slow undone")

    config = SagaConfig(
        metrics=False,
        logging=False,
        failure_strategy=strategy,
        failure_grace_period=grace,
        default_max_retries=0,
    )
    return Checkout(config=config)


async def run(saga: Saga) -> tuple[SagaFailedError, float]:
    started = time.monotonic()
    with pytest.raises(SagaFailedError) as raised:
        await saga.run({})
    return raised.value, time.monotonic() - started


class TestStrategies:
    async def test_wait_all_lets_every_step_finish_then_compensates_them(self):
        log: list[str] = []
        error, elapsed = await run(checkout(log, "WAIT_ALL"))
        assert "slow done" in log
        assert "slow cancelled" not in log
        assert {"quick undone", "slow undone"} <= set(log)
        assert elapsed >= SLOW
        assert "card declined" in str(error)

    async def test_fail_fast_cancels_the_steps_still_running(self):
        log: list[str] = []
        error, elapsed = await run(checkout(log, "FAIL_FAST"))
        assert "slow cancelled" in log
        assert "slow done" not in log
        assert "slow undone" not in log  # it did not complete, so it is not compensated
        assert "quick undone" in log  # the completed one is
        assert elapsed < SLOW
        assert "card declined" in str(error)

    async def test_grace_lets_a_step_finish_within_the_period(self):
        log: list[str] = []
        _, elapsed = await run(checkout(log, "FAIL_FAST_WITH_GRACE", grace=5.0))
        assert "slow done" in log
        assert "slow undone" in log
        assert elapsed < 5.0  # it went on as soon as the step finished

    async def test_grace_cancels_a_step_still_running_after_the_period(self):
        log: list[str] = []
        _, elapsed = await run(checkout(log, "FAIL_FAST_WITH_GRACE", grace=0.05))
        assert "slow cancelled" in log
        assert "slow undone" not in log
        assert "quick undone" in log
        assert elapsed < SLOW

    async def test_the_default_is_fail_fast_with_grace(self):
        config = SagaConfig(metrics=False, logging=False)
        assert (
            failure_strategy(config.failure_strategy)
            is ParallelFailureStrategy.FAIL_FAST_WITH_GRACE
        )
        assert config.failure_grace_period == 2.0

    async def test_a_level_without_failures_is_unaffected(self):
        done: list[str] = []

        class Fine(Saga):
            saga_name = "fine"

            @action("a")
            async def a(self, ctx):
                done.append("a")

            @action("b")
            async def b(self, ctx):
                await asyncio.sleep(0.02)
                done.append("b")

        await Fine(
            config=SagaConfig(metrics=False, logging=False, failure_strategy="FAIL_FAST")
        ).run({})
        assert sorted(done) == ["a", "b"]


class TestConfiguration:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("WAIT_ALL", ParallelFailureStrategy.WAIT_ALL),
            ("wait_all", ParallelFailureStrategy.WAIT_ALL),
            ("FAIL_FAST", ParallelFailureStrategy.FAIL_FAST),
            ("fail_fast_grace", ParallelFailureStrategy.FAIL_FAST_WITH_GRACE),
            (" fail_fast_with_grace ", ParallelFailureStrategy.FAIL_FAST_WITH_GRACE),
            (ParallelFailureStrategy.FAIL_FAST, ParallelFailureStrategy.FAIL_FAST),
            (None, ParallelFailureStrategy.FAIL_FAST_WITH_GRACE),
        ],
    )
    def test_a_strategy_is_given_by_name_value_or_enum(self, given, expected):
        assert failure_strategy(given) is expected

    def test_a_name_that_is_no_strategy_is_refused_when_configuring(self):
        with pytest.raises(SagaDefinitionError, match="failure_strategy must be one of"):
            SagaConfig(metrics=False, logging=False, failure_strategy="fastest")

    def test_a_grace_period_that_is_not_a_number_is_the_default(self):
        assert grace_period(0.5) == 0.5
        assert grace_period(3) == 3.0
        assert grace_period(None) == 2.0
        assert grace_period(True) == 2.0


class TestRunLevel:
    async def test_the_first_failure_in_the_order_given_is_raised(self):
        async def fail(message: str, after: float) -> None:
            await asyncio.sleep(after)
            raise RuntimeError(message)

        with pytest.raises(RuntimeError, match="first"):
            await run_level(
                [fail("first", 0.03), fail("second", 0.0)], ParallelFailureStrategy.WAIT_ALL
            )

    async def test_cancelling_the_level_cancels_its_steps(self):
        cancelled: list[str] = []

        async def step() -> None:
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                cancelled.append("step")
                raise

        level = asyncio.create_task(run_level([step(), step()], ParallelFailureStrategy.WAIT_ALL))
        await asyncio.sleep(0.02)
        level.cancel()
        with pytest.raises(asyncio.CancelledError):
            await level
        assert cancelled == ["step", "step"]
