"""PgLogicalSource against a real PostgreSQL with ``wal_level=logical`` (ADR-011).

The shared ``postgres_container`` fixture does not enable logical decoding, so
this module starts its own container. Set ``SAGAZ_CDC_PG_DSN`` to a superuser
DSN of an existing server with ``wal_level=logical`` to use it instead (the
tests create and drop their own slots, publications and role).
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from sagaz.core.outbox.types import OutboxEvent
from sagaz.core.tenant import system_scope, tenant_scope

pytestmark = [pytest.mark.integration, pytest.mark.timeout(180)]

asyncpg = pytest.importorskip("asyncpg")
pytest.importorskip("psycopg2")

from sagaz.integrations.cdc.pg_logical import PgLogicalSource  # noqa: E402

READER_ROLE = "sagaz_cdc_reader"
READER_PASSWORD = "cdc-reader-pw"


@pytest.fixture(scope="module")
def admin_dsn(logical_postgres_dsn):
    return logical_postgres_dsn


def _with_credentials(dsn: str, user: str, password: str) -> str:
    parts = urlsplit(dsn)
    netloc = f"{user}:{password}@{parts.hostname}:{parts.port or 5432}"
    return urlunsplit(parts._replace(netloc=netloc))


async def _reset(admin_dsn: str) -> None:
    """Drop slots, publications and outbox rows left by a previous test."""
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(
            "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots "
            "WHERE slot_name LIKE 'it_%' AND NOT active"
        )
        for (name,) in await conn.fetch(
            "SELECT pubname FROM pg_publication WHERE pubname LIKE 'it_%'"
        ):
            await conn.execute(f"DROP PUBLICATION {name}")
        await conn.execute("DROP TABLE IF EXISTS cdc_other")
    finally:
        await conn.close()


@pytest.fixture
async def outbox(admin_dsn):
    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

    await _reset(admin_dsn)
    storage = PostgreSQLOutboxStorage(admin_dsn, pool_min_size=1, pool_max_size=2)
    await storage.initialize()
    yield storage
    await storage.close()
    await _reset(admin_dsn)


@pytest.fixture
def slot():
    return f"it_{uuid4().hex[:12]}"


def _source(dsn: str, slot: str, **kwargs) -> PgLogicalSource:
    options = {"publication": f"{slot}_pub", "max_batch_delay": 0.01, "poll_interval": 0.02}
    options.update(kwargs)
    return PgLogicalSource(dsn, slot=slot, **options)


def _event(saga_id: str, **kwargs) -> OutboxEvent:
    return OutboxEvent(
        saga_id=saga_id, event_type="OrderCreated", payload={"saga": saga_id}, **kwargs
    )


async def _collect(source: PgLogicalSource, count: int, timeout: float = 10.0) -> list:
    changes: list = []
    iterator = source.changes()
    async with asyncio.timeout(timeout):
        while len(changes) < count:
            changes += await anext(iterator)
    return changes


async def _nothing_arrives(source: PgLogicalSource, wait: float = 0.5) -> bool:
    with suppress(TimeoutError):
        await asyncio.wait_for(anext(source.changes()), wait)
        return False
    return True


@pytest.mark.asyncio
class TestPgLogicalSource:
    async def test_inserts_of_two_tenants_arrive_with_their_fields(self, admin_dsn, outbox, slot):
        source = _source(admin_dsn, slot)
        await source.start()
        try:
            acme = _event("saga-acme", routing_key="orders", headers={"h": "1"})
            umbrella = _event("saga-umbrella", partition_key="p1")
            with tenant_scope("acme"):
                await outbox.insert(acme)
            with tenant_scope("umbrella"):
                await outbox.insert(umbrella)
            changes = await _collect(source, 2)
        finally:
            await source.stop()
            await source.drop_slot(drop_publication=True)

        by_saga = {c.event.saga_id: c for c in changes}
        assert set(by_saga) == {"saga-acme", "saga-umbrella"}
        got = by_saga["saga-acme"].event
        assert got.event_id == acme.event_id
        assert got.tenant_id == "acme"
        assert got.event_type == "OrderCreated"
        assert got.payload == {"saga": "saga-acme"}
        assert got.headers == {"h": "1"}
        assert got.routing_key == "orders"
        assert got.created_at == acme.created_at
        assert by_saga["saga-umbrella"].event.tenant_id == "umbrella"
        assert by_saga["saga-umbrella"].event.partition_key == "p1"
        assert all(c.committed_at is not None for c in changes)
        assert changes[0].position < changes[1].position

    async def test_change_visible_within_200ms_of_commit(self, admin_dsn, outbox, slot):
        source = _source(admin_dsn, slot)
        await source.start()
        try:
            await asyncio.sleep(0.2)  # let the stream settle
            latencies = []
            for i in range(5):
                await outbox.insert(_event(f"lat-{i}"))
                committed = time.monotonic()
                await _collect(source, 1)
                latencies.append(time.monotonic() - committed)
        finally:
            await source.stop()
            await source.drop_slot(drop_publication=True)
        assert max(latencies) < 0.2, latencies

    async def test_restart_redelivers_until_acknowledged(self, admin_dsn, outbox, slot):
        first = _source(admin_dsn, slot)
        await first.start()
        await outbox.insert(_event("redeliver-me"))
        changes = await _collect(first, 1)
        await first.stop()  # no ack

        second = _source(admin_dsn, slot)
        await second.start()
        again = await _collect(second, 1)
        assert [c.event.event_id for c in again] == [changes[0].event.event_id]
        await second.ack(again[-1].position)
        await second.stop()  # confirms the ack

        third = _source(admin_dsn, slot)
        await third.start()
        try:
            assert await _nothing_arrives(third)
            await outbox.insert(_event("next"))
            assert [c.event.saga_id for c in await _collect(third, 1)] == ["next"]
        finally:
            await third.stop()
            await third.drop_slot(drop_publication=True)

    async def test_other_tables_are_ignored(self, admin_dsn, outbox, slot):
        conn = await asyncpg.connect(admin_dsn)
        await conn.execute("CREATE TABLE cdc_other (id int primary key, note text)")
        source = _source(admin_dsn, slot)
        await source.start()
        try:
            await conn.execute("INSERT INTO cdc_other VALUES (1, 'not an event')")
            # A publication covering every table still yields only outbox rows.
            await conn.execute(f"ALTER PUBLICATION {slot}_pub ADD TABLE cdc_other")
            async with conn.transaction():
                await conn.execute("INSERT INTO cdc_other VALUES (2, 'same transaction')")
                with system_scope():
                    await outbox.insert(_event("only-me"), connection=conn)
            await conn.execute("INSERT INTO cdc_other VALUES (3, 'after')")
            changes = await _collect(source, 1)
            assert [c.event.saga_id for c in changes] == ["only-me"]
            assert await _nothing_arrives(source)
        finally:
            await source.stop()
            await source.drop_slot(drop_publication=True)
            await conn.close()

    async def test_replication_role_without_bypassrls_sees_every_tenant(
        self, admin_dsn, outbox, slot
    ):
        """Logical decoding is not filtered by row-level security."""
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(f"DROP ROLE IF EXISTS {READER_ROLE}")
            await conn.execute(
                f"CREATE ROLE {READER_ROLE} LOGIN REPLICATION NOBYPASSRLS "
                f"PASSWORD '{READER_PASSWORD}'"
            )
            await conn.execute(f"GRANT SELECT ON saga_outbox TO {READER_ROLE}")
        finally:
            await conn.close()
        # An administrator creates the publication and slot; the reader only streams.
        admin = _source(admin_dsn, slot)
        await admin.start()
        await admin.stop()
        reader = _source(
            _with_credentials(admin_dsn, READER_ROLE, READER_PASSWORD), slot, create=False
        )
        await reader.start()
        try:
            for tenant in ("t1", "t2", "t3"):
                with tenant_scope(tenant):
                    await outbox.insert(_event(f"saga-{tenant}"))
            changes = await _collect(reader, 3)
        finally:
            await reader.stop()
            await admin.drop_slot(drop_publication=True)
            conn = await asyncpg.connect(admin_dsn)
            await conn.execute(f"DROP OWNED BY {READER_ROLE}; DROP ROLE {READER_ROLE}")
            await conn.close()
        assert sorted(c.event.tenant_id for c in changes) == ["t1", "t2", "t3"]
