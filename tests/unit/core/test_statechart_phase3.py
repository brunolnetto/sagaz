"""StateChart phase 3: the declarative engine and pivot/taint states (ADR-040, #522)."""

from __future__ import annotations

import asyncio

import pytest
from statemachine.exceptions import TransitionNotAllowed

from sagaz.core.config import SagaConfig
from sagaz.core.decorators import Saga, compensate, step
from sagaz.core.execution.step_statechart import (
    build_step_statechart,
    configuration_values,
    step_state_value,
    step_states,
)
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.types import SagaStatus

NAMES = ("reserve", "charge", "ship")


class Host:
    steps = [object()]
    completed_steps = [object()]


class TestPivotStates:
    async def chart(self, pivots=frozenset()):
        chart = build_step_statechart(("a", "b"), frozenset(pivots))(Host())
        await chart.activate_initial_state()
        await chart.start()
        for i in (0, 1):
            await chart.send(f"s{i}__start")
            await chart.send(f"s{i}__succeed")
        return chart

    async def test_a_tainted_step_cannot_be_compensated(self):
        chart = await self.chart()
        await chart.send("s0__taint")
        assert step_states(("a", "b"), configuration_values(chart))["a"] == "tainted"
        with pytest.raises(TransitionNotAllowed):
            await chart.send("s0__compensate")
        await chart.send("s1__compensate")  # an untainted step still can

    async def test_a_pivot_cannot_be_compensated(self):
        chart = await self.chart(pivots={"b"})
        with pytest.raises(TransitionNotAllowed):
            await chart.send("s1__compensate")
        await chart.send("s0__compensate")

    def test_pivots_are_part_of_the_chart_class(self):
        plain = build_step_statechart(("a", "b"))
        assert build_step_statechart(("a", "b"), frozenset({"b"})) is not plain
        assert build_step_statechart(("a", "b"), frozenset({"b"})).pivots == frozenset({"b"})
        with pytest.raises(ValueError, match="pivots must be steps"):
            build_step_statechart(("a",), frozenset({"z"}))


# -- declarative sagas ----------------------------------------------------------------


def order_saga(calls, seen, *, fail="ship", pivot=False, bad_undo=(), hang_undo=None):
    """reserve -> charge (pivot?) -> notify -> ship."""

    class Order(Saga):
        saga_name = "order"

        @step("reserve")
        async def reserve(self, ctx):
            calls.append("do:reserve")

        @step("charge", depends_on=["reserve"], pivot=pivot)
        async def charge(self, ctx):
            calls.append("do:charge")

        @step("notify", depends_on=["charge"])
        async def notify(self, ctx):
            calls.append("do:notify")

        @step("ship", depends_on=["notify"])
        async def ship(self, ctx):
            seen["ship"] = self.get_step_states()
            calls.append("do:ship")
            if fail == "ship":
                msg = "no truck"
                raise ValueError(msg)

        async def _undo(self, name):
            seen[f"undo:{name}"] = self.get_step_states()
            calls.append(f"undo:{name}")
            if name == hang_undo:
                await asyncio.Event().wait()
            if name in bad_undo:
                msg = f"cannot undo {name}"
                raise RuntimeError(msg)

        @compensate("reserve")
        async def undo_reserve(self, ctx):
            await self._undo("reserve")

        @compensate("charge")
        async def undo_charge(self, ctx):
            await self._undo("charge")

        @compensate("notify")
        async def undo_notify(self, ctx):
            await self._undo("notify")

    return Order


def config(storage=None, flag=True):
    return SagaConfig(storage=storage, use_step_statechart=flag, metrics=False, logging=False)


