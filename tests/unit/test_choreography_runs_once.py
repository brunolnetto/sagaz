"""A choreographed transaction id runs once, as a saga id does (#562)."""

from __future__ import annotations

import pytest

from sagaz.choreography import ChoreographedSaga, ChoreographyEngine, EventBus
from sagaz.choreography.state import InMemoryParticipantState
from sagaz.choreography.state.sqlite import SQLiteParticipantState
from sagaz.core.exceptions import SagaAlreadyExistsError, SagaDefinitionError


def memory_state(bus, tmp_path):
    return ChoreographyEngine(bus, state=InMemoryParticipantState())


def sqlite_state(bus, tmp_path):
    return ChoreographyEngine(bus, state=SQLiteParticipantState(str(tmp_path / "state.db")))


def unified_state(bus, tmp_path):
    # Events go out through the log's outbox: the relay publishes them on the bus.
    return ChoreographyEngine(bus, saga_log="memory://", relay_interval=0.001)


STATES = [memory_state, sqlite_state, unified_state]


async def settle(engine: ChoreographyEngine) -> None:
    if engine.relay is not None:
        await engine.relay.relay()


async def started(make_engine, tmp_path) -> tuple[ChoreographedSaga, list[str], ChoreographyEngine]:
    bus = EventBus()
    engine = make_engine(bus, tmp_path)
    seen: list[str] = []

    async def reserve(event, me):
        seen.append(event.saga_id)

    orders = ChoreographedSaga(name="orders")
    engine.register(orders)
    engine.register(ChoreographedSaga(name="inventory").on("order.created", reserve))
    await engine.start()
    return orders, seen, engine


@pytest.mark.parametrize("make_engine", STATES)
async def test_a_second_begin_with_the_same_id_is_refused_before_publishing(make_engine, tmp_path):
    orders, seen, engine = await started(make_engine, tmp_path)
    try:
        await orders.begin("order.created", {"order_id": "o-1"}, correlation_id="t-1")
        await settle(engine)
        with pytest.raises(SagaAlreadyExistsError) as raised:
            await orders.begin("order.created", {"order_id": "o-1"}, correlation_id="t-1")
        assert raised.value.saga_id == "t-1"
        await settle(engine)
        assert seen == ["t-1"]  # the second begin published nothing
    finally:
        await engine.stop()


@pytest.mark.parametrize("make_engine", STATES)
async def test_allow_rerun_starts_it_again(make_engine, tmp_path):
    orders, seen, engine = await started(make_engine, tmp_path)
    try:
        await orders.begin("order.created", correlation_id="t-1")
        await orders.begin("order.created", correlation_id="t-1", allow_rerun=True)
        await settle(engine)
        assert seen == ["t-1", "t-1"]
    finally:
        await engine.stop()


async def test_the_id_is_per_tenant(tmp_path):
    orders, seen, engine = await started(memory_state, tmp_path)
    try:
        await orders.begin("order.created", correlation_id="t-1", tenant="acme")
        await orders.begin("order.created", correlation_id="t-1", tenant="globex")
        assert seen == ["t-1", "t-1"]
    finally:
        await engine.stop()


async def test_generated_ids_are_not_checked(tmp_path):
    orders, seen, engine = await started(memory_state, tmp_path)
    try:
        first = await orders.begin("order.created")
        second = await orders.begin("order.created")
        assert first.saga_id != second.saga_id
        assert len(seen) == 2
    finally:
        await engine.stop()


def test_reserved_participant_names_are_refused():
    with pytest.raises(SagaDefinitionError, match="reserved"):
        ChoreographedSaga(name="__sagaz_begin")
