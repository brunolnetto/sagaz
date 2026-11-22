"""Deadlines of choreographed transactions (#449)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY

from sagaz.choreography import (
    COMPENSATE,
    COMPENSATED,
    ChoreographyEngine,
    ChoreographyTracker,
    Event,
    EventBus,
)
from sagaz.choreography._deadlines import DEADLINE_EXCEEDED
from sagaz.choreography.state import InMemoryParticipantState
from sagaz.choreography.state.sqlite import SQLiteParticipantState
from sagaz.choreography.tracker import STALLED, TransactionStatus, stalled_view
from sagaz.core.tenant import tenant_scope
from tests.unit.test_choreography_compensation import Inventory, Orders, Stack

LATER = timedelta(seconds=31)


def compensations(bus: EventBus) -> list[Event]:
    return [e for e in bus.published if e.event_type == COMPENSATE]


class Stuck:
    """Orders and Inventory only: nobody ever completes the transaction."""

    def __init__(self, state=None, **engine_options) -> None:
        self.bus = EventBus()
        self.engine = ChoreographyEngine(
            self.bus, completion_events={"order.shipped"}, state=state, **engine_options
        )
        self.tracker = ChoreographyTracker(self.bus, completion_events={"order.shipped"})
        self.orders, self.inventory = Orders(name="orders"), Inventory()
        for participant in (self.orders, self.inventory):
            self.engine.register(participant)

    async def __aenter__(self) -> Stuck:
        await self.tracker.start()
        await self.engine.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.engine.stop()
        await self.tracker.stop()


class TestExpiry:
    async def test_an_expired_deadline_compensates_once(self):
        async with Stuck() as stuck:
            with tenant_scope("acme"):
                first = await stuck.orders.begin("order.created", {"order_id": "o-1"}, deadline=30)
            assert await stuck.engine.deadlines.expire(datetime.now(UTC)) == 0  # not yet
            before = (
                REGISTRY.get_sample_value(
                    "sagaz_choreography_deadlines_expired_total", {"participant": "orders"}
                )
                or 0.0
            )

            assert await stuck.engine.deadlines.expire(datetime.now(UTC) + LATER) == 1
            assert await stuck.engine.deadlines.expire(datetime.now(UTC) + LATER) == 0

            (compensate,) = compensations(stuck.bus)
            assert compensate.saga_id == first.saga_id
            assert (compensate.tenant_id, compensate.source) == ("acme", "orders")
            assert compensate.data["reason"] == DEADLINE_EXCEEDED
            assert stuck.inventory.released == ["o-1"]
            with tenant_scope("acme"):
                status = await stuck.tracker.status(first.saga_id)
            assert status.status == "rolled_back"
            assert status.failure["reason"] == DEADLINE_EXCEEDED
            assert (
                REGISTRY.get_sample_value(
                    "sagaz_choreography_deadlines_expired_total", {"participant": "orders"}
                )
                == before + 1
            )

    async def test_completion_clears_the_deadline(self):
        async with Stack() as stack:
            await stack.orders.begin("order.created", {"order_id": "o-1"}, deadline=1)
            assert await stack.engine.deadlines.expire(datetime.now(UTC) + LATER) == 0
            assert compensations(stack.bus) == []

    async def test_a_failure_clears_the_deadline(self):
        async with Stack() as stack:
            await stack.orders.begin(
                "order.created", {"order_id": "o-1", "amount": 500}, deadline=timedelta(seconds=1)
            )
            assert len(compensations(stack.bus)) == 1  # the payment failure
            assert await stack.engine.deadlines.expire(datetime.now(UTC) + LATER) == 0

    async def test_a_late_event_after_the_deadline_is_not_acted_on(self):
        async with Stuck() as stuck:
            first = await stuck.orders.begin("order.created", {"order_id": "o-1"}, deadline=30)
            await stuck.engine.deadlines.expire(datetime.now(UTC) + LATER)
            await stuck.bus.publish(
                Event("order.created", {"order_id": "o-1"}, saga_id=first.saga_id)
            )
        assert stuck.inventory.reserved == ["o-1"]  # only the original reservation

    async def test_the_watcher_polls_while_the_engine_runs(self):
        async with Stuck(deadline_poll_interval=0.01) as stuck:
            assert not stuck.engine.deadlines.running  # nothing to watch yet
            await stuck.orders.begin("order.created", {"order_id": "o-1"}, deadline=0.05)
            assert stuck.engine.deadlines.running
            for _ in range(100):
                if compensations(stuck.bus):
                    break
                await asyncio.sleep(0.01)
            assert len(compensations(stuck.bus)) == 1
        assert not stuck.engine.deadlines.running  # stop() cancels it

    async def test_watcher_errors_are_logged_and_polling_goes_on(self, caplog):
        class Flaky(InMemoryParticipantState):
            calls = 0

            async def claim_due_deadlines(self, *args, **kwargs):
                Flaky.calls += 1
                if Flaky.calls == 1:
                    msg = "database restarting"
                    raise ConnectionError(msg)
                return await super().claim_due_deadlines(*args, **kwargs)

        async with Stuck(state=Flaky(), deadline_poll_interval=0.01) as stuck:
            assert stuck.engine.deadlines.running  # durable-capable state: watch at start
            for _ in range(100):
                if Flaky.calls > 1:
                    break
                await asyncio.sleep(0.01)
        assert "Checking choreography deadlines failed" in caplog.text


class TestReplicas:
    async def test_replicas_sharing_a_state_compensate_once(self, tmp_path):
        state = SQLiteParticipantState(str(tmp_path / "state.db"))
        replicas = [Stuck(state=state), Stuck(state=state)]
        try:
            for replica in replicas:
                await replica.__aenter__()
            await replicas[0].orders.begin("order.created", {"order_id": "o-1"}, deadline=30)
            later = datetime.now(UTC) + LATER
            counts = await asyncio.gather(*(r.engine.deadlines.expire(later) for r in replicas))
            assert sorted(counts) == [0, 1]
        finally:
            for replica in replicas:
                await replica.__aexit__()
            await state.close()

    @pytest.mark.parametrize("make_state", [InMemoryParticipantState, None])
    async def test_an_unfinished_claim_is_retried_after_the_lease(self, tmp_path, make_state):
        state = make_state() if make_state else SQLiteParticipantState(str(tmp_path / "s.db"))
        now = datetime.now(UTC)
        await state.set_deadline("orders", "t-1", now)
        lease = timedelta(seconds=60)
        assert len(await state.claim_due_deadlines({"orders"}, now, lease)) == 1
        assert await state.claim_due_deadlines({"orders"}, now + timedelta(seconds=30), lease) == []
        retried = await state.claim_due_deadlines({"orders"}, now + timedelta(seconds=61), lease)
        assert [d.correlation_id for d in retried] == ["t-1"]
        assert await state.claim_due_deadlines({"payments"}, now + timedelta(hours=1), lease) == []
        await state.close()

    @pytest.mark.parametrize("make_state", [InMemoryParticipantState, None])
    async def test_deadlines_of_ended_transactions_are_ignored(self, tmp_path, make_state):
        state = make_state() if make_state else SQLiteParticipantState(str(tmp_path / "s.db"))
        now = datetime.now(UTC)
        await state.finish("orders", "t-1", compensated=False)
        await state.set_deadline("orders", "t-1", now)
        await state.set_deadline("orders", "t-2", now)
        await state.finish("orders", "t-2", compensated=True)
        assert await state.claim_due_deadlines({"orders"}, now, timedelta(seconds=1)) == []
        assert await state.claim_due_deadlines(set(), now, timedelta(seconds=1)) == []
        await state.close()


class TestStalled:
    def status(self, state: str, seconds_ago: float) -> TransactionStatus:
        at = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
        return TransactionStatus("t-1", status=state, events=[{"event_type": "x", "at": at}])

    def test_an_idle_executing_transaction_is_stalled(self):
        assert stalled_view(self.status("executing", 120), 60).status == STALLED
        assert stalled_view(self.status("executing", 10), timedelta(seconds=60)).status == (
            "executing"
        )
        assert stalled_view(self.status("completed", 120), 60).status == "completed"
        assert stalled_view(self.status("executing", 120), None).status == "executing"
        assert stalled_view(None, 60) is None

    async def test_the_tracker_reports_stalled_without_storing_it(self):
        bus = EventBus()
        tracker = ChoreographyTracker(bus, stall_after=0.01)
        await tracker.start()
        await bus.publish(Event("order.created", saga_id="t-1", source="orders"))
        await asyncio.sleep(0.05)
        assert (await tracker.status("t-1")).status == STALLED
        assert tracker._memory["t-1"].status == "executing"
        await bus.publish(Event(COMPENSATED, {"participant": "x"}, saga_id="t-1"))
