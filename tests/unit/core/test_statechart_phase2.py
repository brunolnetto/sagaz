"""StateChart phase 2: one chart region per step (ADR-040, #190)."""

from __future__ import annotations

import asyncio

import pytest
from statemachine.exceptions import TransitionNotAllowed

from sagaz.core.execution.step_statechart import (
    build_step_statechart,
    configuration_values,
    lifecycle_state,
    step_state_value,
    step_states,
    validate_configuration,
)
from sagaz.core.replay import ReplayConfig, SnapshotStrategy
from sagaz.core.saga import Saga
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage
from sagaz.core.types import ParallelFailureStrategy, SagaStatus


class Host:
    """What the chart's guards and callbacks read."""

    def __init__(self, steps=1, completed=0):
        self.steps = [object()] * steps
        self.completed_steps = [object()] * completed


class TestChart:
    def test_values_are_injective_for_any_step_name(self):
        names = ["a/b", "a%2Fb", "a.b", "pagamento ✓", "x/y/z"]
        values = {step_state_value(n) for n in names}
        assert len(values) == len(names)
        assert step_state_value("a/b", "executing") == "step/a%2Fb/executing"

    def test_classes_are_cached_and_names_must_be_unique(self):
        assert build_step_statechart(("a", "b")) is build_step_statechart(("a", "b"))
        with pytest.raises(ValueError, match="unique"):
            build_step_statechart(("a", "a"))

    async def test_the_phase_1_contract_holds_with_nested_states(self):
        chart = build_step_statechart(("a", "b"))(Host(steps=2))
        await chart.activate_initial_state()
        await chart.start()
        with pytest.raises(TransitionNotAllowed):  # an event its region cannot take
            await chart.send("s0__succeed")
        with pytest.raises(TransitionNotAllowed):  # a guard refuses: nothing completed
            await chart.fail()
        assert lifecycle_state(configuration_values(chart)) == "executing"

    async def test_regions_move_independently(self):
        chart = build_step_statechart(("a", "b"))(Host(steps=2, completed=1))
        await chart.activate_initial_state()
        await chart.start()
        await asyncio.gather(chart.send("s0__start"), chart.send("s1__start"))
        await chart.send("s0__succeed")
        await chart.send("s1__fail")
        await chart.fail()
        values = configuration_values(chart)
        assert lifecycle_state(values) == "compensating"
        assert step_states(("a", "b"), values) == {"a": "completed", "b": "failed"}
        validate_configuration(("a", "b"), values)

    @pytest.mark.parametrize(
        "broken",
        [
            ["active", "lifecycle", "steps", "step/a", "step/a/pending"],  # no lifecycle state
            [
                "active",
                "lifecycle",
                "executing",
                "compensating",
                "steps",
                "step/a",
                "step/a/pending",
            ],
            ["active", "lifecycle", "executing", "steps", "step/a"],  # step without a state
            [
                "active",
                "lifecycle",
                "executing",
                "steps",
                "step/a",
                "step/a/pending",
                "step/a/completed",
            ],
            ["active", "lifecycle", "executing", "steps", "step/a", "step/a/pending", "rogue"],
        ],
    )
    def test_foreign_configurations_are_refused(self, broken):
        with pytest.raises(ValueError):
            validate_configuration(("a",), broken)

    def test_flat_configurations_are_accepted(self):
        for flat in (["pending"], ["completed"], ["rolled_back"], ["failed"]):
            validate_configuration(("a",), flat)


# -- sagas --------------------------------------------------------------------------


def recorder():
    calls: list[str] = []
    configurations: dict[str, list[str]] = {}
    return calls, configurations


async def build(
    saga: Saga, calls, configurations, *, fail: str | None = None, dag=False, bad_undo=()
):
    names = ["reserve", "charge", "ship"]
    for i, name in enumerate(names):

        async def action(ctx, name=name):
            configurations[f"{name}:run"] = saga.state_configuration
            calls.append(f"do:{name}")
            if name == fail:
                msg = f"{name} failed"
                raise ValueError(msg)
            return name

        async def undo(result, ctx, name=name):
            configurations[f"{name}:undo"] = saga.state_configuration
            calls.append(f"undo:{name}")
            if name in bad_undo:
                msg = f"cannot undo {name}"
                raise RuntimeError(msg)

        deps = {"dependencies": set() if i == 0 else {names[i - 1]}} if dag else {}
        await saga.add_step(name, action, undo, max_retries=0, **deps)
    return saga


