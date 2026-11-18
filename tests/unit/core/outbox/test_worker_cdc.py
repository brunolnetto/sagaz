"""The outbox worker's CDC mode (ADR-011, #50), with a scripted CDC source."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY

from sagaz.core.outbox.brokers.memory import InMemoryBroker
from sagaz.core.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus
from sagaz.core.outbox.worker import OutboxWorker
from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage
from sagaz.core.tenant import system_scope
from sagaz.integrations.cdc import CDCChange, CDCError, CDCSource


class ScriptedSource:
    """A CDCSource that yields prepared batches, then waits (or fails)."""

    def __init__(self, batches, *, name="scripted", fail_with=None):
        self.name = name
        self.batches = batches
        self.fail_with = fail_with
        self.acked: list = []
        self.started = self.stopped = False
        self.drained = asyncio.Event()

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def changes(self):
        for batch in self.batches:
            yield batch
        self.drained.set()
        if self.fail_with:
            raise self.fail_with
        await asyncio.Event().wait()  # a live stream: wait for more

    async def ack(self, position):
        self.acked.append(position)


def _sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def _inserted(storage, tenant="default", n=1, start=0):
    """Insert outbox rows (as the application would) and capture them as changes."""
    changes = []
    for i in range(start, start + n):
        event = OutboxEvent(
            saga_id=f"s{i}", event_type="order.created", payload={"i": i}, tenant_id=tenant
        )
        with system_scope():
            await storage.insert(event)
        committed = datetime.now(UTC) - timedelta(milliseconds=20)
        changes.append(CDCChange(event=event, committed_at=committed, position=i))
    return changes


@pytest.fixture
async def broker():
    b = InMemoryBroker()
    await b.connect()
    return b


def _published(broker):
    return [json.loads(m["message"]) for msgs in broker._messages.values() for m in msgs]


async def _run_until_drained(worker, source):
    task = asyncio.create_task(worker.start())
    await asyncio.wait_for(source.drained.wait(), 5)
    await asyncio.sleep(0.05)
    await worker.stop()
    await asyncio.wait_for(task, 5)


class TestBatchMarking:
    async def test_published_events_are_marked_sent_in_one_call(self, broker):
        storage = InMemoryOutboxStorage()
        changes = await _inserted(storage, n=3)
        calls = []
        original = storage.mark_sent_batch

        async def recording(event_ids):
            calls.append(list(event_ids))
            return await original(event_ids)

        storage.mark_sent_batch = recording
        published = []
        worker = OutboxWorker(storage, broker, on_event_published=_collect(published))

        assert await worker.process_changes(changes) == 3

        assert calls == [[c.event.event_id for c in changes]]
        assert len(published) == 3
        assert worker.get_stats()["events_processed"] == 3

    async def test_marking_failure_is_counted_and_streaming_continues(self, broker, caplog):
        storage = InMemoryOutboxStorage()
        changes = await _inserted(storage, n=2)

        async def broken(event_ids):
            msg = "db down"
            raise RuntimeError(msg)

        storage.mark_sent_batch = broken
        worker = OutboxWorker(storage, broker)
        before = _sample("sagaz_cdc_errors_total", source="unit-m", kind="mark_sent")

        assert await worker.process_changes(changes, "unit-m") == 2  # published nonetheless

        assert _sample("sagaz_cdc_errors_total", source="unit-m", kind="mark_sent") == before + 1
        assert "could not mark 2 sent: db down" in caplog.text
        with system_scope():
            assert await storage.get_pending_count() == 2  # the sweep will republish them

    async def test_default_mark_sent_batch_updates_each_event(self):
        storage = InMemoryOutboxStorage()
        changes = await _inserted(storage, n=2)
        with system_scope():
            assert await storage.mark_sent_batch([c.event.event_id for c in changes]) == 2
            assert await storage.get_pending_count() == 0
            assert await storage.mark_sent_batch([]) == 0


def _collect(into):
    async def callback(event):
        into.append(event.event_id)

    return callback


class TestCDCMode:
    async def test_streamed_events_are_published_marked_sent_and_acked(self, broker):
        storage = InMemoryOutboxStorage()
        first, second = await _inserted(storage, n=2), await _inserted(storage, n=1, start=2)
        source = ScriptedSource([first, [], second], name="unit-a")
        config = OutboxConfig(cdc_sweep_interval_seconds=None)
        worker = OutboxWorker(storage, broker, config, cdc_source=source)
        lag_before = _sample("sagaz_cdc_lag_seconds_count", source="unit-a")

        await _run_until_drained(worker, source)

        assert source.started
        assert source.stopped
        assert source.acked == [1, 2]  # last position of each non-empty batch
        assert sorted(e["payload"]["i"] for e in _published(broker)) == [0, 1, 2]
        with system_scope():
            assert await storage.get_pending_count() == 0
            assert (await storage.get_by_id(first[0].event.event_id)).status == OutboxStatus.SENT
        assert _sample("sagaz_cdc_events_total", source="unit-a") == 3
        assert _sample("sagaz_cdc_lag_seconds_count", source="unit-a") - lag_before == 3
        assert _sample("sagaz_cdc_lag_seconds_sum", source="unit-a") >= 3 * 0.02

    async def test_each_event_is_published_in_its_tenant(self, broker):
        storage = InMemoryOutboxStorage()
        changes = [*await _inserted(storage, "acme"), *await _inserted(storage, "globex", start=1)]
        source = ScriptedSource([changes])
        worker = OutboxWorker(
            storage, broker, OutboxConfig(cdc_sweep_interval_seconds=None), cdc_source=source
        )

        await _run_until_drained(worker, source)

        assert sorted(e["tenant_id"] for e in _published(broker)) == ["acme", "globex"]

    async def test_failed_publish_is_retried_by_the_sweep(self, broker):
        storage = InMemoryOutboxStorage()
        changes = await _inserted(storage)
        calls = {"n": 0}
        original = broker.publish_event

        async def flaky(event):
            calls["n"] += 1
            if calls["n"] == 1:
                msg = "broker down"
                raise ConnectionError(msg)
            return await original(event)

        broker.publish_event = flaky
        source = ScriptedSource([changes])
        config = OutboxConfig(cdc_sweep_interval_seconds=0.05, cdc_sweep_min_age_seconds=0)
        worker = OutboxWorker(storage, broker, config, cdc_source=source)

        task = asyncio.create_task(worker.start())
        for _ in range(100):
            await asyncio.sleep(0.02)
            if _published(broker):
                break
        await worker.stop()
        await asyncio.wait_for(task, 5)

        assert calls["n"] == 2  # the stream's attempt failed, the sweep's succeeded
        assert len(_published(broker)) == 1
        assert source.acked == [0]  # the failure was recorded, so the batch was acked

    async def test_sweep_leaves_fresh_events_to_the_stream(self, broker):
        storage = InMemoryOutboxStorage()
        await _inserted(storage)  # pending, but younger than the sweep age
        worker = OutboxWorker(storage, broker, OutboxConfig(cdc_sweep_min_age_seconds=60))
        assert await worker.process_batch(older_than_seconds=60) == 0
        assert await worker.process_batch() == 1

    async def test_stream_failure_stops_the_worker_and_is_counted(self, broker):
        source = ScriptedSource([], name="unit-b", fail_with=CDCError("slot dropped"))
        worker = OutboxWorker(
            InMemoryOutboxStorage(),
            broker,
            OutboxConfig(cdc_sweep_interval_seconds=None),
            cdc_source=source,
        )
        before = _sample("sagaz_cdc_errors_total", source="unit-b", kind="stream")

        with pytest.raises(CDCError, match="slot dropped"):
            await asyncio.wait_for(worker.start(), 5)

        assert source.stopped
        assert _sample("sagaz_cdc_errors_total", source="unit-b", kind="stream") == before + 1

    async def test_event_errors_are_counted_and_do_not_block_the_batch(self, broker):
        storage = InMemoryOutboxStorage()
        changes = await _inserted(storage, n=2)
        worker = OutboxWorker(storage, broker)
        original = worker._publish_change

        async def boom_on_first(event):
            if event.event_id == changes[0].event.event_id:
                msg = "unexpected"
                raise RuntimeError(msg)
            return await original(event)

        worker._publish_change = boom_on_first
        no_commit_time = CDCChange(changes[1].event, None, 1)
        before = _sample("sagaz_cdc_errors_total", source="unit-c", kind="event")

        processed = await worker.process_changes([changes[0], no_commit_time], "unit-c")

        assert processed == 1
        assert _sample("sagaz_cdc_errors_total", source="unit-c", kind="event") == before + 1

    async def test_sweep_errors_are_logged_and_sweeping_continues(self, broker, caplog):
        worker = OutboxWorker(
            InMemoryOutboxStorage(), broker, OutboxConfig(cdc_sweep_interval_seconds=0.01)
        )
        calls = {"n": 0}

        async def failing(older_than_seconds=0.0):
            calls["n"] += 1
            msg = "db down"
            raise RuntimeError(msg)

        worker.process_batch = failing
        sweep = asyncio.create_task(worker._sweep_loop())
        await asyncio.sleep(0.08)
        worker._shutdown_event.set()
        await asyncio.wait_for(sweep, 1)

        assert calls["n"] >= 2
        assert "sweep failed: db down" in caplog.text

    async def test_sweep_logs_what_it_recovers(self, broker, caplog):
        storage = InMemoryOutboxStorage()
        await _inserted(storage, n=2)
        config = OutboxConfig(cdc_sweep_interval_seconds=0.01, cdc_sweep_min_age_seconds=0)
        worker = OutboxWorker(storage, broker, config)
        caplog.set_level("INFO")

        sweep = asyncio.create_task(worker._sweep_loop())
        for _ in range(50):
            await asyncio.sleep(0.01)
            if "swept 2 stale pending events" in caplog.text:
                break
        worker._shutdown_event.set()
        await asyncio.wait_for(sweep, 1)

        assert "swept 2 stale pending events" in caplog.text

    def test_scripted_source_is_a_cdc_source(self):
        assert isinstance(ScriptedSource([]), CDCSource)
