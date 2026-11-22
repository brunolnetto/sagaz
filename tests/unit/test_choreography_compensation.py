"""Choreography: correlation, tenancy, compensation and status tracking (ADR-029, #56)."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from sagaz.choreography import (
    COMPENSATE,
    COMPENSATED,
    ChoreographedSaga,
    ChoreographyEngine,
    ChoreographyTracker,
    Event,
    EventBus,
    TransactionStatus,
    compensate,
    load_status,
    on_event,
)
from sagaz.choreography.state import InMemoryParticipantState
from sagaz.core.tenant import current_tenant_id, tenant_scope


class Orders(ChoreographedSaga):
    """Starts transactions; nothing to undo."""


class Inventory(ChoreographedSaga):
    def __init__(self, fail_release: bool = False) -> None:
        super().__init__(name="inventory")
        self.reserved: list[str] = []
        self.released: list[str] = []
        self.tenants: list[str] = []
        self.fail_release = fail_release

    @on_event("order.created")
    async def reserve(self, event: Event) -> None:
        self.tenants.append(current_tenant_id())
        self.reserved.append(event.data["order_id"])
        await self.emit("inventory.reserved", dict(event.data))

    @compensate("order.created")
    async def release(self, event: Event) -> None:
        if self.fail_release:
            msg = "warehouse offline"
            raise RuntimeError(msg)
        self.released.append(event.data["order_id"])


class Payments(ChoreographedSaga):
    def __init__(self, limit: int = 100) -> None:
        super().__init__(name="payments")
        self.limit = limit
        self.charged: list[str] = []
        self.refunded: list[str] = []

    @on_event("inventory.reserved")
    async def charge(self, event: Event) -> None:
        if event.data.get("amount", 0) > self.limit:
            msg = "card declined"
            raise ValueError(msg)
        self.charged.append(event.data["order_id"])
        await self.emit("payment.charged", event.data)

    @compensate("inventory.reserved")
    async def refund(self, event: Event) -> None:
        self.refunded.append(event.data["order_id"])


class Shipping(ChoreographedSaga):
    def __init__(self) -> None:
        super().__init__(name="shipping")

    @on_event("payment.charged")
    async def ship(self, event: Event) -> None:
        await self.emit("order.shipped", event.data)


class Stack:
    def __init__(self, inventory: Inventory | None = None, storage=None) -> None:
        self.bus = EventBus()
        self.engine = ChoreographyEngine(self.bus, completion_events={"order.shipped"})
        self.tracker = ChoreographyTracker(self.bus, storage, completion_events={"order.shipped"})
        self.orders = Orders(name="orders")
        self.inventory = inventory or Inventory()
        self.payments = Payments()
        self.shipping = Shipping()
        for participant in (self.orders, self.inventory, self.payments, self.shipping):
            self.engine.register(participant)

    async def __aenter__(self) -> Stack:
        await self.tracker.start()
        await self.engine.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.engine.stop()
        await self.tracker.stop()

    def types(self) -> list[str]:
        return [e.event_type for e in self.bus.published]


def _sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestHappyPath:
    async def test_events_carry_correlation_tenant_cause_and_source(self):
        async with Stack() as stack:
            with tenant_scope("acme"):
                first = await stack.orders.begin("order.created", {"order_id": "o-1"})

            assert stack.types() == [
                "order.created",
                "inventory.reserved",
                "payment.charged",
                "order.shipped",
            ]
            events = stack.bus.published
            assert {e.correlation_id for e in events} == {first.saga_id}
            assert {e.tenant_id for e in events} == {"acme"}
            assert [e.source for e in events] == ["orders", "inventory", "payments", "shipping"]
            assert [e.causation_id for e in events[1:]] == [e.event_id for e in events[:-1]]
            assert stack.inventory.tenants == ["acme"]  # handlers run in the event's tenant

    async def test_completion_is_tracked_and_compensation_memory_released(self):
        async with Stack() as stack:
            first = await stack.orders.begin("order.created", {"order_id": "o-1"})
            status = await stack.tracker.status(first.saga_id)
            assert status.status == "completed"
            # Completed: a late compensation request has nothing left to undo.
            await stack.bus.publish(Event(COMPENSATE, saga_id=first.saga_id))

        # The in-process bus delivers nested events depth-first, so the tracker
        # sees them in reverse; the status does not depend on arrival order.
        assert set(status.participants) == {"orders", "inventory", "payments", "shipping"}
        assert {e["event_type"] for e in status.events} >= {"order.created", "order.shipped"}
        assert stack.inventory.released == []
        assert stack.payments.refunded == []

    async def test_begin_accepts_an_explicit_correlation_and_tenant(self):
        async with Stack() as stack:
            event = await stack.orders.begin(
                "order.created", {"order_id": "o-9"}, correlation_id="ord-9", tenant="globex"
            )
        assert (event.saga_id, event.tenant_id) == ("ord-9", "globex")


class TestCompensation:
    async def test_a_failing_participant_triggers_compensation_of_the_others(self):
        async with Stack() as stack:
            failed_before = _sample(
                "sagaz_choreography_events_total",
                participant="payments",
                event_type="inventory.reserved",
                outcome="failed",
            )
            first = await stack.orders.begin("order.created", {"order_id": "o-2", "amount": 500})

            assert stack.types()[:3] == ["order.created", "inventory.reserved", COMPENSATE]
            compensate_event = stack.bus.published[2]
            assert compensate_event.data["participant"] == "payments"
            assert compensate_event.data["reason"] == "ValueError: card declined"
            assert compensate_event.saga_id == first.saga_id
            assert stack.inventory.released == ["o-2"]
            assert stack.payments.refunded == []  # its own action never completed
            assert "payment.charged" not in stack.types()

            reports = {
                e.data["participant"]: e.data
                for e in stack.bus.published
                if e.event_type == COMPENSATED
            }
            assert reports["inventory"]["undone"] == ["order.created"]
            assert set(reports) == {"orders", "inventory", "payments", "shipping"}

            status = await stack.tracker.status(first.saga_id)
            assert status.status == "rolled_back"
            assert status.failure["participant"] == "payments"
            assert (
                _sample(
                    "sagaz_choreography_events_total",
                    participant="payments",
                    event_type="inventory.reserved",
                    outcome="failed",
                )
                == failed_before + 1
            )

    async def test_compensation_failures_mark_the_transaction_failed(self):
        async with Stack(inventory=Inventory(fail_release=True)) as stack:
            first = await stack.orders.begin("order.created", {"order_id": "o-3", "amount": 500})
            status = await stack.tracker.status(first.saga_id)

        assert status.status == "failed"
        assert status.compensated_by["inventory"]["failed"] == ["order.created"]

    async def test_compensation_runs_newest_first(self):
        class TwoSteps(ChoreographedSaga):
            def __init__(self) -> None:
                super().__init__(name="two")
                self.undone: list[str] = []

            @on_event("a")
            async def on_a(self, event: Event) -> None: ...

            @on_event("b")
            async def on_b(self, event: Event) -> None: ...

            @compensate("a")
            async def undo_a(self, event: Event) -> None:
                self.undone.append("a")

            @compensate("b")
            async def undo_b(self, event: Event) -> None:
                self.undone.append("b")

        bus = EventBus()
        engine = ChoreographyEngine(bus)
        participant = TwoSteps()
        engine.register(participant)
        for event_type in ("a", "b"):
            await bus.publish(Event(event_type, saga_id="t-1"))
        await bus.publish(Event(COMPENSATE, saga_id="t-1"))
        assert participant.undone == ["b", "a"]

    async def test_sync_handlers_and_compensations_work(self):
        """A plain ``def`` handler is not turned into a failure and compensated (#553)."""

        class Sync(ChoreographedSaga):
            def __init__(self) -> None:
                super().__init__(name="sync")
                self.done: list[str] = []

            @on_event("a")
            def on_a(self, event: Event) -> None:
                self.done.append("a")

            @compensate("a")
            def undo_a(self, event: Event) -> None:
                self.done.append("undo:a")

        bus = EventBus()
        published: list[str] = []
        bus.subscribe("*", lambda event: published.append(event.event_type))
        engine = ChoreographyEngine(bus)
        participant = Sync()
        engine.register(participant)
        await bus.publish(Event("a", saga_id="t-sync"))
        assert participant.done == ["a"]
        assert COMPENSATE not in published  # the sync handler did not "fail"
        await bus.publish(Event(COMPENSATE, saga_id="t-sync"))
        assert participant.done == ["a", "undo:a"]

    async def test_failures_without_a_transaction_are_not_compensated(self):
        async with Stack() as stack:
            await stack.bus.publish(Event("inventory.reserved", {"order_id": "x", "amount": 999}))
        assert COMPENSATE not in stack.types()


class TestIdempotency:
    async def test_redelivered_events_are_handled_once(self):
        async with Stack() as stack:
            event = Event("order.created", {"order_id": "o-4"}, saga_id="t-4")
            await stack.bus.publish(event)
            await stack.bus.publish(event)  # at-least-once redelivery
        assert stack.inventory.reserved == ["o-4"]

    async def test_dedup_memory_is_bounded(self):
        state = InMemoryParticipantState(max_deliveries=2)
        for i in range(3):
            assert await state.first_delivery("o", str(i))
        assert not await state.first_delivery("o", "2")
        assert await state.first_delivery("o", "0")  # evicted

    async def test_compensation_memory_is_bounded(self):
        state = InMemoryParticipantState(max_transactions=2)
        for i in range(3):
            await state.record_action("inventory", Event("order.created", saga_id=f"t-{i}"))
        assert await state.finish("inventory", "t-0", compensated=True) == []  # evicted
        assert len(await state.finish("inventory", "t-2", compensated=True)) == 1


class TestEmitting:
    async def test_participants_must_be_registered_to_publish(self):
        with pytest.raises(RuntimeError, match="not registered"):
            await Orders(name="lonely").begin("x")
        with pytest.raises(RuntimeError, match="not registered"):
            await Orders(name="lonely").emit("x")


class TestTracker:
    async def test_status_is_persisted_per_tenant(self, tmp_path):
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage

        async with SQLiteSagaStorage(str(tmp_path / "c.db")) as storage:
            async with Stack(storage=storage) as stack:
                first = await stack.orders.begin(
                    "order.created", {"order_id": "o-5"}, tenant="acme"
                )
            with tenant_scope("acme"):
                status = await load_status(storage, first.saga_id)
            with tenant_scope("globex"):
                other = await load_status(storage, first.saga_id)
            assert await load_status(storage, "nope") is None

        assert status.status == "completed"
        assert status.tenant_id == "acme"
        assert other is None

    async def test_status_round_trips_and_ignores_unknown_fields(self):
        status = TransactionStatus("t-1", status="compensating", participants=["a"])
        assert TransactionStatus.from_dict({**status.to_dict(), "extra": 1}) == status

    async def test_events_without_correlation_are_ignored(self):
        tracker = ChoreographyTracker(EventBus())
        await tracker.observe(Event("x"))
        assert tracker._memory == {}


class TestEventSerialization:
    def test_to_dict_from_dict_round_trip(self):
        event = Event(
            "order.created",
            {"order_id": "o-1"},
            saga_id="t-1",
            tenant_id="acme",
            causation_id="c-1",
            source="orders",
        )
        assert Event.from_dict(event.to_dict()) == event

    def test_older_payloads_default_the_new_fields(self):
        payload = Event("x", saga_id="t").to_dict()
        for key in ("tenant_id", "causation_id", "source"):
            payload.pop(key)
        restored = Event.from_dict(payload)
        assert (restored.tenant_id, restored.causation_id, restored.source) == (
            "default",
            None,
            None,
        )


class TestEdges:
    async def test_compensate_without_a_transaction_is_ignored(self):
        async with Stack() as stack:
            await stack.bus.publish(Event(COMPENSATE))
        assert COMPENSATED not in stack.types()

    async def test_an_action_is_remembered_once(self):
        inventory = Inventory()
        event = Event("order.created", saga_id="t-1")
        await inventory._remember(event)
        await inventory._remember(event)  # emit() and the handler's return both record it
        assert len(await inventory._state.finish("inventory", "t-1", compensated=True)) == 1

    async def test_finished_transactions_are_bounded_and_never_remembered_again(self):
        state = InMemoryParticipantState(max_transactions=2)
        for i in range(3):
            await state.finish("inventory", f"t-{i}", compensated=False)
        for i in (0, 2):
            await state.record_action("inventory", Event("order.created", saga_id=f"t-{i}"))
        assert await state.finish("inventory", "t-2", compensated=True) == []  # finished
        assert len(await state.finish("inventory", "t-0", compensated=True)) == 1  # evicted


class TestLateEvents:
    """Compensation commutes with business events that arrive after it (#446)."""

    async def test_a_business_event_after_compensation_is_not_acted_on(self):
        async with Stack() as stack:
            before = _sample(
                "sagaz_choreography_events_total",
                participant="inventory",
                event_type="order.created",
                outcome="after_compensation",
            )
            # A partition or a slow producer delivers the compensation first.
            await stack.bus.publish(Event(COMPENSATE, {"participant": "payments"}, saga_id="t-1"))
            await stack.bus.publish(Event("order.created", {"order_id": "late"}, saga_id="t-1"))

            assert stack.inventory.reserved == []
            assert "inventory.reserved" not in stack.types()
            assert (
                _sample(
                    "sagaz_choreography_events_total",
                    participant="inventory",
                    event_type="order.created",
                    outcome="after_compensation",
                )
                == before + 1
            )
            # Other transactions are unaffected.
            await stack.bus.publish(Event("order.created", {"order_id": "o-2"}, saga_id="t-2"))
            assert stack.inventory.reserved == ["o-2"]

            # The tracker still records the late event.
            status = await stack.tracker.status("t-1")
            assert "order.created" in {e["event_type"] for e in status.events}

    async def test_compensation_reports_still_reach_wildcard_handlers(self):
        class Auditor(ChoreographedSaga):
            def __init__(self) -> None:
                super().__init__(name="auditor")
                self.seen: list[str] = []

            @on_event("*")
            async def record(self, event: Event) -> None:
                self.seen.append(event.event_type)

        bus = EventBus()
        engine = ChoreographyEngine(bus)
        auditor = Auditor()
        engine.register(auditor)
        await bus.publish(Event(COMPENSATE, saga_id="t-1"))
        await bus.publish(Event(COMPENSATED, {"participant": "x"}, saga_id="t-1"))
        await bus.publish(Event("order.created", saga_id="t-1"))
        # Its own report and the one published above; the late business event is not.
        assert auditor.seen == [COMPENSATED, COMPENSATED]

    async def test_tombstones_are_bounded(self, monkeypatch):
        monkeypatch.setattr(Inventory, "max_tracked_transactions", 2)
        inventory = Inventory()
        for i in range(3):
            await inventory.compensate_transaction(f"t-{i}")
        assert [await inventory.was_compensated(f"t-{i}") for i in range(3)] == [False, True, True]
        assert not await inventory.was_compensated(None)