class TestSagaWithStepChart:
    async def test_a_successful_run(self):
        calls, cfgs = recorder()
        saga = await build(Saga("order", use_step_statechart=True), calls, cfgs)
        result = await saga.execute()
        assert result.status == SagaStatus.COMPLETED
        assert saga.state_configuration == ["completed"]  # flat once the saga ended
        running = step_states(("reserve", "charge", "ship"), cfgs["charge:run"])
        assert running == {"reserve": "completed", "charge": "executing", "ship": "pending"}
        assert saga.current_state == "Completed"

    async def test_a_compensated_failure(self):
        calls, cfgs = recorder()
        saga = await build(Saga("order", use_step_statechart=True), calls, cfgs, fail="ship")
        result = await saga.execute()
        assert result.status == SagaStatus.ROLLED_BACK
        assert saga.state_configuration == ["rolled_back"]
        assert calls == ["do:reserve", "do:charge", "do:ship", "undo:charge", "undo:reserve"]
        during = step_states(("reserve", "charge", "ship"), cfgs["reserve:undo"])
        assert during == {"reserve": "compensating", "charge": "compensated", "ship": "failed"}
        assert lifecycle_state(cfgs["reserve:undo"]) == "compensating"

    async def test_a_failed_compensation(self):
        calls, cfgs = recorder()
        saga = Saga("order", use_step_statechart=True)
        await build(saga, calls, cfgs, fail="ship", bad_undo=("charge",))
        result = await saga.execute()
        assert (result.status, saga.status) == (SagaStatus.FAILED, SagaStatus.FAILED)
        assert saga.state_configuration == ["failed"]
        assert step_states(("reserve", "charge", "ship"), cfgs["reserve:undo"])["charge"] == (
            "compensation_failed"
        )

    @pytest.mark.parametrize(
        "strategy",
        [
            ParallelFailureStrategy.FAIL_FAST,
            ParallelFailureStrategy.WAIT_ALL,
            ParallelFailureStrategy.FAIL_FAST_WITH_GRACE,
        ],
    )
    async def test_a_dag_batch_with_a_failure(self, strategy):
        saga = Saga("order", use_step_statechart=True, failure_strategy=strategy)
        observed: dict[str, list[str]] = {}

        async def first(ctx):
            return "ok"

        async def slow(ctx):
            observed["slow"] = saga.state_configuration
            await asyncio.sleep(0.2)
            return "late"

        async def boom(ctx):
            await asyncio.sleep(0.01)
            msg = "declined"
            raise ValueError(msg)

        async def undo(result, ctx):
            observed["undo"] = saga.state_configuration

        await saga.add_step("first", first, undo, dependencies=set(), max_retries=0)
        await saga.add_step("slow", slow, undo, dependencies={"first"}, max_retries=0)
        await saga.add_step("boom", boom, undo, dependencies={"first"}, max_retries=0)
        result = await saga.execute()
        assert result.status == SagaStatus.ROLLED_BACK
        assert saga.state_configuration == ["rolled_back"]
        names = ("first", "slow", "boom")
        assert step_states(names, observed["slow"])["boom"] in ("pending", "executing")
        during = step_states(names, observed["undo"])
        assert during["boom"] == "failed"
        assert during["slow"] in ("failed", "completed", "compensating", "compensated")

    async def test_the_flag_changes_nothing_but_the_configuration(self):
        results = {}
        for flag in (False, True):
            calls, cfgs = recorder()
            saga = await build(Saga("order", use_step_statechart=flag), calls, cfgs, fail="ship")
            result = await saga.execute()
            results[flag] = (result.status, result.completed_steps, calls, saga.status)
        assert results[False] == results[True]

    async def test_the_global_config_turns_it_on(self, monkeypatch):
        from sagaz.core.config import _config

        monkeypatch.setattr(_config, "_global_config", _config.SagaConfig(use_step_statechart=True))
        assert Saga("x").use_step_statechart is True
        assert Saga("x", use_step_statechart=False).use_step_statechart is False
        monkeypatch.setattr(_config, "_global_config", None)
        assert Saga("x").use_step_statechart is False


