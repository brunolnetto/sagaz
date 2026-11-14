"""Tenant-isolation contract shared by every outbox storage backend (ADR-020).

Runs against the in-memory, SQLite, Redis (an in-process fake and, with
Docker, a real server) and PostgreSQL backends: two tenants writing events for
the same saga id never see each other's events through any tenant-facing
operation, events written without a tenant stay the default tenant's, and the
system scope (used by the outbox worker) spans every tenant.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.interfaces.outbox import OutboxStorageError
from sagaz.core.tenant import CrossTenantAccessError, system_scope, tenant_scope
from tests.unit.core.storage.backends._fake_redis import fake_redis_outbox
from tests.unit.core.storage.backends.test_outbox_dlq_contract import FACTORIES

BACKENDS = [
    "memory",
    "sqlite",
    "fake-redis",
    pytest.param("redis", marks=pytest.mark.integration),
    pytest.param("postgresql", marks=pytest.mark.integration),
]

SAGA = "saga-shared"


async def _fake_redis(request, tmp_path):
    return await fake_redis_outbox()


@pytest.fixture(params=BACKENDS)
async def storage(request, tmp_path):
    factories = {**FACTORIES, "fake-redis": _fake_redis}
    storage = await factories[request.param](request, tmp_path)
    initialize = getattr(storage, "initialize", None)
    if request.param != "fake-redis" and callable(initialize):
        await initialize()
    if request.param == "postgresql":
        async with storage._pool.acquire() as conn:
            await conn.execute("TRUNCATE saga_outbox, saga_outbox_archive")
    yield storage
    await storage.close()


async def _insert(storage, tenant: str | None, **fields) -> OutboxEvent:
    event = OutboxEvent(saga_id=SAGA, event_type="Evt", payload={"n": 1}, **fields)
    if tenant is None:
        return await storage.insert(event)
    with tenant_scope(tenant):
        return await storage.insert(event)


async def _dead_letter(storage, tenant: str, reason: str = "boom") -> OutboxEvent:
    event = await _insert(storage, tenant)
    with tenant_scope(tenant):
        return await storage.update_status(
            event.event_id, OutboxStatus.DEAD_LETTER, error_message=reason
        )


class TestWrites:
    async def test_insert_takes_the_scope_tenant(self, storage):
        event = await _insert(storage, "acme")
        assert event.tenant_id == "acme"
        with tenant_scope("acme"):
            stored = await storage.get_by_id(event.event_id)
        assert stored is not None
        assert stored.tenant_id == "acme"

    async def test_conflicting_explicit_tenant_is_rejected(self, storage):
        with pytest.raises(CrossTenantAccessError):
            await _insert(storage, "acme", tenant_id="globex")

    async def test_system_scope_keeps_the_event_tenant(self, storage):
        with system_scope():
            event = await storage.insert(
                OutboxEvent(saga_id=SAGA, event_type="Evt", payload={}, tenant_id="globex")
            )
        with tenant_scope("globex"):
            assert (await storage.get_by_id(event.event_id)).tenant_id == "globex"


class TestReadsAreScoped:
    async def test_same_saga_id_is_isolated(self, storage):
        a = await _insert(storage, "acme")
        b = await _insert(storage, "globex")

        with tenant_scope("acme"):
            assert [e.event_id for e in await storage.get_events_by_saga(SAGA)] == [a.event_id]
            assert await storage.get_by_id(b.event_id) is None
        with tenant_scope("globex"):
            assert [e.event_id for e in await storage.get_events_by_saga(SAGA)] == [b.event_id]
            assert await storage.get_by_id(a.event_id) is None
        # Code that sets no tenant is the default tenant: it sees neither.
        assert await storage.get_events_by_saga(SAGA) == []

    async def test_counts_are_per_tenant(self, storage):
        await _insert(storage, "acme")
        await _insert(storage, "acme")
        await _insert(storage, "globex")

        with tenant_scope("acme"):
            assert await storage.get_pending_count() == 2
            assert await storage.count() == 2
        with tenant_scope("globex"):
            assert await storage.get_pending_count() == 1
            assert await storage.count() == 1
        with system_scope():
            assert await storage.get_pending_count() == 3
            assert await storage.count() == 3

    async def test_update_of_another_tenants_event_fails(self, storage):
        b = await _insert(storage, "globex")
        with tenant_scope("acme"), pytest.raises((OutboxStorageError, KeyError)):
            await storage.update_status(b.event_id, OutboxStatus.SENT)
        with tenant_scope("globex"):
            assert (await storage.get_by_id(b.event_id)).status == OutboxStatus.PENDING

    async def test_export_is_scoped(self, storage):
        a = await _insert(storage, "acme")
        b = await _insert(storage, "globex")
        with tenant_scope("acme"):
            exported = [record async for record in storage.export_all()]
        assert [record["event_id"] for record in exported] == [a.event_id]
        assert exported[0]["tenant_id"] == "acme"
        with system_scope():
            everything = {record["event_id"] async for record in storage.export_all()}
        assert everything == {a.event_id, b.event_id}


class TestDeadLetterQueueIsScoped:
    async def test_listing(self, storage):
        a = await _dead_letter(storage, "acme")
        b = await _dead_letter(storage, "globex")

        with tenant_scope("acme"):
            assert [e.event_id for e in await storage.get_dead_letter_events()] == [a.event_id]
        with system_scope():
            listed = {e.event_id for e in await storage.get_dead_letter_events()}
        assert listed == {a.event_id, b.event_id}

    async def test_requeue_of_another_tenants_event_is_not_found(self, storage):
        b = await _dead_letter(storage, "globex")
        with tenant_scope("acme"), pytest.raises(KeyError):
            await storage.requeue_dead_letter_event(b.event_id)
        with tenant_scope("globex"):
            requeued = await storage.requeue_dead_letter_event(b.event_id)
        assert requeued.status == OutboxStatus.PENDING
        assert requeued.tenant_id == "globex"

    async def test_purge_only_removes_the_current_tenants_events(self, storage):
        await _dead_letter(storage, "acme")
        b = await _dead_letter(storage, "globex")

        with tenant_scope("acme"):
            assert await storage.purge_dead_letter_events() == 1
            assert await storage.purge_dead_letter_events(older_than=timedelta(0)) == 0
        with tenant_scope("globex"):
            assert [e.event_id for e in await storage.get_dead_letter_events()] == [b.event_id]


class TestDefaultTenantCompatibility:
    async def test_unscoped_events_belong_to_default(self, storage):
        event = await _insert(storage, None)
        assert event.tenant_id == "default"
        assert (await storage.get_by_id(event.event_id)).tenant_id == "default"
        with tenant_scope("default"):
            assert await storage.get_by_id(event.event_id) is not None
        with tenant_scope("acme"):
            assert await storage.get_by_id(event.event_id) is None

    async def test_unscoped_code_cannot_write_for_another_tenant(self, storage):
        with pytest.raises(CrossTenantAccessError):
            await _insert(storage, None, tenant_id="acme")


class TestSystemScope:
    async def test_claim_batch_spans_every_tenant(self, storage):
        expected = {
            (await _insert(storage, tenant)).event_id: tenant or "default"
            for tenant in ("acme", "globex", None)
        }

        with system_scope():
            claimed = await storage.claim_batch("worker-1", batch_size=10)

        assert {e.event_id: e.tenant_id for e in claimed} == expected
        assert all(e.status == OutboxStatus.CLAIMED for e in claimed)

    async def test_tenant_claim_only_sees_its_events(self, storage):
        a = await _insert(storage, "acme")
        await _insert(storage, "globex")
        with tenant_scope("acme"):
            claimed = await storage.claim_batch("worker-1", batch_size=10)
        assert [e.event_id for e in claimed] == [a.event_id]

    async def test_worker_style_update_inside_the_event_tenant(self, storage):
        await _insert(storage, "acme")
        await _insert(storage, "globex")
        with system_scope():
            claimed = await storage.claim_batch("worker-1", batch_size=10)
        for event in claimed:
            with tenant_scope(event.tenant_id):
                await storage.update_status(event.event_id, OutboxStatus.SENT)
        for tenant in ("acme", "globex"):
            with tenant_scope(tenant):
                statuses = [e.status for e in await storage.get_events_by_saga(SAGA)]
            assert statuses == [OutboxStatus.SENT]

    async def test_system_scope_update_and_lookup(self, storage):
        b = await _insert(storage, "globex")
        with system_scope():
            assert (await storage.get_by_id(b.event_id)).tenant_id == "globex"
            updated = await storage.update_status(b.event_id, OutboxStatus.SENT)
        assert updated.status == OutboxStatus.SENT
        assert updated.tenant_id == "globex"

    async def test_stuck_event_release_spans_tenants(self, storage):
        _skip_sqlite_stuck(storage)
        for tenant in ("acme", "globex", None):
            await _insert(storage, tenant)
        with system_scope():
            await storage.claim_batch("worker-1", batch_size=10)
        await asyncio.sleep(0.2)  # let the claims age past a zero threshold
        with system_scope():
            assert await storage.release_stuck_events(claimed_older_than_seconds=0) == 3

    async def test_stuck_event_release_is_scoped(self, storage):
        _skip_sqlite_stuck(storage)
        for tenant in ("acme", "globex", "globex"):
            await _insert(storage, tenant)
        with system_scope():
            await storage.claim_batch("worker-1", batch_size=10)
        await asyncio.sleep(0.2)  # let the claims age past a zero threshold
        with tenant_scope("acme"):
            assert await storage.release_stuck_events(claimed_older_than_seconds=0) == 1


def _skip_sqlite_stuck(storage) -> None:
    from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

    if isinstance(storage, SQLiteOutboxStorage):
        # SQLite compares ISO-8601 claimed_at strings with datetime('now') and
        # cannot express a negative age; its tenant filter is covered elsewhere.
        pytest.skip("SQLite stuck-event detection cannot be forced in a test")
