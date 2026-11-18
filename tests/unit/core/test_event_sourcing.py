"""Event-sourced saga storage (ADR-033, #57)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from prometheus_client import REGISTRY

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.events import (
    SagaCompleted,
    SagaEvent,
    SagaStarted,
    StepExecuted,
    StepFailed,
    UnrecognizedEvent,
    event_class,
    json_safe,
)
from sagaz.core.storage.event_store import (
    InMemoryEventStore,
    SagaEventRecorder,
    SagaSnapshot,
    create_event_store,
    event_sourcing_settings,
)
from sagaz.core.storage.event_store import recorder as recorder_module
from sagaz.core.storage.event_store.sqlite import SQLiteEventStore
from sagaz.core.tenant import system_scope, tenant_scope
from sagaz.projections import SagaSummaryProjection, build_projection, load_projection


def _sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryEventStore()
        return
    async with SQLiteEventStore(str(tmp_path / "events.db")) as sqlite_store:
        yield sqlite_store


def make_saga(store, *, threshold=50, fail_charge=False, fail_release=False, slow=False):
    class OrderSaga(Saga):
        saga_name = "order"

        class Meta:
            storage_strategy = "event_sourced"
            event_store = store
            snapshot_threshold = threshold

        @action("reserve")
        async def reserve(self, ctx):
            return {"reserved": ctx["order_id"]}

        @compensate("reserve")
        async def release(self, ctx):
            if fail_release:
                msg = "warehouse offline"
                raise RuntimeError(msg)

        @action("charge", depends_on=["reserve"], timeout_seconds=0.05 if slow else 60)
        async def charge(self, ctx):
            if slow:
                await asyncio.sleep(1)
            if fail_charge:
                msg = "card declined"
                raise ValueError(msg)
            return {"charged": 40}

    return OrderSaga()


def types(events):
    return [e.event_type for e in events]


class TestEvents:
    def test_round_trip_keeps_identity_time_and_payload(self):
        event = StepExecuted(
            "s-1",
            sequence=3,
            saga_name="order",
            tenant_id="acme",
            metadata={"k": 1},
            step_name="charge",
            step_result={"at": datetime(2026, 1, 1, tzinfo=UTC)},
            duration_ms=1.5,
        )
        restored = SagaEvent.from_dict(event.to_dict())
        assert restored.event_id == event.event_id
        assert restored.occurred_at == event.occurred_at
        assert (restored.sequence, restored.tenant_id, restored.metadata) == (3, "acme", {"k": 1})
        assert restored.step_result == {"at": "2026-01-01T00:00:00+00:00"}
        assert restored.event_type == "StepExecuted" == event_class("StepExecuted").event_type

    def test_unknown_types_survive_a_round_trip(self):
        data = {**SagaStarted("s").to_dict(), "event_type": "FromTheFuture", "payload": {"x": 1}}
        event = SagaEvent.from_dict(data)
        assert isinstance(event, UnrecognizedEvent)
        assert (event.original_type, event.data) == ("FromTheFuture", {"x": 1})
        assert event.to_dict()["event_type"] == "FromTheFuture"

    def test_minimal_payloads_get_defaults(self):
        event = SagaEvent.from_dict({"event_type": "SagaStarted", "saga_id": "s"})
        assert (event.sequence, event.tenant_id, event.initial_context) == (0, "default", {})
        naive = SagaEvent.from_dict({"saga_id": "s", "occurred_at": "2026-01-01T00:00:00"})
        assert naive.occurred_at.tzinfo is UTC

    def test_json_safe_stringifies_unknown_objects(self):
        assert json_safe({"o": object, "s": {1}}) == {"o": str(object), "s": [1]}


class TestStores:
    async def test_streams_are_numbered_per_saga(self, store):
        for saga_id in ("a", "b", "a"):
            await store.append(SagaStarted(saga_id))
        assert [e.sequence for e in await store.load_stream("a")] == [1, 2]
        assert [e.sequence for e in await store.load_stream("b")] == [1]
        assert [e.sequence for e in await store.load_stream_after("a", 1)] == [2]
        assert await store.load_stream("missing") == []

    async def test_concurrent_appends_get_distinct_sequences(self, store):
        await asyncio.gather(*(store.append(StepFailed("a", step_name=str(i))) for i in range(20)))
        assert [e.sequence for e in await store.load_stream("a")] == list(range(1, 21))

    async def test_latest_snapshot_wins(self, store):
        assert await store.load_latest_snapshot("a") is None
        await store.save_snapshot(SagaSnapshot("a", 10, {"n": 10}))
        await store.save_snapshot(SagaSnapshot("a", 20, {"n": 20}))
        await store.save_snapshot(SagaSnapshot("a", 20, {"n": 21}))  # replaces
        latest = await store.load_latest_snapshot("a")
        assert (latest.sequence, latest.state) == (20, {"n": 21})

    async def test_tenants_are_isolated(self, store):
        with tenant_scope("acme"):
            await store.append(SagaStarted("a", tenant_id="acme"))
            await store.save_snapshot(SagaSnapshot("a", 1, {}, "acme"))
        with tenant_scope("globex"):
            await store.append(SagaStarted("a", tenant_id="globex"))
            assert [e.tenant_id for e in await store.load_stream("a")] == ["globex"]
            assert await store.load_latest_snapshot("a") is None
        with tenant_scope("acme"):
            assert [e.sequence for e in await store.load_stream("a")] == [1]
        with system_scope():
            assert sorted(e.tenant_id for e in await store.load_stream("a")) == ["acme", "globex"]

    async def test_a_tenant_cannot_write_for_another(self, store):
        with tenant_scope("acme"), pytest.raises(Exception, match="globex"):
            await store.append(SagaStarted("a", tenant_id="globex"))

    def test_factory(self, tmp_path):
        assert isinstance(create_event_store("memory://"), InMemoryEventStore)
        sqlite_store = create_event_store(f"sqlite://{tmp_path / 'e.db'}")
        assert sqlite_store.db_path == str(tmp_path / "e.db")
        assert create_event_store("sqlite://").db_path == ":memory:"
        assert type(create_event_store("postgresql://u@h/db")).__name__ == "PostgreSQLEventStore"
        with pytest.raises(ValueError, match="Unsupported"):
            create_event_store("mongodb://x")


class TestEventSourcedSaga:
    async def test_completed_run(self, store):
        await make_saga(store).run({"order_id": "o-1"}, saga_id="s-1")
        events = await store.load_stream("s-1")
        assert types(events) == ["SagaStarted", "StepExecuted", "StepExecuted", "SagaCompleted"]
        assert {e.saga_name for e in events} == {"order"}
        assert events[0].initial_context == {"order_id": "o-1", "saga_id": "s-1"}
        state = await load_projection(store, "s-1")
        assert state.status == "completed"
        assert state.context["charged"] == 40
        assert {name: s.status for name, s in state.steps.items()} == {
            "reserve": "completed",
            "charge": "completed",
        }

    async def test_rolled_back_run(self, store):
        with pytest.raises(ValueError, match="declined"):
            await make_saga(store, fail_charge=True).run({"order_id": "o-2"}, saga_id="s-2")
        events = await store.load_stream("s-2")
        assert types(events) == [
            "SagaStarted",
            "StepExecuted",
            "StepFailed",
            "CompensationStarted",
            "StepCompensated",
            "SagaRolledBack",
        ]
        state = await load_projection(store, "s-2")
        assert (state.status, state.failed_step) == ("rolled_back", "charge")
        assert state.error == "ValueError: card declined"
        assert state.steps["reserve"].status == "compensated"

    async def test_a_failed_compensation_fails_the_saga(self, store):
        saga = make_saga(store, fail_charge=True, fail_release=True)
        with pytest.raises(ValueError):
            await saga.run({"order_id": "o-3"}, saga_id="s-3")
        events = await store.load_stream("s-3")
        assert types(events)[-2:] == ["StepCompensationFailed", "SagaFailed"]
        state = await load_projection(store, "s-3")
        assert state.status == "failed"
        assert state.steps["reserve"].status == "compensation_failed"
        assert state.error == "ValueError: card declined"

    async def test_timeouts_are_recorded(self, store):
        with pytest.raises(TimeoutError):
            await make_saga(store, slow=True).run({"order_id": "o-4"}, saga_id="s-4")
        failed = [e for e in await store.load_stream("s-4") if e.event_type == "StepFailed"]
        assert failed[0].error_message == "timed out after 0.05s"

    async def test_a_rerun_continues_the_stream(self, store):
        saga = make_saga(store)
        await saga.run({"order_id": "o-5"}, saga_id="s-5")
        await saga.run({"order_id": "o-5"}, saga_id="s-5")
        events = await store.load_stream("s-5")
        assert [e.sequence for e in events] == list(range(1, 9))
        state = await load_projection(store, "s-5")
        assert (state.runs, state.status, state.event_count) == (2, "completed", 8)

    async def test_snapshots_every_threshold_events(self, store):
        await make_saga(store, threshold=3).run({"order_id": "o"}, saga_id="s-6")
        snapshot = await store.load_latest_snapshot("s-6")
        assert snapshot.sequence == 3
        assert snapshot.state["steps"]["charge"]["status"] == "completed"
        state = await load_projection(store, "s-6")
        assert (state.status, state.last_sequence, state.event_count) == ("completed", 4, 4)

    async def test_runs_in_the_tenant_scope(self, store):
        await make_saga(store).run({"order_id": "o"}, saga_id="s-7", tenant_context="acme")
        assert await store.load_stream("s-7") == []
        with tenant_scope("acme"):
            events = await store.load_stream("s-7")
        assert {e.tenant_id for e in events} == {"acme"}

    async def test_snapshot_strategy_records_nothing(self, store):
        saga = make_saga(store)
        type(saga).Meta.storage_strategy = "snapshot"
        await saga.run({"order_id": "o"}, saga_id="s-8")
        assert await store.load_stream("s-8") == []

    async def test_metrics(self, store):
        labels = {"saga_name": "order", "event_type": "SagaCompleted", "outcome": "appended"}
        before = _sample("sagaz_event_store_events_total", **labels)
        await make_saga(store).run({"order_id": "o"}, saga_id="s-9")
        assert _sample("sagaz_event_store_events_total", **labels) == before + 1


class BrokenStore(InMemoryEventStore):
    def __init__(self, fail_append=False, fail_snapshot=False, fail_load=False):
        super().__init__()
        self.fail_append, self.fail_snapshot, self.fail_load = fail_append, fail_snapshot, fail_load

    async def append(self, event):
        if self.fail_append:
            msg = "disk full"
            raise OSError(msg)
        return await super().append(event)

    async def save_snapshot(self, snapshot):
        if self.fail_snapshot:
            msg = "disk full"
            raise OSError(msg)
        await super().save_snapshot(snapshot)

    async def load_latest_snapshot(self, saga_id):
        if self.fail_load:
            msg = "unreachable"
            raise OSError(msg)
        return await super().load_latest_snapshot(saga_id)


class TestRecorder:
    async def test_append_failures_do_not_fail_the_saga(self):
        store = BrokenStore(fail_append=True)
        labels = {"saga_name": "order", "event_type": "SagaStarted", "outcome": "error"}
        before = _sample("sagaz_event_store_events_total", **labels)
        result = await make_saga(store).run({"order_id": "o"}, saga_id="r-1")
        assert result["charged"] == 40
        assert _sample("sagaz_event_store_events_total", **labels) == before + 1

    async def test_snapshot_failures_are_counted(self):
        store = BrokenStore(fail_snapshot=True)
        labels = {"saga_name": "order", "outcome": "error"}
        before = _sample("sagaz_event_store_snapshots_total", **labels)
        await make_saga(store, threshold=1).run({"order_id": "o"}, saga_id="r-2")
        assert _sample("sagaz_event_store_snapshots_total", **labels) == before + 4
        assert len(await store.load_stream("r-2")) == 4

    async def test_an_unreadable_stream_still_records(self):
        store = BrokenStore(fail_load=True)
        await make_saga(store).run({"order_id": "o"}, saga_id="r-3")
        assert len(await store.load_stream("r-3")) == 4

    async def test_events_from_another_writer_are_folded_in(self):
        store = InMemoryEventStore()
        recorder = SagaEventRecorder(store, "r-4", "order", snapshot_threshold=2)
        await recorder.open()
        await recorder.record(SagaStarted("ignored"))
        await store.append(StepExecuted("r-4", step_name="elsewhere"))  # another process
        await recorder.record(SagaCompleted("ignored"))
        assert recorder.projection.last_sequence == 3
        assert "elsewhere" in recorder.projection.steps
        assert (await store.load_latest_snapshot("r-4")).sequence == 3  # crossed 2

    def test_threshold_must_be_positive(self):
        with pytest.raises(ValueError, match="at least 1"):
            SagaEventRecorder(InMemoryEventStore(), "s", "n", snapshot_threshold=0)


class TestSettings:
    def test_meta_then_config(self, monkeypatch):
        store = InMemoryEventStore()

        class Plain(Saga):
            pass

        plain = Plain(name="plain", config=SagaConfig(metrics=False, logging=False))
        assert event_sourcing_settings(plain) is None

        config = SagaConfig(
            storage_strategy="event_sourced",
            event_store=store,
            snapshot_threshold=7,
            metrics=False,
            logging=False,
        )
        assert event_sourcing_settings(Saga(name="imperative", config=config)) == (store, 7)

    def test_urls_share_one_store(self, monkeypatch):
        monkeypatch.setattr(recorder_module, "_stores_by_url", {})
        config = SagaConfig(
            storage_strategy="event_sourced", event_store="memory://", metrics=False, logging=False
        )
        first, _ = event_sourcing_settings(Saga(name="a", config=config))
        second, _ = event_sourcing_settings(Saga(name="b", config=config))
        assert first is second

    def test_invalid_settings(self):
        with pytest.raises(ValueError, match="storage_strategy must be"):
            event_sourcing_settings(Saga(name="x", config=SagaConfig(storage_strategy="nope")))
        with pytest.raises(ValueError, match="needs an event store"):
            event_sourcing_settings(
                Saga(name="x", config=SagaConfig(storage_strategy="event_sourced"))
            )

    def test_config_copies_keep_the_settings(self):
        config = SagaConfig(
            storage_strategy="event_sourced", event_store="memory://", snapshot_threshold=9
        )
        for copy in (config.with_storage(None), config.with_broker(None)):
            assert (copy.storage_strategy, copy.event_store, copy.snapshot_threshold) == (
                "event_sourced",
                "memory://",
                9,
            )


class TestProjection:
    def test_round_trip_and_idempotent_apply(self):
        events = [
            SagaStarted("p", sequence=1, initial_context={"a": 1}),
            StepExecuted("p", sequence=2, step_name="s", step_result=5),
        ]
        projection = build_projection("p", events)
        projection.apply(events[1])  # already applied
        assert projection.event_count == 2
        restored = SagaSummaryProjection.from_dict({**projection.to_dict(), "extra": 1})
        assert restored == projection

    async def test_load_projection_of_unknown_saga(self):
        assert await load_projection(InMemoryEventStore(), "none") is None
