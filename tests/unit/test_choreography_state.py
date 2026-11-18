"""Durable choreography participant state (#448)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from sagaz.choreography import COMPENSATE, ChoreographyEngine, Event, EventBus
from sagaz.choreography.state import InMemoryParticipantState, create_participant_state
from sagaz.choreography.state.sqlite import SQLiteParticipantState
from sagaz.core.tenant import tenant_scope
from tests.unit.test_choreography_compensation import Inventory


@pytest.fixture(params=["memory", "sqlite"])
async def state(request, tmp_path):
    if request.param == "memory":
        yield InMemoryParticipantState()
        return
    sqlite_state = SQLiteParticipantState(str(tmp_path / "state.db"))
    yield sqlite_state
    await sqlite_state.close()


def created(saga_id: str, order_id: str = "o-1") -> Event:
    return Event("order.created", {"order_id": order_id}, saga_id=saga_id)


class TestContract:
    async def test_actions_come_back_oldest_first_once(self, state):
        first, second = created("t-1", "a"), created("t-1", "b")
        for event in (first, second, first):
            await state.record_action("inventory", event)
        await state.record_action("inventory", Event("x"))  # no transaction: ignored
        done = await state.finish("inventory", "t-1", compensated=True)
        assert [e.event_id for e in done] == [first.event_id, second.event_id]
        assert done[0] == first
        assert await state.finish("inventory", "t-1", compensated=True) == []

    async def test_finished_transactions_record_nothing(self, state):
        await state.finish("inventory", "t-1", compensated=False)
        await state.record_action("inventory", created("t-1"))
        assert await state.finish("inventory", "t-1", compensated=True) == []

    async def test_compensated_wins_over_completed(self, state):
        assert not await state.was_compensated("inventory", "t-1")
        await state.finish("inventory", "t-1", compensated=True)
        await state.finish("inventory", "t-1", compensated=False)
        assert await state.was_compensated("inventory", "t-1")
        assert not await state.was_compensated("payments", "t-1")

    async def test_deliveries_are_claimed_once_per_participant(self, state):
        assert await state.first_delivery("inventory", "e-1")
        assert not await state.first_delivery("inventory", "e-1")
        assert await state.first_delivery("payments", "e-1")

    async def test_tenants_are_separate(self, state):
        with tenant_scope("acme"):
            await state.record_action("inventory", created("t-1"))
            await state.finish("inventory", "t-2", compensated=True)
            assert await state.first_delivery("inventory", "e-1")
        with tenant_scope("globex"):
            assert await state.finish("inventory", "t-1", compensated=True) == []
            assert not await state.was_compensated("inventory", "t-2")
            assert await state.first_delivery("inventory", "e-1")
        with tenant_scope("acme"):
            assert len(await state.finish("inventory", "t-1", compensated=True)) == 1

    async def test_prune(self, state):
        await state.finish("inventory", "t-1", compensated=True)
        await state.first_delivery("inventory", "e-1")
        assert await state.prune(timedelta(days=1)) == 0
        removed = await state.prune(timedelta(seconds=-1))
        if isinstance(state, InMemoryParticipantState):
            assert removed == 0  # bounded instead
        else:
            assert removed == 2
            assert not await state.was_compensated("inventory", "t-1")
            assert await state.first_delivery("inventory", "e-1")


class TestFactory:
    def test_urls(self, tmp_path):
        assert isinstance(create_participant_state("memory://"), InMemoryParticipantState)
        assert create_participant_state(f"sqlite://{tmp_path}/s.db").db_path == f"{tmp_path}/s.db"
        assert create_participant_state("sqlite://").db_path == ":memory:"
        pg = create_participant_state("postgresql://u@h/db")
        assert type(pg).__name__ == "PostgreSQLParticipantState"
        with pytest.raises(ValueError, match="Unsupported"):
            create_participant_state("mongodb://x")


async def run_inventory(url: str, *events: Event) -> Inventory:
    """One 'process': a fresh engine and participant on the shared state."""
    bus = EventBus()
    engine = ChoreographyEngine(bus, state=url)
    inventory = Inventory()
    engine.register(inventory)
    await engine.start()
    for event in events:
        await bus.publish(event)
    await engine.stop()
    await engine._state.close()
    return inventory


class TestAcrossProcesses:
    async def test_a_restarted_participant_compensates_earlier_actions(self, tmp_path):
        url = f"sqlite://{tmp_path / 'state.db'}"
        order = created("t-1")
        before = await run_inventory(url, order)
        assert before.reserved == ["o-1"]

        after = await run_inventory(url, Event(COMPENSATE, saga_id="t-1"))
        assert after.released == ["o-1"]

    async def test_a_redelivery_after_restart_is_not_handled_again(self, tmp_path):
        url = f"sqlite://{tmp_path / 'state.db'}"
        order = created("t-1")
        await run_inventory(url, order)
        again = await run_inventory(url, order)
        assert again.reserved == []

    async def test_a_late_event_after_restart_still_hits_the_tombstone(self, tmp_path):
        url = f"sqlite://{tmp_path / 'state.db'}"
        await run_inventory(url, Event(COMPENSATE, saga_id="t-1"))
        late = await run_inventory(url, created("t-1"))
        assert late.reserved == []

    async def test_without_durable_state_a_restart_forgets(self):
        bus = EventBus()
        first, second = ChoreographyEngine(bus), ChoreographyEngine(EventBus())
        inventory = Inventory()
        first.register(inventory)
        await bus.publish(created("t-1"))
        replacement = Inventory()
        second.register(replacement)
        await second._bus.publish(Event(COMPENSATE, saga_id="t-1"))
        assert replacement.released == []  # the documented limitation
