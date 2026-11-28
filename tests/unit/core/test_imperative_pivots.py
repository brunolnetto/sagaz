"""add_step() declares pivots and forward recovery (#678); parallel pivots warn (#679)."""

from __future__ import annotations

import warnings
from typing import Any

import pytest

from sagaz import (
    ParallelPivotsWarning,
    RecoveryAction,
    Saga,
    SagaConfig,
    SagaFailedError,
    SagaStatus,
    action,
    forward_recovery,
)
from sagaz.core.decorators._validation import parallel_pivots


def quiet() -> SagaConfig:
    return SagaConfig(metrics=False, logging=False)


def step(log: list[str], name: str, *, fails: bool = False) -> Any:
    async def run(ctx: dict[str, Any]) -> None:
        if fails and not ctx.get("fixed"):
            raise RuntimeError(name)
        log.append(name)

    return run


def undo(log: list[str], name: str) -> Any:
    async def run(ctx: dict[str, Any]) -> None:
        log.append(f"undo {name}")

    return run


def order(log: list[str], **ship: Any) -> Saga:
    saga = Saga(name="order", config=quiet())
    saga.add_step("reserve", step(log, "reserve"), undo(log, "reserve"))
    saga.add_step("charge", step(log, "charge"), depends_on=["reserve"], pivot=True)
    saga.add_step("label", step(log, "label"), undo(log, "label"), depends_on=["charge"])
    saga.add_step(
        "ship", step(log, "ship", fails=True), depends_on=["label"], max_retries=0, **ship
    )
    return saga


class TestAddStepPivot:
    async def test_a_failure_after_an_imperative_pivot_is_partially_committed(self):
        log: list[str] = []
        with pytest.raises(SagaFailedError) as failure:
            await order(log).run({})
        assert failure.value.status == SagaStatus.PARTIALLY_COMMITTED
        assert log == ["reserve", "charge", "label", "undo label"]  # reserve stays

    def test_the_pivot_is_listed(self):
        assert order([]).get_pivot_steps() == ["charge"]

    async def test_a_plain_function_recovers_forward(self):
        log: list[str] = []
        asked: list[str] = []

        async def recover(ctx: dict[str, Any], error: Exception) -> RecoveryAction:
            asked.append(str(error))
            ctx["fixed"] = True
            return RecoveryAction.RETRY

        await order(log, forward_recovery=recover).run({})
        assert asked == ["ship"]
        assert log == ["reserve", "charge", "label", "ship"]

    async def test_a_sync_handler_and_a_request_for_a_person(self):
        def recover(ctx: dict[str, Any], error: Exception) -> RecoveryAction:
            return RecoveryAction.MANUAL_INTERVENTION

        log: list[str] = []
        with pytest.raises(SagaFailedError) as failure:
            await order(log, forward_recovery=recover).run({})
        assert failure.value.status == SagaStatus.FORWARD_RECOVERY
        assert "undo label" not in log

    async def test_a_decorated_function_keeps_its_retry_limit(self):
        calls: list[int] = []

        @forward_recovery("ship", max_retries=1)
        async def recover(ctx: dict[str, Any], error: Exception) -> RecoveryAction:
            calls.append(1)
            return RecoveryAction.RETRY  # never fixes it

        with pytest.raises(SagaFailedError) as failure:
            await order([], forward_recovery=recover).run({})
        assert failure.value.status == SagaStatus.FORWARD_RECOVERY
        assert len(calls) == 2  # asked, retried once, asked again: the limit is reached

    async def test_the_handler_is_not_asked_before_the_pivot(self):
        asked: list[str] = []

        async def recover(ctx: dict[str, Any], error: Exception) -> RecoveryAction:
            asked.append("asked")
            return RecoveryAction.RETRY

        saga = Saga(name="early", config=quiet())
        saga.add_step("reserve", step([], "reserve"))
        saga.add_step(
            "check",
            step([], "check", fails=True),
            depends_on=["reserve"],
            max_retries=0,
            forward_recovery=recover,
        )
        with pytest.raises(SagaFailedError) as failure:
            await saga.run({})
        assert failure.value.status == SagaStatus.ROLLED_BACK
        assert asked == []


def saga_of(*steps: tuple[str, list[str], bool]) -> Saga:
    saga = Saga(name="graph", config=quiet())
    for name, depends_on, pivot in steps:
        saga.add_step(name, step([], name), depends_on=depends_on, pivot=pivot)
    return saga


def caught(saga: Saga) -> list[str]:
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        saga.get_execution_order()
        saga.get_execution_order()  # the same definition warns once
    return [str(w.message) for w in seen if issubclass(w.category, ParallelPivotsWarning)]


class TestParallelPivots:
    def test_pivots_in_series_do_not_warn(self):
        saga = saga_of(
            ("a", [], False), ("p1", ["a"], True), ("b", ["p1"], False), ("p2", ["b"], True)
        )
        assert parallel_pivots(saga.get_steps()) == []
        assert caught(saga) == []

    def test_pivots_in_parallel_branches_warn_once_naming_both(self):
        saga = saga_of(("r", [], False), ("p1", ["r"], True), ("p2", ["r"], True))
        (message,) = caught(saga)
        assert "'p1' and 'p2' are in parallel branches" in message
        assert "saga 'graph'" in message

    def test_a_pivot_far_up_another_branch_is_still_parallel(self):
        saga = saga_of(
            ("r", [], False),
            ("p1", ["r"], True),
            ("x", ["p1"], False),
            ("y", ["r"], False),
            ("p2", ["y"], True),
        )
        assert parallel_pivots(saga.get_steps()) == [("p1", "p2")]

    def test_three_parallel_pivots_are_three_pairs(self):
        saga = saga_of(("p1", [], True), ("p2", [], True), ("p3", [], True))
        assert parallel_pivots(saga.get_steps()) == [("p1", "p2"), ("p1", "p3"), ("p2", "p3")]

    def test_a_single_pivot_and_no_pivot_do_not_warn(self):
        assert caught(saga_of(("a", [], False), ("p", ["a"], True))) == []
        assert caught(saga_of(("a", [], False), ("b", [], False))) == []

    def test_a_step_added_later_is_checked_again(self):
        saga = saga_of(("r", [], False), ("p1", ["r"], True))
        assert caught(saga) == []
        saga.add_step("p2", step([], "p2"), depends_on=["r"], pivot=True)
        assert len(caught(saga)) == 1

    def test_a_declarative_saga_warns_too(self):
        class Deploy(Saga):
            saga_name = "deploy"

            @action("edge", pivot=True)
            async def edge(self, ctx: dict[str, Any]) -> None: ...

            @action("cloud", pivot=True)
            async def cloud(self, ctx: dict[str, Any]) -> None: ...

        (message,) = caught(Deploy(config=quiet()))
        assert "saga 'deploy'" in message

    async def test_the_saga_still_runs_and_the_warning_can_be_silenced(self):
        saga = saga_of(("p1", [], True), ("p2", [], True))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            warnings.filterwarnings("ignore", category=ParallelPivotsWarning)
            await saga.run({})
