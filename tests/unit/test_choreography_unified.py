"""Choreography on the unified saga log (ADR-041 phase 3, #466)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner

from sagaz.choreography import (
    COMPENSATE,
    ChoreographyEngine,
    ChoreographyTracker,
    Event,
    EventBus,
)
from sagaz.choreography.relay import ChoreographyRelay, EventBusBroker
from sagaz.choreography.state.unified import UnifiedParticipantState
from sagaz.cli.app import cli
from sagaz.core.storage.saga_log import InMemorySagaLogStore, LogWrite
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore
from tests.unit.test_choreography_compensation import Inventory, Orders, Payments, Shipping

COMPLETION = {"order.shipped"}


@pytest.fixture(params=["memory", "sqlite"])
async def log(request, tmp_path):
    if request.param == "memory":
        yield InMemorySagaLogStore()
        return
    store = SQLiteSagaLogStore(str(tmp_path / "log.db"))
    yield store
    await store.close()


class Service:
    """One process: an engine on the log, with its own bus and participants."""

    def __init__(self, log, *participants, bus=None) -> None:
        self.bus = bus or EventBus()
        self.engine = ChoreographyEngine(
            self.bus, completion_events=COMPLETION, saga_log=log, relay_interval=3600
        )
        self.tracker = ChoreographyTracker(self.bus, completion_events=COMPLETION, saga_log=log)
        self.participants = participants
        for participant in participants:
            self.engine.register(participant)

    async def __aenter__(self) -> Service:
        await self.tracker.start()
        await self.engine.start()
        # Deterministic tests: deliver only on settle(), not from the background
        # poll (covered by TestPieces.test_the_relay_polls_in_the_background).
        await self.engine.relay.stop()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.engine.stop()
        await self.tracker.stop()

    async def settle(self) -> int:
        """Relay the outbox until nothing is pending (handlers add more)."""
        return await self.engine.relay.relay()


def shop(log, inventory=None):
    orders = Orders(name="orders")
    inventory = inventory or Inventory()
    return Service(log, orders, inventory, Payments(), Shipping()), orders, inventory


class TestFlows:
    async def test_a_completed_order(self, log):
        service, orders, inventory = shop(log)
        async with service:
            start = await orders.begin("order.created", {"order_id": "o-1", "amount": 40})
            assert inventory.reserved == []  # nothing is published until the relay runs
            assert await service.settle() == 4
            status = await service.tracker.status(start.saga_id)

        transaction = await log.get_transaction(start.saga_id)
        assert (transaction.coordination, transaction.flow) == ("choreographed", "order.created")
        assert (transaction.initiator, transaction.status) == ("orders", "completed")
        events = await log.events(start.saga_id)
        assert [e.event_type for e in events] == [
            "order.created",
            "inventory.reserved",
            "payment.charged",
            "order.shipped",
        ]
        assert [e.causation_id for e in events[1:]] == [e.event_id for e in events[:-1]]
        assert {e.kind for e in events} == {"business"}
        assert status.status == "completed"
        assert inventory.reserved == ["o-1"]

    async def test_a_declined_payment_is_compensated(self, log):
        service, orders, inventory = shop(log)
        async with service:
            start = await orders.begin("order.created", {"order_id": "o-2", "amount": 500})
            await service.settle()
            status = await service.tracker.status(start.saga_id)

        assert inventory.released == ["o-2"]
        assert status.status == "compensated"
        assert status.failure["participant"] == "payments"
        assert (await log.get_transaction(start.saga_id)).status == "compensated"
        kinds = [e.kind for e in await log.events(start.saga_id)]
        assert "compensate" in kinds
        assert kinds.count("compensated") == 4
        markers = {
            a.participant: a.status
            for a in await log.activities(start.saga_id)
            if a.name == "__transaction__"
        }
        assert markers["inventory"] == "compensated"

    async def test_the_tracker_agrees_with_the_bus_tracker(self, log):
        service, orders, _ = shop(log)
        legacy = ChoreographyTracker(service.bus, completion_events=COMPLETION)
        await legacy.start()
        async with service:
            ids = []
            for amount in (40, 500):
                start = await orders.begin("order.created", {"order_id": "o", "amount": amount})
                ids.append(start.saga_id)
            await service.settle()
            for saga_id in ids:
                old = await legacy.status(saga_id)
                new = await service.tracker.status(saga_id)
                assert (new.status, sorted(new.participants), new.failure) == (
                    old.status,
                    sorted(old.participants),
                    old.failure,
                )
                assert set(new.compensated_by) == set(old.compensated_by)
        await legacy.stop()


class TestAtomicity:
    async def test_a_failed_write_records_neither_state_nor_event(self, log):
        service, orders, _ = shop(log)
        original = log.write

        async def failing(batch: LogWrite):
            if batch.publish:
                msg = "database down"
                raise ConnectionError(msg)
            return await original(batch)

        log.write = failing  # type: ignore[method-assign]
        async with service:
            with pytest.raises(ConnectionError):
                await orders.begin("order.created", {"order_id": "o-3"}, correlation_id="t-3")
            assert await service.settle() == 0
        assert await log.get_transaction("t-3") is None
        assert await log.events("t-3") == []

    async def test_a_bus_outage_delays_delivery_without_losing_it(self, log):
        service, orders, inventory = shop(log)
        real_publish = service.bus.publish
        down = True

        async def flaky(event):
            if down:
                msg = "broker unreachable"
                raise ConnectionError(msg)
            await real_publish(event)

        service.bus.publish = flaky  # type: ignore[method-assign]
        async with service:
            await orders.begin("order.created", {"order_id": "o-4", "amount": 40})
            assert await service.settle() == 0  # failed, left for retry
            assert inventory.reserved == []
            down = False
            await service.settle()
        assert inventory.reserved == ["o-4"]


class TestDurability:
    async def test_replicas_share_state(self, log):
        """The replica that receives the compensation request undoes what another did."""
        first = Inventory()
        a = Service(log, Orders(name="orders"), first)
        second = Inventory()
        b = Service(log, second)
        async with a, b:
            start = await a.participants[0].begin("order.created", {"order_id": "o-5"})
            await a.settle()  # replica A reserves; nobody completes the order
            assert first.reserved == ["o-5"]
            await b.bus.publish(
                Event(COMPENSATE, {"participant": "payments"}, saga_id=start.saga_id)
            )
        assert second.released == ["o-5"]
        assert first.released == []

    async def test_a_late_event_hits_the_tombstone(self, log):
        inventory = Inventory()
        service = Service(log, inventory)
        async with service:
            await service.bus.publish(Event(COMPENSATE, saga_id="t-6"))
            await service.bus.publish(Event("order.created", {"order_id": "x"}, saga_id="t-6"))
        assert inventory.reserved == []

    async def test_redeliveries_are_handled_once(self, log):
        inventory = Inventory()
        service = Service(log, inventory)
        event = Event("order.created", {"order_id": "o-7"}, saga_id="t-7")
        async with service:
            await service.bus.publish(event)
            await service.bus.publish(event)
        assert inventory.reserved == ["o-7"]

    async def test_a_deadline_compensates_through_the_log(self, log):
        orders, inventory = Orders(name="orders"), Inventory()
        service = Service(log, orders, inventory)
        async with service:
            start = await orders.begin("order.created", {"order_id": "o-8"}, deadline=30)
            await service.settle()
            later = datetime.now(UTC) + timedelta(seconds=31)
            assert await service.engine.deadlines.expire(later) == 1
            await service.settle()
            status = await service.tracker.status(start.saga_id)
        assert inventory.released == ["o-8"]
        assert status.failure["reason"] == "deadline exceeded"


class TestPieces:
    async def test_events_without_a_transaction_go_straight_to_the_bus(self):
        sent = []

        async def send(event):
            sent.append(event)

        state = UnifiedParticipantState(InMemorySagaLogStore())
        await state.publish("orders", Event("ping"), send)
        assert [e.event_type for e in sent] == ["ping"]

    async def test_the_broker_publishes_raw_messages_too(self):
        bus = EventBus()
        received = []

        async def collect(event):
            received.append(event)

        bus.subscribe("*", collect)
        broker = EventBusBroker(bus)
        await broker.connect()
        assert broker.is_connected
        assert await broker.health_check()
        event = Event("order.created", {"n": 1}, saga_id="t")
        await broker.publish("topic", json.dumps({"payload": event.to_dict()}).encode())
        await broker.close()
        assert received[0].event_id == event.event_id

    async def test_the_relay_polls_in_the_background(self):
        log = InMemorySagaLogStore()
        bus = EventBus()
        received = []

        async def collect(event):
            received.append(event)

        bus.subscribe("*", collect)
        relay = ChoreographyRelay(log.outbox_storage(), bus, poll_interval=0.01)
        await relay.start()
        state = UnifiedParticipantState(log)
        await state.publish("orders", Event("x", saga_id="t"), bus.publish, begin=True)
        for _ in range(100):
            if received:
                break
            await asyncio.sleep(0.01)
        await relay.close()
        assert [e.event_type for e in received] == ["x"]

    async def test_engines_accept_a_log_url(self, tmp_path):
        engine = ChoreographyEngine(EventBus(), saga_log=f"sqlite://{tmp_path / 'l.db'}")
        assert isinstance(engine._state, UnifiedParticipantState)
        await engine._state.log.close()


def test_status_from_the_cli(tmp_path):
    path = tmp_path / "log.db"

    async def record():
        async with SQLiteSagaLogStore(str(path)) as log:
            service, orders, _ = shop(log)
            async with service:
                await orders.begin(
                    "order.created", {"order_id": "o", "amount": 500}, correlation_id="bad"
                )
                await service.settle()

    asyncio.run(record())
    args = ["choreography", "status", "bad", "--saga-log", f"sqlite://{path}"]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert "Transaction bad (tenant default): compensated" in result.output
    assert "failed: payments" in result.output
    unset = {"SAGAZ_STORAGE_URL": None, "SAGAZ_SAGA_LOG_URL": None}
    missing = CliRunner().invoke(cli, ["choreography", "status", "bad"], env=unset)
    assert missing.exit_code != 0
    assert "--saga-log" in missing.output


def test_a_sqlite_outbox_is_relayed_one_message_at_a_time(tmp_path):
    from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

    sqlite_relay = ChoreographyRelay(SQLiteOutboxStorage(str(tmp_path / "o.db")), EventBus())
    memory_relay = ChoreographyRelay(InMemorySagaLogStore().outbox_storage(), EventBus())
    assert sqlite_relay.worker.config.batch_size == 1
    assert memory_relay.worker.config.batch_size == 100
