"""Multi-tenant outbox (ADR-020): event tenant, worker fan-out and publishing."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from sagaz.core.listeners import OutboxSagaListener
from sagaz.core.outbox.brokers.memory import InMemoryBroker
from sagaz.core.outbox.optimistic_publisher import OptimisticPublisher
from sagaz.core.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus
from sagaz.core.outbox.worker import OutboxWorker
from sagaz.core.storage._outbox_tenancy import event_visible, resolve_event_tenant
from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage
from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage
from sagaz.core.storage.interfaces.outbox import OutboxStorageError
from sagaz.core.tenant import (
    CrossTenantAccessError,
    InvalidTenantIdError,
    current_tenant_id,
    is_system_scope,
    system_scope,
    tenant_scope,
)

TENANTS = ("acme", "globex", "default")


def _event(**fields) -> OutboxEvent:
    return OutboxEvent(saga_id="saga-1", event_type="OrderCreated", payload={"n": 1}, **fields)


@pytest.fixture(params=["memory", "sqlite"])
async def storage(request, tmp_path):
    if request.param == "memory":
        yield InMemoryOutboxStorage()
        return
    storage = SQLiteOutboxStorage(str(tmp_path / "outbox.db"))
    await storage.initialize()
    yield storage
    await storage.close()


class TestOutboxEventTenant:
    def test_defaults_to_default_tenant(self):
        assert _event().tenant_id == "default"

    def test_round_trips_through_dict(self):
        event = _event(tenant_id="acme")
        data = event.to_dict()
        assert data["tenant_id"] == "acme"
        assert OutboxEvent.from_dict(data).tenant_id == "acme"

    def test_missing_tenant_in_dict_is_default(self):
        data = _event().to_dict()
        del data["tenant_id"]
        assert OutboxEvent.from_dict(data).tenant_id == "default"
        assert OutboxEvent.from_dict({**data, "tenant_id": None}).tenant_id == "default"


class TestResolveEventTenant:
    def test_unscoped_is_default(self):
        event = _event()
        assert resolve_event_tenant(event) == "default"

    def test_tenant_scope_replaces_the_default_value(self):
        event = _event()
        with tenant_scope("acme"):
            assert resolve_event_tenant(event) == "acme"
        assert event.tenant_id == "acme"

    def test_matching_explicit_tenant_is_accepted(self):
        with tenant_scope("acme"):
            assert resolve_event_tenant(_event(tenant_id="acme")) == "acme"

    @pytest.mark.parametrize("scope", ["acme", None])
    def test_conflicting_explicit_tenant_is_rejected(self, scope):
        event = _event(tenant_id="globex")
        if scope is None:
            with pytest.raises(CrossTenantAccessError):
                resolve_event_tenant(event)
            return
        with tenant_scope(scope), pytest.raises(CrossTenantAccessError):
            resolve_event_tenant(event)

    def test_system_scope_keeps_the_event_tenant(self):
        with system_scope():
            assert resolve_event_tenant(_event(tenant_id="globex")) == "globex"
            assert resolve_event_tenant(_event()) == "default"

    def test_system_scope_rejects_invalid_tenant_ids(self):
        with system_scope(), pytest.raises(InvalidTenantIdError):
            resolve_event_tenant(_event(tenant_id="Not Valid"))

    def test_event_visible(self):
        event = _event(tenant_id="acme")
        assert not event_visible(event)
        with tenant_scope("acme"):
            assert event_visible(event)
        with system_scope():
            assert event_visible(event)


class TestStorageIsolation:
    async def test_tenants_with_the_same_saga_id_are_isolated(self, storage):
        events = {}
        for tenant in TENANTS:
            with tenant_scope(tenant):
                events[tenant] = await storage.insert(_event())
        for tenant in TENANTS:
            with tenant_scope(tenant):
                listed = await storage.get_events_by_saga("saga-1")
                assert [e.event_id for e in listed] == [events[tenant].event_id]
                assert await storage.get_pending_count() == 1
                assert await storage.count() == 1
                others = [e for t, e in events.items() if t != tenant]
                for other in others:
                    assert await storage.get_by_id(other.event_id) is None
        # Unscoped code is the default tenant.
        assert [e.event_id for e in await storage.get_events_by_saga("saga-1")] == [
            events["default"].event_id
        ]

    async def test_dead_letter_queue_is_isolated(self, storage):
        dead = {}
        for tenant in ("acme", "globex"):
            with tenant_scope(tenant):
                event = await storage.insert(_event())
                dead[tenant] = await storage.update_status(
                    event.event_id, OutboxStatus.DEAD_LETTER, error_message="boom"
                )
        with tenant_scope("acme"):
            assert [e.event_id for e in await storage.get_dead_letter_events()] == [
                dead["acme"].event_id
            ]
            with pytest.raises(KeyError):
                await storage.requeue_dead_letter_event(dead["globex"].event_id)
            assert await storage.purge_dead_letter_events() == 1
        with tenant_scope("globex"):
            assert len(await storage.get_dead_letter_events()) == 1
            requeued = await storage.requeue_dead_letter_event(dead["globex"].event_id)
            assert requeued.status == OutboxStatus.PENDING

    async def test_cross_tenant_update_is_not_found(self, storage):
        with tenant_scope("globex"):
            event = await storage.insert(_event())
        with tenant_scope("acme"), pytest.raises((OutboxStorageError, KeyError)):
            await storage.update_status(event.event_id, OutboxStatus.SENT)

    async def test_system_scope_claims_every_tenant(self, storage):
        for tenant in TENANTS:
            with tenant_scope(tenant):
                await storage.insert(_event())
        with system_scope():
            claimed = await storage.claim_batch("w", batch_size=10)
            stats = await storage.get_statistics()
        assert sorted(e.tenant_id for e in claimed) == sorted(TENANTS)
        assert stats.pending_records == 0

    async def test_import_and_export_keep_the_tenant(self, storage):
        with tenant_scope("acme"):
            event = await storage.insert(_event())
            records = [record async for record in storage.export_all()]
        target = InMemoryOutboxStorage()
        with system_scope():
            await target.import_record(records[0])
            await target.import_record(records[0])  # idempotent
        with tenant_scope("acme"):
            assert (await target.get_by_id(event.event_id)).tenant_id == "acme"
        with pytest.raises(CrossTenantAccessError):
            await target.import_record({**records[0], "event_id": "other"})


class TestMemoryBackend:
    async def test_event_id_of_another_tenant_cannot_be_overwritten(self):
        storage = InMemoryOutboxStorage()
        with tenant_scope("acme"):
            event = await storage.insert(_event(event_id="evt-1"))
        with tenant_scope("globex"), pytest.raises(OutboxStorageError):
            await storage.insert(_event(event_id="evt-1"))
        with tenant_scope("acme"):
            assert await storage.get_by_id("evt-1") is event


class TestSQLiteMigration:
    async def test_pre_tenant_rows_become_default(self, tmp_path):
        path = str(tmp_path / "legacy.db")
        async with aiosqlite.connect(path) as conn:
            await conn.execute(
                "CREATE TABLE outbox_events (event_id TEXT PRIMARY KEY, saga_id TEXT NOT NULL, "
                "event_type TEXT NOT NULL, payload TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL)"
            )
            await conn.execute(
                "INSERT INTO outbox_events VALUES "
                "('legacy-1', 'saga-1', 'Evt', '{}', 'pending', '2026-01-01T00:00:00+00:00')"
            )
            await conn.commit()

        storage = SQLiteOutboxStorage(path)
        try:
            event = await storage.get_by_id("legacy-1")
            assert event is not None
            assert event.tenant_id == "default"
            with tenant_scope("acme"):
                assert await storage.get_by_id("legacy-1") is None
        finally:
            await storage.close()


class TestWorker:
    async def test_publishes_every_tenant_with_its_tenant_in_the_message(self, storage):
        ids = {}
        for tenant in TENANTS:
            with tenant_scope(tenant):
                ids[tenant] = (await storage.insert(_event())).event_id
        broker = InMemoryBroker()
        await broker.connect()
        seen_scopes = []

        async def on_published(event):
            seen_scopes.append((event.tenant_id, current_tenant_id()))

        worker = OutboxWorker(storage, broker, OutboxConfig(), on_event_published=on_published)
        assert await worker.process_batch() == 3

        messages = broker.get_messages("OrderCreated")
        assert sorted(m["headers"]["tenant_id"] for m in messages) == sorted(TENANTS)
        for message in messages:
            body = json.loads(message["message"])
            assert body["tenant_id"] == message["headers"]["tenant_id"]
            assert body["event_id"] == ids[body["tenant_id"]]
        # Callbacks and status updates run in the event's own tenant scope.
        assert sorted(seen_scopes) == sorted((t, t) for t in TENANTS)
        for tenant in TENANTS:
            with tenant_scope(tenant):
                assert (await storage.get_by_id(ids[tenant])).status == OutboxStatus.SENT

    async def test_event_header_cannot_spoof_the_tenant(self):
        broker = InMemoryBroker()
        await broker.connect()
        await broker.publish_event(_event(tenant_id="acme", headers={"tenant_id": "globex"}))
        assert broker.get_messages("OrderCreated")[0]["headers"]["tenant_id"] == "acme"

    async def test_failed_publish_is_retried_in_the_event_tenant(self, storage):
        with tenant_scope("acme"):
            event = await storage.insert(_event())
        broker = MagicMock()
        broker.publish_event = AsyncMock(side_effect=RuntimeError("down"))
        worker = OutboxWorker(storage, broker, OutboxConfig(max_retries=1))

        await worker.process_batch()

        with tenant_scope("acme"):
            stored = await storage.get_by_id(event.event_id)
        assert stored.status == OutboxStatus.DEAD_LETTER
        assert stored.tenant_id == "acme"

    async def test_storage_calls_run_in_the_system_scope(self):
        storage = MagicMock()
        scopes = []

        async def claim_batch(**kwargs):
            scopes.append(is_system_scope())
            return []

        async def release_stuck_events(**kwargs):
            scopes.append(is_system_scope())
            return 0

        storage.claim_batch = claim_batch
        storage.release_stuck_events = release_stuck_events
        worker = OutboxWorker(storage, InMemoryBroker())

        assert await worker.process_batch() == 0
        assert await worker.recover_stuck_events() == 0
        assert scopes == [True, True]


class TestEventProducers:
    async def test_listener_events_get_the_saga_tenant(self):
        storage = InMemoryOutboxStorage()
        listener = OutboxSagaListener(storage)
        with tenant_scope("acme"):
            await listener.on_saga_complete("orders", "saga-1", {})
        await listener.on_saga_complete("orders", "saga-2", {})

        with system_scope():
            events = {e.saga_id: e.tenant_id async for e in _all(storage)}
        assert events == {"saga-1": "acme", "saga-2": "default"}

    async def test_optimistic_publish_sends_the_tenant_header(self):
        broker = MagicMock()
        broker.publish = AsyncMock()
        storage = MagicMock()
        storage.mark_sent = AsyncMock()
        publisher = OptimisticPublisher(storage, broker)

        assert await publisher.publish_after_commit(_event(tenant_id="acme", headers={"a": "1"}))
        assert broker.publish.await_args.kwargs["headers"] == {"a": "1", "tenant_id": "acme"}


async def _all(storage):
    for record in [r async for r in storage.export_all()]:
        yield OutboxEvent.from_dict(record)
