"""Redis outbox key layout per tenant (ADR-020), against an in-process fake."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.interfaces.outbox import OutboxStorageError
from sagaz.core.tenant import system_scope, tenant_scope
from tests.unit.core.storage.backends._fake_redis import fake_redis_outbox


def _event(**fields) -> OutboxEvent:
    return OutboxEvent(saga_id="s", event_type="Evt", payload={}, **fields)


@pytest.fixture
async def storage():
    return await fake_redis_outbox(prefix="sagaz:outbox")


class TestKeys:
    async def test_default_tenant_keeps_the_historical_keys(self, storage):
        event = await storage.insert(_event())
        redis = storage._redis
        assert f"sagaz:outbox:meta:{event.event_id}".encode() in redis.hashes
        assert b"sagaz:outbox:events" in redis.streams
        assert b"sagaz:outbox:tenants" not in redis.sets

    async def test_other_tenants_are_namespaced_and_indexed(self, storage):
        with tenant_scope("acme"):
            event = await storage.insert(_event())
        redis = storage._redis
        assert f"sagaz:acme:sagaz:outbox:meta:{event.event_id}".encode() in redis.hashes
        assert b"sagaz:acme:sagaz:outbox:events" in redis.streams
        assert redis.sets[b"sagaz:outbox:tenants"] == {b"acme"}
        assert "g" in redis.streams[b"sagaz:acme:sagaz:outbox:events"].groups

    async def test_imported_events_register_their_tenant(self, storage):
        with system_scope():
            await storage.import_record(_event(tenant_id="globex").to_dict())
        assert storage._redis.sets[b"sagaz:outbox:tenants"] == {b"globex"}

    def test_system_scope_needs_an_explicit_tenant_for_keys(self, storage):
        with system_scope():
            assert storage._tenant_prefix("acme") == "sagaz:acme:sagaz:outbox"
            with pytest.raises(RuntimeError):
                storage._meta_key("evt")


class TestSystemScope:
    async def test_statistics_span_tenants(self, storage):
        await storage.insert(_event())
        with tenant_scope("acme"):
            await storage.insert(_event())
        with system_scope():
            stats = await storage.get_statistics()
        assert stats.pending_records == 2
        assert (await storage.health_check()).details["stream_length"] == 1

    async def test_unknown_event_lookups(self, storage):
        with tenant_scope("acme"):
            await storage.insert(_event())
        with system_scope():
            assert await storage.get_by_id("missing") is None
            with pytest.raises(OutboxStorageError):
                await storage.update_status("missing", OutboxStatus.SENT)
            with pytest.raises(KeyError):
                await storage.requeue_dead_letter_event("missing")

    async def test_update_uses_the_event_tenant_hint(self, storage):
        with tenant_scope("acme"):
            event = await storage.insert(_event())
        with system_scope():
            updated = await storage.update_status(event.event_id, OutboxStatus.SENT, event=event)
        assert updated.tenant_id == "acme"

    async def test_messages_of_unmapped_streams_use_the_current_scope(self, storage):
        event = await storage.insert(_event())
        response = await storage._redis.xreadgroup("g", "w", {b"sagaz:outbox:events": ">"})
        claimed = await storage._process_claimed_messages(response, "w")
        assert [e.event_id for e in claimed] == [event.event_id]


class TestConsumerGroups:
    async def test_unexpected_group_errors_propagate(self, storage):
        storage._redis.xgroup_create = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            await storage._ensure_group("other:events")

    async def test_existing_group_is_accepted(self, storage):
        storage._ready_groups.clear()
        await storage._ensure_group(storage._stream_key)
        assert storage._stream_key in storage._ready_groups