class TestReEntry:
    async def run_until_checkpoint(self):
        """A run that fails on ship and dies after compensating charge (a durable snapshot)."""
        storage = InMemorySnapshotStorage()
        calls, cfgs = recorder()
        saga = Saga(
            "order",
            use_step_statechart=True,
            replay_config=ReplayConfig(
                enable_snapshots=True, snapshot_strategy=SnapshotStrategy.AFTER_EACH_STEP
            ),
            snapshot_storage=storage,
        )
        await build(saga, calls, cfgs, fail="ship")
        await saga.execute()
        snapshots = await storage.list_snapshots(__import__("uuid").UUID(saga.saga_id))
        return next(
            s for s in snapshots if s.step_name == "charge" and "compensating" in s.configuration
        )

    async def fresh(self, calls, cfgs, **kwargs):
        return await build(Saga("order", use_step_statechart=True, **kwargs), calls, cfgs)

    async def test_compensation_resumes_where_it_stopped(self):
        checkpoint = await self.run_until_checkpoint()
        assert step_states(("reserve", "charge", "ship"), checkpoint.configuration) == {
            "reserve": "completed",
            "charge": "compensated",
            "ship": "failed",
        }
        calls, cfgs = recorder()
        saga = await self.fresh(calls, cfgs)
        await saga.restore_state(checkpoint.configuration, checkpoint.completed_steps)
        assert saga.status == SagaStatus.COMPENSATING
        assert saga.pending_compensations() == ["reserve"]  # charge already compensated
        result = await saga.resume_compensation()
        assert result.status == SagaStatus.ROLLED_BACK
        assert calls == ["undo:reserve"]
        assert saga.state_configuration == ["rolled_back"]

    async def test_a_run_interrupted_while_executing(self):
        names = ("reserve", "charge", "ship")
        configuration = [
            "active",
            "lifecycle",
            "executing",
            "steps",
            *(step_state_value(n) for n in names),
            step_state_value("reserve", "completed"),
            step_state_value("charge", "executing"),
            step_state_value("ship", "pending"),
        ]
        calls, cfgs = recorder()
        saga = await self.fresh(calls, cfgs)
        await saga.restore_state(configuration, ["reserve"])
        assert saga.in_doubt_steps() == ["charge"]  # reported, not compensated
        result = await saga.resume_compensation()
        assert result.status == SagaStatus.ROLLED_BACK
        assert calls == ["undo:reserve"]

    async def test_nothing_to_compensate(self):
        names = ("reserve", "charge", "ship")
        configuration = [
            "active",
            "lifecycle",
            "executing",
            "steps",
            *(step_state_value(n) for n in names),
            *(step_state_value(n, "pending") for n in names),
        ]
        calls, cfgs = recorder()
        saga = await self.fresh(calls, cfgs)
        await saga.restore_state(configuration, [])
        result = await saga.resume_compensation()
        assert result.status == SagaStatus.ROLLED_BACK
        assert calls == []
        assert saga.state_configuration == ["rolled_back"]

    async def test_a_compensation_that_fails_again(self):
        checkpoint = await self.run_until_checkpoint()
        calls, cfgs = recorder()
        saga = Saga("order", use_step_statechart=True)
        await build(saga, calls, cfgs, bad_undo=("reserve",))
        await saga.restore_state(checkpoint.configuration, checkpoint.completed_steps)
        result = await saga.resume_compensation()
        assert (result.status, saga.state_configuration) == (SagaStatus.FAILED, ["failed"])

    async def test_what_cannot_be_restored(self):
        checkpoint = await self.run_until_checkpoint()
        calls, cfgs = recorder()
        off = await build(Saga("order"), calls, cfgs)
        with pytest.raises(ValueError, match="use_step_statechart"):
            await off.restore_state(checkpoint.configuration, checkpoint.completed_steps)
        with pytest.raises(ValueError, match="needs a run restored"):
            await off.resume_compensation()
        saga = await self.fresh(calls, cfgs)
        with pytest.raises(ValueError, match="not in this saga"):
            await saga.restore_state(checkpoint.configuration, ["nope"])
        with pytest.raises(ValueError):
            await saga.restore_state(["active", "lifecycle"], [])
        await saga.restore_state(["rolled_back"], [])
        with pytest.raises(ValueError, match="already ended"):
            await saga.resume_compensation()


async def test_replayed_steps_are_adopted():
    """A run restarted from a snapshot marks the steps it skips as completed."""
    from uuid import UUID

    storage = InMemorySnapshotStorage()
    calls, cfgs = recorder()
    saga = Saga(
        "order",
        use_step_statechart=True,
        replay_config=ReplayConfig(
            enable_snapshots=True, snapshot_strategy=SnapshotStrategy.AFTER_EACH_STEP
        ),
        snapshot_storage=storage,
    )
    await build(saga, calls, cfgs, fail="ship")
    await saga.execute()
    snapshots = await storage.list_snapshots(UUID(saga.saga_id))
    after_charge = next(s for s in snapshots if s.step_name == "charge" and s.status == "executing")
    calls2, cfgs2 = recorder()
    replay = await build(Saga("order", use_step_statechart=True), calls2, cfgs2)
    result = await replay.execute_from_snapshot(after_charge)
    assert result.status == SagaStatus.COMPLETED
    assert calls2 == ["do:ship"]
    adopted = step_states(("reserve", "charge", "ship"), cfgs2["ship:run"])
    assert adopted == {"reserve": "completed", "charge": "completed", "ship": "executing"}
