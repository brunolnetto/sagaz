"""A deadline for a whole orchestrated saga (#568)."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

import pytest

from sagaz import Saga, SagaFailedError, SagaTimeoutError, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.decorators._deadline import deadline_seconds
from sagaz.core.exceptions import SagaDefinitionError
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage


def config(**more) -> SagaConfig:
    return SagaConfig(metrics=False, logging=False, default_max_retries=0, **more)


def order(log: list[str], *, slow: float = 0.5, default: object = None):
    """reserve (quick) -> charge (slow) -> ship."""

    class Order(Saga):
        saga_name = "order"
        deadline = default

        @action("reserve")
        async def reserve(self, ctx):
            log.append("reserve")
            return {"reserved": True}

        @compensate("reserve")
        async def release(self, ctx):
            log.append("undo:reserve")

        @action("charge", depends_on=["reserve"])
        async def charge(self, ctx):
            try:
                await asyncio.sleep(slow)
            except asyncio.CancelledError:
                log.append("charge cancelled")
                raise
            log.append("charge")

        @compensate("charge")
        async def refund(self, ctx):
            log.append("undo:charge")

        @action("ship", depends_on=["charge"])
        async def ship(self, ctx):
            log.append("ship")

    return Order


class TestExpiry:
    async def test_past_the_deadline_the_saga_is_cancelled_compensated_and_fails(self):
        log: list[str] = []
        started = time.monotonic()
        with pytest.raises(SagaFailedError) as raised:
            await order(log)(config=config()).run({}, deadline=0.05)
        assert time.monotonic() - started < 0.4  # it did not wait for the slow step
        assert log == ["reserve", "charge cancelled", "undo:reserve"]
        failure = raised.value
        assert failure.status.value == "rolled_back"
        assert isinstance(failure.__cause__, SagaTimeoutError)
        assert "did not finish within its deadline of 0.05s" in str(failure.__cause__)

    async def test_a_saga_within_its_deadline_is_unaffected(self):
        log: list[str] = []
        context = await order(log, slow=0.01)(config=config()).run({}, deadline=5)
        assert log == ["reserve", "charge", "ship"]
        assert context["reserved"] is True

    async def test_without_a_deadline_there_is_no_limit(self):
        log: list[str] = []
        await order(log, slow=0.05)(config=config()).run({})
        assert log == ["reserve", "charge", "ship"]

    async def test_the_cancelled_step_is_not_compensated(self):
        log: list[str] = []
        with pytest.raises(SagaFailedError):
            await order(log)(config=config()).run({}, deadline=0.05)
        assert "undo:charge" not in log  # it did not complete

    async def test_compensation_is_not_bounded_by_the_deadline(self):
        log: list[str] = []

        class Slow(Saga):
            saga_name = "slow-undo"

            @action("reserve")
            async def reserve(self, ctx):
                log.append("reserve")

            @compensate("reserve")
            async def release(self, ctx):
                await asyncio.sleep(0.15)  # longer than the deadline
                log.append("undo:reserve")

            @action("charge", depends_on=["reserve"])
            async def charge(self, ctx):
                await asyncio.sleep(5)

        with pytest.raises(SagaFailedError) as raised:
            await Slow(config=config()).run({}, deadline=0.05)
        assert log == ["reserve", "undo:reserve"]  # the compensation ran to its end
        assert raised.value.status.value == "rolled_back"

    async def test_a_steps_own_timeout_is_not_reported_as_the_deadline(self):
        class Timed(Saga):
            saga_name = "timed"

            @action("charge", timeout_seconds=0.02)
            async def charge(self, ctx):
                await asyncio.sleep(5)

        with pytest.raises(SagaFailedError) as raised:
            await Timed(config=config()).run({}, deadline=5)
        assert raised.value.failed_step == "charge"
        assert "Step 'charge' timed out" in str(raised.value.__cause__)

    async def test_parallel_steps_are_all_cancelled(self):
        log: list[str] = []

        class Fanout(Saga):
            saga_name = "fanout"

            @action("a")
            async def a(self, ctx):
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    log.append("a cancelled")
                    raise

            @action("b")
            async def b(self, ctx):
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    log.append("b cancelled")
                    raise

        with pytest.raises(SagaFailedError):
            await Fanout(config=config(failure_strategy="WAIT_ALL")).run({}, deadline=0.05)
        assert sorted(log) == ["a cancelled", "b cancelled"]

    async def test_the_outcome_is_stored(self):
        storage = InMemorySagaStorage()
        with pytest.raises(SagaFailedError):
            await order([])(config=config(storage=storage)).run({}, saga_id="o-1", deadline=0.05)
        assert str((await storage.load_saga_state("o-1"))["status"]).endswith("rolled_back")


class TestWhereItIsSet:
    async def test_the_class_declares_a_default(self):
        log: list[str] = []
        with pytest.raises(SagaFailedError) as raised:
            await order(log, default=0.05)(config=config()).run({})
        assert isinstance(raised.value.__cause__, SagaTimeoutError)

    async def test_the_argument_overrides_the_class(self):
        log: list[str] = []
        await order(log, slow=0.1, default=0.02)(config=config()).run({}, deadline=5)
        assert log == ["reserve", "charge", "ship"]

    async def test_a_timedelta_is_accepted(self):
        with pytest.raises(SagaFailedError):
            await order([])(config=config()).run({}, deadline=timedelta(milliseconds=50))

    @pytest.mark.parametrize(
        ("given", "seconds"),
        [(None, None), (30, 30.0), (1.5, 1.5), (timedelta(minutes=2), 120.0)],
    )
    def test_seconds_or_a_timedelta(self, given, seconds):
        assert deadline_seconds(given) == seconds

    @pytest.mark.parametrize("bad", [0, -1, "soon", True, timedelta(0)])
    async def test_a_deadline_that_is_not_a_positive_duration_is_refused(self, bad):
        log: list[str] = []
        with pytest.raises(SagaDefinitionError, match="deadline must be a positive number"):
            await order(log)(config=config()).run({}, deadline=bad)
        assert log == []  # refused before any step ran
