"""Orchestrated sagas write the unified saga log (ADR-041 phase 2, #465)."""

from __future__ import annotations

import asyncio

import pytest
from click.testing import CliRunner

from sagaz import Saga, action, compensate
from sagaz.cli.app import cli
from sagaz.core.config import SagaConfig
from sagaz.core.events import SagaStarted, StepExecuted
from sagaz.core.exceptions import SagaFailedError
from sagaz.core.saga import Saga as ClassicSaga
from sagaz.core.storage.event_store.recorder import event_sourcing_settings
from sagaz.core.storage.saga_log import InMemorySagaLogStore, LogWrite
from sagaz.core.storage.saga_log.event_store import SagaLogEventStore
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore
from sagaz.core.tenant import tenant_scope
from sagaz.projections import load_projection


@pytest.fixture(params=["memory", "sqlite"])
async def log(request, tmp_path):
    if request.param == "memory":
        yield InMemorySagaLogStore()
        return
    store = SQLiteSagaLogStore(str(tmp_path / "log.db"))
    yield store
    await store.close()


def order_saga(log, *, fail_charge=False, fail_release=False, slow=False):
    class OrderSaga(Saga):
        saga_name = "order"

        class Meta:
            storage_layout = "unified"
            saga_log = log
            participant = "orders-service"
            snapshot_threshold = 3

        @action("reserve")
        async def reserve(self, ctx):
            return {"reservation": f"r-{ctx['order_id']}"}

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
            return {"charge": "ch-1"}

    return OrderSaga(config=SagaConfig(metrics=False, logging=False))


async def state(log, tid):
    transaction = await log.get_transaction(tid)
    activities = {a.activity_id: a for a in await log.activities(tid)}
    events = await log.events(tid)
    return transaction, activities, events


class TestDeclarative:
    async def test_completed(self, log):
        await order_saga(log).run({"order_id": "o-1"}, saga_id="s-1")
        transaction, activities, events = await state(log, "s-1")
        assert (transaction.coordination, transaction.flow) == ("orchestrated", "order")
        assert (transaction.status, transaction.initiator) == ("completed", "orders-service")
        assert transaction.ended_at is not None
        assert transaction.context == {
            "order_id": "o-1",
            "saga_id": "s-1",
            "reservation": "r-o-1",
            "charge": "ch-1",
        }
        assert {k: a.status for k, a in activities.items()} == {
            "reserve": "completed",
            "charge": "completed",
        }
        assert activities["reserve"].result == {"reservation": "r-o-1"}
        assert activities["reserve"].participant == "orders-service"
        assert activities["charge"].duration_ms >= 0
        assert [e.event_type for e in events] == [
            "SagaStarted",
            "StepExecuted",
            "StepExecuted",
            "SagaCompleted",
        ]
        assert {e.kind for e in events} == {"lifecycle"}
        assert {e.source for e in events} == {"orders-service"}
        # status changes: start (v1) → completed (v2)
        assert transaction.version == 2

    async def test_rolled_back(self, log):
        with pytest.raises(SagaFailedError, match="declined"):
            await order_saga(log, fail_charge=True).run({"order_id": "o-2"}, saga_id="s-2")
        transaction, activities, _ = await state(log, "s-2")
        assert transaction.status == "rolled_back"
        assert transaction.version == 3  # executing → compensating → rolled_back
        assert activities["reserve"].status == "compensated"
        assert activities["charge"].status == "failed"
        assert activities["charge"].error == "ValueError: card declined"

    async def test_a_failed_compensation(self, log):
        saga = order_saga(log, fail_charge=True, fail_release=True)
        with pytest.raises(SagaFailedError):
            await saga.run({"order_id": "o-3"}, saga_id="s-3")
        transaction, activities, _ = await state(log, "s-3")
        assert transaction.status == "failed"
        assert activities["reserve"].status == "compensation_failed"
        assert activities["reserve"].error == "RuntimeError: warehouse offline"

    async def test_a_timeout(self, log):
        with pytest.raises(SagaFailedError):
            await order_saga(log, slow=True).run({"order_id": "o-4"}, saga_id="s-4")
        _, activities, _ = await state(log, "s-4")
        assert activities["charge"].error == "TimeoutError: timed out after 0.05s"

    async def test_a_rerun_starts_the_transaction_again(self, log):
        saga = order_saga(log)
        await saga.run({"order_id": "o-5"}, saga_id="s-5")
        await saga.run({"order_id": "o-5"}, saga_id="s-5", allow_rerun=True)
        transaction, _, events = await state(log, "s-5")
        assert (transaction.status, transaction.version) == ("completed", 4)
        assert [e.sequence for e in events] == list(range(1, 9))

    async def test_snapshots_and_projection_read_the_log(self, log):
        await order_saga(log).run({"order_id": "o-6"}, saga_id="s-6")
        store = SagaLogEventStore(log)
        assert (await store.load_latest_snapshot("s-6")).sequence == 3
        projection = await load_projection(store, "s-6")
        assert (projection.status, projection.last_sequence) == ("completed", 4)

    async def test_tenants(self, log):
        await order_saga(log).run({"order_id": "o"}, saga_id="s-7", tenant_context="acme")
        assert await log.get_transaction("s-7") is None
        with tenant_scope("acme"):
            assert (await log.get_transaction("s-7")).status == "completed"

    async def test_imperative_sagas_via_config(self, log):
        config = SagaConfig(storage_layout="unified", saga_log=log, metrics=False, logging=False)
        saga = Saga(name="adhoc", config=config)

        async def step(ctx):
            return {"done": True}

        saga.add_step("only", step)
        await saga.run({}, saga_id="s-8")
        transaction, activities, _ = await state(log, "s-8")
        assert (transaction.status, transaction.initiator) == ("completed", "orchestrator")
        assert activities["only"].status == "completed"
        assert config.with_storage(None).saga_log is log


