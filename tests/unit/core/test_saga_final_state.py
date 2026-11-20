"""The state machine ends where the result says the saga ended (#517)."""

from __future__ import annotations

import pytest

from sagaz.core.saga import Saga
from sagaz.core.types import SagaStatus


async def ok(ctx):
    return {"ok": True}


async def boom(ctx):
    msg = "declined"
    raise ValueError(msg)


async def undo(result, ctx):
    return None


async def undo_fails(result, ctx):
    msg = "cannot undo"
    raise RuntimeError(msg)


def assert_agrees(saga: Saga, result, status: SagaStatus) -> None:
    assert result.status == status
    assert saga.status == status
    assert saga.state_configuration == [status.value]


class TestSequential:
    async def test_failure_before_any_step_completed(self):
        saga = Saga("s")
        await saga.add_step("charge", boom, undo, max_retries=0)
        result = await saga.execute()
        assert_agrees(saga, result, SagaStatus.ROLLED_BACK)
        assert saga.completed_at is not None

    async def test_failure_after_a_step_is_compensated(self):
        saga = Saga("s")
        await saga.add_step("reserve", ok, undo)
        await saga.add_step("charge", boom, undo, max_retries=0)
        assert_agrees(saga, await saga.execute(), SagaStatus.ROLLED_BACK)

    async def test_a_failed_compensation(self):
        saga = Saga("s")
        await saga.add_step("reserve", ok, undo_fails, max_retries=0)
        await saga.add_step("charge", boom, undo, max_retries=0)
        assert_agrees(saga, await saga.execute(), SagaStatus.FAILED)


class TestDag:
    async def test_a_failed_compensation(self):
        saga = Saga("s")
        await saga.add_step("reserve", ok, undo_fails, dependencies=set(), max_retries=0)
        await saga.add_step("charge", boom, undo, dependencies={"reserve"}, max_retries=0)
        result = await saga.execute()
        assert_agrees(saga, result, SagaStatus.FAILED)  # was ROLLED_BACK, with a FAILED result

    async def test_a_compensated_failure(self):
        saga = Saga("s")
        await saga.add_step("reserve", ok, undo, dependencies=set(), max_retries=0)
        await saga.add_step("charge", boom, undo, dependencies={"reserve"}, max_retries=0)
        assert_agrees(saga, await saga.execute(), SagaStatus.ROLLED_BACK)

    async def test_failure_before_any_step_completed(self):
        saga = Saga("s")
        await saga.add_step("charge", boom, undo, dependencies=set(), max_retries=0)
        result = await saga.execute()
        assert_agrees(saga, result, SagaStatus.ROLLED_BACK)  # was FAILED, with a ROLLED_BACK result

    async def test_success(self):
        saga = Saga("s")
        await saga.add_step("a", ok, undo, dependencies=set())
        await saga.add_step("b", ok, undo, dependencies={"a"})
        assert_agrees(saga, await saga.execute(), SagaStatus.COMPLETED)


@pytest.mark.parametrize("dag", [False, True])
async def test_the_event_store_records_the_outcome_once(dag, monkeypatch):
    finished: list[str] = []

    async def record(self, outcome):
        finished.append(outcome)

    monkeypatch.setattr(Saga, "_es_finish", record)
    saga = Saga("s")
    deps = {"dependencies": set()} if dag else {}
    await saga.add_step("charge", boom, undo, max_retries=0, **deps)
    await saga.execute()
    assert finished == ["rolled_back"]
