"""One failure contract, and definitions checked before anything runs (#536)."""

from __future__ import annotations

import asyncio
from types import MappingProxyType

import pytest

from sagaz import Saga, SagaConfig, action, compensate
from sagaz.core.exceptions import (
    SagaDefinitionError,
    SagaFailedError,
    SagaTimeoutError,
)
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.types import SagaStatus


def config(storage=None):
    return SagaConfig(storage=storage, metrics=False, logging=False)


def order_saga(*, charge_error=None, release_error=None, slow=False):
    class Order(Saga):
        saga_name = "order"

        @action("reserve", max_retries=0)
        async def reserve(self, ctx):
            return {"reserved": True}

        @compensate("reserve")
        async def release(self, ctx):
            if release_error:
                raise release_error

        @action("charge", depends_on=["reserve"], max_retries=0, timeout_seconds=0.05)
        async def charge(self, ctx):
            if slow:
                await asyncio.sleep(1)
            if charge_error:
                raise charge_error

    return Order


class TestSagaFailedError:
    async def test_a_rolled_back_saga(self):
        cause = ValueError("card declined")
        with pytest.raises(SagaFailedError, match="card declined") as raised:
            await order_saga(charge_error=cause)(config=config()).run({}, saga_id="o-1")
        error = raised.value
        assert (error.saga_id, error.saga_name, error.failed_step) == ("o-1", "order", "charge")
        assert error.status == SagaStatus.ROLLED_BACK
        assert error.compensation_errors == {}
        assert error.__cause__ is cause
        assert "rolled back" in str(error)

    async def test_a_failed_compensation(self):
        undo = RuntimeError("warehouse offline")
        saga = order_saga(charge_error=ValueError("declined"), release_error=undo)
        with pytest.raises(SagaFailedError) as raised:
            await saga(config=config()).run({})
        assert raised.value.status == SagaStatus.FAILED
        assert raised.value.compensation_errors == {"reserve": undo}
        assert "compensation failed for ['reserve']" in str(raised.value)

    async def test_a_timeout_is_a_saga_timeout_error_and_a_timeout_error(self):
        with pytest.raises(SagaFailedError) as raised:
            await order_saga(slow=True)(config=config()).run({})
        cause = raised.value.__cause__
        assert isinstance(cause, SagaTimeoutError)
        assert isinstance(cause, TimeoutError)
        assert "timed out after 0.05s" in str(cause)

    async def test_the_stored_outcome_matches_the_error(self):
        storage = InMemorySagaStorage()
        with pytest.raises(SagaFailedError) as raised:
            await order_saga(charge_error=ValueError("x"))(config=config(storage)).run(
                {}, saga_id="o-2"
            )
        stored = await storage.load_saga_state("o-2")
        assert stored["status"] == raised.value.status.value


class TestDefinitionErrors:
    def test_compensate_of_no_step(self):
        class Bad(Saga):
            @action("a")
            async def a(self, ctx): ...

            @compensate("b")
            async def undo_b(self, ctx): ...

        with pytest.raises(SagaDefinitionError, match=r"@compensate\('b'\) on undo_b\(\)"):
            Bad()

    def test_two_steps_with_one_name(self):
        class Bad(Saga):
            @action("a")
            async def first(self, ctx): ...

            @action("a")
            async def second(self, ctx): ...

        with pytest.raises(SagaDefinitionError, match="two steps are named 'a'"):
            Bad()

    def test_two_compensations_of_one_step(self):
        class Bad(Saga):
            @action("a")
            async def a(self, ctx): ...

            @compensate("a")
            async def undo1(self, ctx): ...

            @compensate("a")
            async def undo2(self, ctx): ...

        with pytest.raises(SagaDefinitionError, match="two @compensate"):
            Bad()

    async def test_an_unknown_dependency_is_named_and_nothing_runs(self):
        ran: list[str] = []
        storage = InMemorySagaStorage()

        class Bad(Saga):
            @action("a")
            async def a(self, ctx):
                ran.append("a")

            @action("b", depends_on=["zzz"])
            async def b(self, ctx): ...

        with pytest.raises(
            SagaDefinitionError, match=r"'b' depends on unknown step\(s\) \['zzz'\]"
        ):
            await Bad(config=config(storage)).run({}, saga_id="d")
        assert ran == []
        assert await storage.load_saga_state("d") is None  # not stored either

    async def test_a_cycle_shows_its_path(self):
        saga = Saga(name="loop", config=config())
        saga.add_step("a", _noop, depends_on=["c"])
        saga.add_step("b", _noop, depends_on=["a"])
        saga.add_step("c", _noop, depends_on=["b"])
        with pytest.raises(SagaDefinitionError, match="dependency cycle: a -> b -> c -> a"):
            await saga.run({})

    async def test_cycles_are_still_value_errors(self):
        saga = Saga(name="loop", config=config())
        saga.add_step("a", _noop, depends_on=["a"])
        with pytest.raises(ValueError, match="dependency cycle"):
            await saga.run({})


async def _noop(ctx):
    return None


class TestRunInputs:
    async def test_sync_steps_and_compensations_work(self):
        undone: list[str] = []

        class Sync(Saga):
            saga_name = "sync"

            @action("a", max_retries=0)
            def a(self, ctx):
                return {"a": 1}

            @compensate("a")
            def undo_a(self, ctx):
                undone.append("a")

            @action("b", depends_on=["a"], max_retries=0)
            def b(self, ctx):
                msg = "no"
                raise ValueError(msg)

        with pytest.raises(SagaFailedError):
            await Sync(config=config()).run({})
        assert undone == ["a"]

        saga = Saga(name="sync-add-step", config=config())
        saga.add_step("only", lambda ctx: {"done": True})
        assert (await saga.run({}))["done"] is True

    async def test_a_non_mapping_context_is_refused(self):
        with pytest.raises(TypeError, match="initial_context must be a dict.*got list"):
            await order_saga()(config=config()).run(["not", "a", "dict"])

    async def test_any_mapping_is_accepted(self):
        result = await order_saga()(config=config()).run(MappingProxyType({"k": 1}))
        assert result["k"] == 1
