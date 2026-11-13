"""StepLedger and the declarative executor persisting step outcomes."""

from __future__ import annotations

import pytest

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.decorators._step_ledger import StepLedger
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage


class TestStepLedger:
    def test_success_failure_and_compensation_are_recorded_in_step_order(self):
        ledger = StepLedger(["a", "b", "c"])
        ledger.started("b")
        ledger.finished("b", RuntimeError("boom"))
        ledger.started("a")
        ledger.finished("a")
        ledger.compensated("a")

        a, b = ledger.snapshot()
        assert (a["name"], a["status"]) == ("a", "compensated")
        assert a["duration_ms"] >= 0
        assert a["compensated_at"] is not None
        assert (b["status"], b["error"]) == ("failed", "boom")

    def test_error_without_message_records_its_type(self):
        ledger = StepLedger(["a"])
        ledger.started("a")
        ledger.finished("a", TimeoutError())
        assert ledger.snapshot()[0]["error"] == "TimeoutError"

    def test_unknown_steps_are_ignored(self):
        ledger = StepLedger(["a"])
        ledger.finished("ghost")
        ledger.compensated("ghost")
        assert ledger.snapshot() == []


class OrderSaga(Saga):
    saga_name = "order"

    @action("reserve")
    async def reserve(self, ctx):
        return {"ok": True}

    @compensate("reserve")
    async def release(self, ctx):
        return None

    @action("charge", depends_on=["reserve"])
    async def charge(self, ctx):
        msg = "declined"
        raise RuntimeError(msg)


async def test_executor_persists_step_outcomes_with_durations():
    storage = InMemorySagaStorage()
    saga = OrderSaga(config=SagaConfig(storage=storage))
    with pytest.raises(RuntimeError):
        await saga.run({"order": 1})

    state = await storage.load_saga_state(saga._saga_id)
    steps = {s["name"]: s for s in state["steps"]}
    assert state["status"] == "rolled_back"
    assert steps["reserve"]["status"] == "compensated"
    assert steps["charge"]["status"] == "failed"
    assert steps["charge"]["error"] == "declined"
    assert all(s["duration_ms"] is not None for s in steps.values())