class TestDeclarative:
    async def test_a_successful_run(self):
        calls, seen = [], {}
        saga = order_saga(calls, seen, fail=None)(config=config())
        await saga.run({})
        assert saga.state_configuration == ["completed"]
        assert seen["ship"] == {
            "reserve": "completed",
            "charge": "completed",
            "notify": "completed",
            "ship": "executing",
        }

    async def test_a_compensated_failure_is_stored_with_its_configuration(self):
        storage, calls, seen = InMemorySagaStorage(), [], {}
        saga = order_saga(calls, seen)(config=config(storage))
        with pytest.raises(ValueError, match="no truck"):
            await saga.run({}, saga_id="o-1")
        assert calls[-3:] == ["undo:notify", "undo:charge", "undo:reserve"]
        assert seen["undo:reserve"]["charge"] == "compensated"
        assert seen["undo:reserve"]["ship"] == "failed"
        stored = await storage.load_saga_state("o-1")
        assert (stored["status"], stored["configuration"]) == ("rolled_back", ["rolled_back"])

    @pytest.mark.parametrize("flag", [False, True])
    async def test_a_failed_compensation_is_stored_as_failed(self, flag):
        storage = InMemorySagaStorage()
        saga = order_saga([], {}, bad_undo=("charge",))(config=config(storage, flag))
        with pytest.raises(ValueError):
            await saga.run({}, saga_id="o-2")
        stored = await storage.load_saga_state("o-2")
        assert stored["status"] == "failed"  # was rolled_back
        assert saga.state_configuration == (["failed"] if flag else [])

    async def test_a_pivot_taints_its_ancestors(self):
        calls, seen = [], {}
        saga = order_saga(calls, seen, pivot=True)(config=config())
        with pytest.raises(ValueError):
            await saga.run({})
        assert seen["ship"]["reserve"] == "tainted"
        assert seen["ship"]["charge"] == "completed"  # the pivot itself
        assert [c for c in calls if c.startswith("undo")] == ["undo:notify"]
        assert saga.state_configuration == ["rolled_back"]

    async def test_the_flag_changes_nothing_but_the_configuration(self):
        outcomes = {}
        for flag in (False, True):
            for pivot in (False, True):
                calls = []
                storage = InMemorySagaStorage()
                saga = order_saga(calls, {}, pivot=pivot)(config=config(storage, flag))
                with pytest.raises(ValueError):
                    await saga.run({}, saga_id="o")
                stored = await storage.load_saga_state("o")
                outcomes[flag, pivot] = (calls, stored["status"], stored["steps"][0]["status"])
        assert outcomes[False, False] == outcomes[True, False]
        assert outcomes[False, True] == outcomes[True, True]

    def test_where_the_flag_comes_from(self):
        cls = order_saga([], {})
        assert cls(config=config(flag=True)).use_step_statechart is True
        assert cls(config=config(flag=False)).use_step_statechart is False
        assert cls(config=config(flag=True), use_step_statechart=False).use_step_statechart is False

        class On(cls):
            use_step_statechart = True

        assert On(config=config(flag=False)).use_step_statechart is True

    async def test_an_empty_saga_runs_without_a_chart(self):
        saga = Saga("empty", config=config())
        assert await saga.run({}) is not None
        assert saga.state_configuration == []


class TestResume:
    async def interrupted(self, pivot=False):
        """A run cancelled while compensating reserve, after notify and charge were."""
        storage = InMemorySagaStorage()
        saga = order_saga([], {}, pivot=pivot, hang_undo="reserve")(config=config(storage))
        task = asyncio.create_task(saga.run({"order": 7}, saga_id="o-9"))
        for _ in range(200):
            await asyncio.sleep(0.005)
            if saga.get_step_states().get("reserve") == "compensating":
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return storage

    async def test_a_compensation_resumes_from_its_last_checkpoint(self):
        storage = await self.interrupted()
        stored = await storage.load_saga_state("o-9")
        assert stored["status"] == "compensating"
        assert step_states(("reserve", "charge", "notify", "ship"), stored["configuration"]) == {
            "reserve": "completed",
            "charge": "compensated",
            "notify": "compensated",
            "ship": "failed",
        }
        calls = []
        saga = order_saga(calls, {})(config=config(storage))
        assert await saga.resume_compensation("o-9") == SagaStatus.ROLLED_BACK
        assert calls == ["undo:reserve"]
        stored = await storage.load_saga_state("o-9")
        assert (stored["status"], stored["configuration"]) == ("rolled_back", ["rolled_back"])
        assert stored["context"]["order"] == 7

    async def test_resuming_an_executing_run_with_a_pivot(self):
        storage = InMemorySagaStorage()
        names = ("reserve", "charge", "notify", "ship")
        states = {"reserve": "tainted", "charge": "completed", "notify": "completed"}
        states["ship"] = "executing"
        configuration = [
            "active",
            "lifecycle",
            "executing",
            "steps",
            *(step_state_value(n) for n in names),
            *(step_state_value(n, s) for n, s in states.items()),
        ]
        await storage.save_saga_state(
            "o-5", "order", SagaStatus.EXECUTING, [], {}, configuration=configuration
        )
        calls = []
        saga = order_saga(calls, {}, pivot=True)(config=config(storage))
        assert await saga.resume_compensation("o-5") == SagaStatus.ROLLED_BACK
        assert calls == ["undo:notify"]  # reserve tainted, charge the pivot, ship in doubt

    async def test_a_resumed_compensation_that_fails(self):
        storage = await self.interrupted()
        saga = order_saga([], {}, bad_undo=("reserve",))(config=config(storage))
        assert await saga.resume_compensation("o-9") == SagaStatus.FAILED
        assert (await storage.load_saga_state("o-9"))["status"] == "failed"

    async def test_what_cannot_be_resumed(self):
        storage = await self.interrupted()
        cls = order_saga([], {})
        with pytest.raises(ValueError, match="use_step_statechart"):
            await cls(config=config(storage, flag=False)).resume_compensation("o-9")
        no_storage = cls(config=config())
        no_storage._config.storage = None
        with pytest.raises(ValueError, match="SagaConfig.storage"):
            await no_storage.resume_compensation("o-9")
        with pytest.raises(ValueError, match="no stored state"):
            await cls(config=config(storage)).resume_compensation("nope")
        await cls(config=config(storage)).resume_compensation("o-9")
        with pytest.raises(ValueError, match="already ended"):
            await cls(config=config(storage)).resume_compensation("o-9")
