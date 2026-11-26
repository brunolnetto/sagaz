"""Who a participant is: names it had, one name per participant, and its service (#571)."""

from __future__ import annotations

import logging

import pytest

from sagaz.choreography import (
    COMPENSATE,
    PIVOTED,
    ChoreographedSaga,
    ChoreographyEngine,
    Event,
    EventBus,
)
from sagaz.choreography._identity import finish
from sagaz.choreography._pivot import commit, split
from sagaz.choreography.state.sqlite import SQLiteParticipantState
from sagaz.core.exceptions import SagaDefinitionError


def participant(name: str, *formerly: str, undone: list[str] | None = None) -> ChoreographedSaga:
    log = undone if undone is not None else []
    return ChoreographedSaga(name=name, formerly=formerly).on(
        "order.created", lambda e, me: None, lambda e, me: log.append(e.data["order"])
    )


class TestARenamedParticipant:
    async def test_it_compensates_what_it_did_under_its_old_name(self, tmp_path):
        """A deploy renames ``payments`` to ``billing`` while a transaction is in flight."""
        state = SQLiteParticipantState(str(tmp_path / "state.db"))
        undone: list[str] = []
        try:
            before = ChoreographyEngine(EventBus(), state=state)
            before.register(participant("payments"))
            await before.start()
            await before._bus.publish(Event("order.created", {"order": "old"}, saga_id="t-1"))
            await before.stop()

            bus = EventBus()
            after = ChoreographyEngine(bus, state=state)
            after.register(participant("billing", "payments", undone=undone))
            await after.start()
            await bus.publish(Event("order.created", {"order": "new"}, saga_id="t-1"))
            await bus.publish(Event(COMPENSATE, saga_id="t-1"))
            await after.stop()
        finally:
            await state.close()
        assert undone == ["new", "old"]  # newest first, across the rename

    async def test_without_formerly_the_old_actions_are_forgotten(self, tmp_path):
        state = SQLiteParticipantState(str(tmp_path / "state.db"))
        undone: list[str] = []
        try:
            before = ChoreographyEngine(EventBus(), state=state)
            before.register(participant("payments"))
            await before.start()
            await before._bus.publish(Event("order.created", {"order": "old"}, saga_id="t-1"))
            await before.stop()
            bus = EventBus()
            after = ChoreographyEngine(bus, state=state)
            after.register(participant("billing", undone=undone))
            await after.start()
            await bus.publish(Event(COMPENSATE, saga_id="t-1"))
            await after.stop()
        finally:
            await state.close()
        assert undone == []

    async def test_it_recognises_itself_in_a_lineage_under_its_old_name(self):
        saga = participant("billing", "payments")
        acted = Event("order.created", {"order": "o"}, saga_id="t-1")
        trigger = Event("pay", source="payments").caused_by(acted)  # emitted before the rename
        await saga._state.record_action("payments", acted)
        await commit(saga, Event(PIVOTED, source="bank").caused_by(trigger))
        undo, kept = split(saga, await finish(saga, "t-1", compensated=True))
        assert (undo, kept) == ([], ["order.created"])

    async def test_a_transaction_compensated_under_the_old_name_stays_compensated(self):
        saga = participant("billing", "payments")
        await saga._state.finish("payments", "t-1", compensated=True)
        assert await saga.was_compensated("t-1")
        assert not await saga.was_compensated("t-2")
        assert not await saga.was_compensated(None)

    def test_formerly_cannot_list_the_current_name_nor_a_reserved_one(self):
        with pytest.raises(SagaDefinitionError, match="no longer has"):
            ChoreographedSaga(name="billing", formerly=["billing"])
        with pytest.raises(SagaDefinitionError, match="reserved"):
            ChoreographedSaga(name="billing", formerly=["__sagaz_x"])
        assert ChoreographedSaga(name="b", formerly=["a", "a"]).formerly == ("a",)


class TestOneNameOneParticipant:
    def test_an_engine_refuses_two_participants_with_one_name(self):
        engine = ChoreographyEngine(EventBus())
        engine.register(ChoreographedSaga(name="payments"))
        with pytest.raises(SagaDefinitionError, match="answer to the name 'payments'"):
            engine.register(ChoreographedSaga(name="payments"))

    def test_a_former_name_counts(self):
        engine = ChoreographyEngine(EventBus())
        engine.register(ChoreographedSaga(name="billing", formerly=["payments"]))
        with pytest.raises(SagaDefinitionError, match="'payments'"):
            engine.register(ChoreographedSaga(name="payments"))

    def test_registering_the_same_participant_again_replaces_it(self):
        engine = ChoreographyEngine(EventBus())
        engine.register(ChoreographedSaga(saga_id="s-1", name="payments"))
        engine.register(ChoreographedSaga(saga_id="s-1", name="payments"))
        assert len(engine.registered_sagas) == 1


class TestServices:
    """Engines with ``service=`` announce their participants on the bus."""

    @staticmethod
    def engine(bus: EventBus, service: str | None, *names: str) -> ChoreographyEngine:
        engine = ChoreographyEngine(bus, service=service)
        for name in names:
            engine.register(ChoreographedSaga(name=name))
        return engine

    async def test_replicas_of_a_service_share_a_name(self):
        bus = EventBus()
        one = self.engine(bus, "billing", "payments")
        two = self.engine(bus, "billing", "payments")
        await one.start()
        await two.start()
        assert one.identity.conflicts == two.identity.conflicts == []
        await one.stop()
        await two.stop()

    async def test_a_name_claimed_by_two_services_is_reported_to_both(self, caplog):
        bus = EventBus()
        billing = self.engine(bus, "billing", "payments", "invoices")
        fraud = self.engine(bus, "fraud", "payments", "scores")
        await billing.start()
        with caplog.at_level(logging.ERROR, logger="sagaz.choreography"):
            await fraud.start()  # the later one: billing answers, so both learn of it
        assert billing.identity.conflicts == [{"name": "payments", "service": "fraud"}]
        assert fraud.identity.conflicts == [{"name": "payments", "service": "billing"}]
        assert "claimed by service 'fraud'" in caplog.text
        await billing.stop()
        await fraud.stop()

    async def test_a_former_name_claimed_by_another_service_is_reported(self):
        bus = EventBus()
        billing = ChoreographyEngine(bus, service="billing")
        billing.register(ChoreographedSaga(name="billing", formerly=["payments"]))
        fraud = self.engine(bus, "fraud", "payments")
        await billing.start()
        await fraud.start()
        assert billing.identity.conflicts == [{"name": "payments", "service": "fraud"}]
        await billing.stop()
        await fraud.stop()

    async def test_different_names_do_not_conflict(self):
        bus = EventBus()
        billing = self.engine(bus, "billing", "payments")
        fraud = self.engine(bus, "fraud", "scores")
        await billing.start()
        await fraud.start()
        assert billing.identity.conflicts == fraud.identity.conflicts == []
        await billing.stop()
        await fraud.stop()

    async def test_without_a_service_nothing_is_announced(self):
        bus = EventBus()
        seen: list[Event] = []

        async def see(event: Event) -> None:
            seen.append(event)

        bus.subscribe("*", see)
        engine = self.engine(bus, None, "payments")
        await engine.start()
        await engine.stop()
        assert seen == []

    async def test_a_stopped_engine_no_longer_listens(self):
        bus = EventBus()
        billing = self.engine(bus, "billing", "payments")
        await billing.start()
        await billing.stop()
        billing.register(ChoreographedSaga(name="payments"))
        await self.engine(bus, "fraud", "payments").start()
        assert billing.identity.conflicts == []