class TestClassic:
    async def test_sequential_with_retries_and_participant(self, log):
        attempts = []

        async def flaky(ctx):
            attempts.append(1)
            if len(attempts) == 1:
                msg = "transient"
                raise ConnectionError(msg)
            return {"paid": True}

        async def undo(result, ctx):
            return None

        saga = ClassicSaga(
            name="billing", saga_log=log, participant="billing-svc", retry_backoff_base=0.001
        )
        await saga.add_step("charge", flaky, undo, max_retries=2)
        await saga.execute()
        transaction, activities, _ = await state(log, saga.saga_id)
        assert (transaction.status, transaction.initiator) == ("completed", "billing-svc")
        assert (activities["charge"].status, activities["charge"].attempt) == ("completed", 2)

    async def test_dag_rollback(self, log):
        async def ok(ctx):
            return {"x": 1}

        async def boom(ctx):
            msg = "declined"
            raise ValueError(msg)

        async def undo(result, ctx):
            return None

        saga = ClassicSaga(name="dag", saga_log=log)
        await saga.add_step("a", ok, undo, max_retries=0, dependencies=set())
        await saga.add_step("b", boom, undo, max_retries=0, dependencies={"a"})
        await saga.execute()
        transaction, activities, _ = await state(log, saga.saga_id)
        assert transaction.status == "rolled_back"
        assert (activities["a"].status, activities["b"].status) == ("compensated", "failed")


class TestAdapter:
    async def test_regions_and_attempts_come_from_metadata(self):
        log = InMemorySagaLogStore()
        store = SagaLogEventStore(log, "eu-worker")
        await store.append(SagaStarted("t", saga_name="checkout"))
        await store.append(
            StepExecuted("t", step_name="charge", metadata={"region": "eu-west-1", "attempt": 3})
        )
        (activity,) = await log.activities("t")
        assert (activity.region, activity.attempt, activity.participant) == (
            "eu-west-1",
            3,
            "eu-worker",
        )
        (started, executed) = await store.load_stream("t")
        assert (started.saga_name, executed.metadata["region"]) == ("checkout", "eu-west-1")

    async def test_an_outcome_without_a_recorded_start_creates_the_transaction(self):
        from sagaz.core.events import SagaCompleted

        log = InMemorySagaLogStore()
        await SagaLogEventStore(log).append(SagaCompleted("t", saga_name="late"))
        assert (await log.get_transaction("t")).status == "completed"

    async def test_state_and_log_are_written_together(self):
        class Broken(InMemorySagaLogStore):
            async def write(self, batch: LogWrite):
                msg = "disk full"
                raise OSError(msg)

        log = Broken()
        with pytest.raises(OSError, match="disk full"):
            await SagaLogEventStore(log).append(SagaStarted("t", saga_name="x"))
        assert await log.get_transaction("t") is None
        assert await log.events("t") == []

    async def test_close_closes_the_log(self):
        closed = []

        class Tracking(InMemorySagaLogStore):
            async def close(self):
                closed.append(True)

        await SagaLogEventStore(Tracking()).close()
        assert closed == [True]


class TestSettings:
    def test_layouts(self):
        log = InMemorySagaLogStore()
        unified = SagaConfig(storage_layout="unified", saga_log=log, participant="svc")
        store, threshold = event_sourcing_settings(Saga(name="x", config=unified))
        assert isinstance(store, SagaLogEventStore)
        assert (store.log, store.participant, threshold) == (log, "svc", 50)
        with pytest.raises(ValueError, match="needs a saga log"):
            event_sourcing_settings(Saga(name="x", config=SagaConfig(storage_layout="unified")))
        with pytest.raises(ValueError, match="storage_layout must be"):
            event_sourcing_settings(Saga(name="x", config=SagaConfig(storage_layout="v2")))
        assert event_sourcing_settings(Saga(name="x", config=SagaConfig())) is None

    def test_urls_share_one_log(self, monkeypatch):
        from sagaz.core.storage.event_store import recorder

        monkeypatch.setattr(recorder, "_logs_by_url", {})
        config = SagaConfig(storage_layout="unified", saga_log="memory://")
        first, _ = event_sourcing_settings(Saga(name="a", config=config))
        second, _ = event_sourcing_settings(Saga(name="b", config=config))
        assert first.log is second.log


def test_event_log_reads_the_unified_layout(tmp_path):
    path = tmp_path / "log.db"

    async def record():
        async with SQLiteSagaLogStore(str(path)) as log:
            with pytest.raises(SagaFailedError):
                await order_saga(log, fail_charge=True).run({"order_id": "o"}, saga_id="bad")

    asyncio.run(record())
    result = CliRunner().invoke(
        cli, ["event-log", "bad", "--store-url", f"sqlite://{path}", "--layout", "unified"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == "Saga bad (order, tenant default): rolled_back"
    assert "CompensationStarted" in result.output
