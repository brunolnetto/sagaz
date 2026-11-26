"""Forward recovery: a step that fails after a pivot (#570, ADR-023)."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from sagaz import (
    RecoveryAction,
    Saga,
    SagaFailedError,
    SagaStatus,
    action,
    compensate,
    forward_recovery,
)
from sagaz.core.config import SagaConfig
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage


def config(**more) -> SagaConfig:
    return SagaConfig(metrics=False, logging=False, default_max_retries=0, **more)


def order(log: list[str], answers: list[object] | None = None, *, ship_failures: int = 99, **meta):
    """reserve -> charge (pivot) -> ship -> notify. ship fails ``ship_failures`` times.

    *answers* are what the forward recovery handler of ship returns, in turn; without
    them, ship has no handler.
    """

    class Order(Saga):
        saga_name = "order"

        @action("reserve")
        async def reserve(self, ctx):
            log.append("reserve")

        @compensate("reserve")
        async def release(self, ctx):
            log.append("undo:reserve")

        @action("charge", depends_on=["reserve"], pivot=True)
        async def charge(self, ctx):
            log.append("charge")

        @compensate("charge")
        async def refund(self, ctx):
            log.append("undo:charge")

        @action("pack", depends_on=["charge"])
        async def pack(self, ctx):
            log.append("pack")

        @compensate("pack")
        async def unpack(self, ctx):
            log.append("undo:pack")

        @action("ship", depends_on=["pack"])
        async def ship(self, ctx):
            log.append(f"ship via {ctx.get('carrier', 'primary')}")
            if log.count("ship via primary") + log.count("ship via backup") <= ship_failures:
                msg = "no truck"
                raise RuntimeError(msg)
            return {"shipped": True}

        @action("notify", depends_on=["ship"])
        async def notify(self, ctx):
            log.append("notify")

        if answers is not None:

            @forward_recovery("ship", **meta)
            async def recover_ship(self, ctx, error):
                log.append(f"recover: {error}")
                answer = answers.pop(0) if answers else RecoveryAction.MANUAL_INTERVENTION
                if not callable(answer):
                    return answer
                answer = answer(ctx)
                return await answer if inspect.isawaitable(answer) else answer

    return Order


async def failed(saga: Saga, **run) -> SagaFailedError:
    with pytest.raises(SagaFailedError) as raised:
        await saga.run({}, **run)
    return raised.value


class TestWithoutAHandler:
    async def test_what_is_reversible_is_undone_and_the_saga_is_partially_committed(self):
        log: list[str] = []
        failure = await failed(order(log)(config=config()))
        assert failure.status == SagaStatus.PARTIALLY_COMMITTED
        assert failure.failed_step == "ship"
        # pack came after the pivot and is undone; the pivot and its ancestor stay done
        assert log == ["reserve", "charge", "pack", "ship via primary", "undo:pack"]

    async def test_a_failure_before_any_pivot_still_rolls_back(self):
        log: list[str] = []

        class Early(Saga):
            saga_name = "early"

            @action("reserve")
            async def reserve(self, ctx):
                log.append("reserve")

            @compensate("reserve")
            async def release(self, ctx):
                log.append("undo:reserve")

            @action("charge", depends_on=["reserve"], pivot=True)
            async def charge(self, ctx):
                msg = "card declined"
                raise RuntimeError(msg)

        failure = await failed(Early(config=config()))
        assert failure.status == SagaStatus.ROLLED_BACK
        assert log == ["reserve", "undo:reserve"]

    async def test_the_status_is_stored_and_told_to_listeners(self):
        seen: list[str] = []

        class Listener:
            async def on_saga_failed(self, saga_name, saga_id, ctx, error):
                seen.append(error.status.value)

        storage = InMemorySagaStorage()
        saga = order([])(config=config(storage=storage))
        saga.add_listener(Listener())
        await failed(saga, saga_id="o-1")
        assert seen == ["partially_committed"]
        assert str((await storage.load_saga_state("o-1"))["status"]).endswith("partially_committed")


class TestRetry:
    async def test_retry_runs_the_step_again_until_it_succeeds(self):
        log: list[str] = []
        answers = [RecoveryAction.RETRY, RecoveryAction.RETRY]
        context = await order(log, answers, ship_failures=2)(config=config()).run({})
        assert context["shipped"] is True
        assert log.count("ship via primary") == 3
        assert log[-1] == "notify"  # the saga went on and completed
        assert not [entry for entry in log if entry.startswith("undo")]

    async def test_retry_with_alternate_sees_what_the_handler_changed(self):
        log: list[str] = []

        def use_backup(ctx):
            ctx["carrier"] = "backup"
            return RecoveryAction.RETRY_WITH_ALTERNATE

        context = await order(log, [use_backup], ship_failures=1)(config=config()).run({})
        assert "ship via backup" in log
        assert context["shipped"] is True

    async def test_retries_that_run_out_stop_the_saga_for_a_person(self):
        log: list[str] = []
        answers = [RecoveryAction.RETRY] * 10
        failure = await failed(order(log, answers, max_retries=2)(config=config()))
        assert failure.status == SagaStatus.FORWARD_RECOVERY
        assert log.count("ship via primary") == 3  # the first run and two retries
        assert not [entry for entry in log if entry.startswith("undo")]  # nothing is compensated


class TestSkip:
    async def test_skip_leaves_the_step_failed_and_the_dependents_run(self):
        log: list[str] = []

        def skip(ctx):
            ctx["shipped"] = False  # what notify needs
            return RecoveryAction.SKIP

        context = await order(log, [skip])(config=config()).run({})
        assert log[-1] == "notify"
        assert context["shipped"] is False
        assert "__ship_completed" not in context

    async def test_a_skipped_step_is_not_compensated_if_the_saga_fails_later(self):
        log: list[str] = []

        class Later(order(log, [RecoveryAction.SKIP])):
            @compensate("ship")
            async def unship(self, ctx):
                log.append("undo:ship")

            @action("invoice", depends_on=["notify"])
            async def invoice(self, ctx):
                msg = "ledger down"
                raise RuntimeError(msg)

        failure = await failed(Later(config=config()))
        assert failure.failed_step == "invoice"
        assert "undo:ship" not in log  # it never completed
        assert failure.status == SagaStatus.PARTIALLY_COMMITTED


class TestStoppingForward:
    async def test_manual_intervention_compensates_nothing(self):
        log: list[str] = []
        storage = InMemorySagaStorage()
        saga = order(log, [RecoveryAction.MANUAL_INTERVENTION])(config=config(storage=storage))
        failure = await failed(saga, saga_id="o-1")
        assert failure.status == SagaStatus.FORWARD_RECOVERY
        assert failure.failed_step == "ship"
        assert not [entry for entry in log if entry.startswith("undo")]
        assert str((await storage.load_saga_state("o-1"))["status"]).endswith("forward_recovery")

    async def test_a_handler_that_raises_stops_the_saga_the_same_way(self):
        log: list[str] = []

        def broken(ctx):
            msg = "handler bug"
            raise ValueError(msg)

        failure = await failed(order(log, [broken])(config=config()))
        assert failure.status == SagaStatus.FORWARD_RECOVERY
        assert "no truck" in str(failure.__cause__)  # the step's error, not the handler's

    async def test_an_answer_that_is_no_recovery_action_stops_the_saga_the_same_way(self):
        failure = await failed(order([], ["retry please"])(config=config()))
        assert failure.status == SagaStatus.FORWARD_RECOVERY

    async def test_a_handler_slower_than_its_timeout_stops_the_saga_the_same_way(self):
        async def slow(ctx):
            await asyncio.sleep(5)

        failure = await failed(order([], [slow], timeout_seconds=0.05)(config=config()))
        assert failure.status == SagaStatus.FORWARD_RECOVERY


class TestCompensatePivot:
    async def test_everything_is_rolled_back_the_pivot_included(self):
        log: list[str] = []
        failure = await failed(order(log, [RecoveryAction.COMPENSATE_PIVOT])(config=config()))
        assert failure.status == SagaStatus.ROLLED_BACK
        undone = [entry for entry in log if entry.startswith("undo")]
        assert undone == ["undo:pack", "undo:charge", "undo:reserve"]


class TestWhenItApplies:
    async def test_a_handler_is_not_asked_when_its_step_fails_before_the_pivot(self):
        log: list[str] = []

        class Before(Saga):
            saga_name = "before"

            @action("reserve")
            async def reserve(self, ctx):
                msg = "out of stock"
                raise RuntimeError(msg)

            @forward_recovery("reserve")
            async def recover(self, ctx, error):
                log.append("asked")
                return RecoveryAction.SKIP

            @action("charge", depends_on=["reserve"], pivot=True)
            async def charge(self, ctx): ...

        failure = await failed(Before(config=config()))
        assert log == []
        assert failure.status == SagaStatus.ROLLED_BACK

    async def test_a_step_in_a_branch_that_does_not_follow_the_pivot_is_not_recovered(self):
        log: list[str] = []

        class Branches(Saga):
            saga_name = "branches"

            @action("charge", pivot=True)
            async def charge(self, ctx):
                log.append("charge")

            @action("audit")
            async def audit(self, ctx):
                await asyncio.sleep(0.02)  # after the pivot in time, not in the graph
                msg = "audit down"
                raise RuntimeError(msg)

            @forward_recovery("audit")
            async def recover(self, ctx, error):
                log.append("asked")
                return RecoveryAction.SKIP

        failure = await failed(Branches(config=config(failure_strategy="WAIT_ALL")))
        assert "asked" not in log
        assert failure.status == SagaStatus.PARTIALLY_COMMITTED  # the pivot stays done
