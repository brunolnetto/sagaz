"""The PostgreSQL saga log (ADR-041, #464): contract, participant isolation, append-only log.

Runs against the PostgreSQL container, or the server in ``SAGAZ_TEST_POSTGRES_URL``,
in a database of its own.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from sagaz.core.storage.saga_log import (
    Activity,
    Coordination,
    LogWrite,
    Participant,
    Transaction,
)
from sagaz.core.storage.saga_log._pg_schema import service_role_grants
from sagaz.core.storage.saga_log.postgresql import PostgreSQLSagaLogStore
from sagaz.core.tenant import system_scope
from tests.unit.core.test_saga_log import (
    TestContract,
    TestGuardsAndOutbox,
    activity,
    event,
    tx,
)
from tests.unit.core.test_saga_log_export import TestExportContract, read_all

asyncpg = pytest.importorskip("asyncpg")

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="postgres")]

# The shared contracts, on PostgreSQL
__all__ = ["TestContract", "TestExportContract", "TestGuardsAndOutbox"]

TABLES = (
    "saga_transaction, saga_activity, saga_log_event, saga_snapshot,"
    " saga_participant, saga_delivery, saga_deadline"
)


@pytest.fixture(scope="module")
def database_url(postgres_container):
    psycopg2 = pytest.importorskip("psycopg2")
    base = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    name = f"sagaz_log_{uuid4().hex[:8]}"

    def admin(sql: str) -> None:
        conn = psycopg2.connect(base)
        conn.autocommit = True
        try:
            conn.cursor().execute(sql)
        finally:
            conn.close()

    admin(f"CREATE DATABASE {name}")
    yield base.rsplit("/", 1)[0] + f"/{name}"
    admin(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture
async def store(database_url):
    log = PostgreSQLSagaLogStore(database_url)
    yield log
    if log._pool is not None:
        async with log._pool.acquire() as conn:
            await conn.execute(f"TRUNCATE {TABLES}, saga_outbox, saga_export_cursor")
    await log.close()


async def test_concurrent_writers_never_share_a_sequence(store, database_url):
    other = PostgreSQLSagaLogStore(database_url)
    try:
        await asyncio.gather(
            *(
                (store if i % 2 else other).write(LogWrite(events=[event(event_type=str(i))]))
                for i in range(40)
            )
        )
    finally:
        await other.close()
    assert [e.sequence for e in await store.events("t-1")] == list(range(1, 41))


async def test_concurrent_startups_create_the_schema_once(database_url):
    stores = [PostgreSQLSagaLogStore(database_url) for _ in range(4)]
    try:
        await asyncio.gather(*(s.participants() for s in stores))
    finally:
        for s in stores:
            await s.close()


@pytest.fixture
async def service_role(store, database_url):
    """A non-superuser role registered as participant 'inventory'."""
    role = f"svc_{uuid4().hex[:8]}"
    await store.participants()  # create the schema
    admin = await asyncpg.connect(database_url)
    try:
        await admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'svc'")
        await admin.execute(service_role_grants(role))
    finally:
        await admin.close()
    await store.register_participant(Participant("inventory", db_role=role))
    rest = database_url.split("://", 1)[1].split("@", 1)[1]
    service = PostgreSQLSagaLogStore(f"postgresql://{role}:svc@{rest}")
    yield service
    await service.close()
    admin = await asyncpg.connect(database_url)
    try:
        await admin.execute(
            f"REVOKE ALL ON {TABLES}, sagaz_schema_version, saga_outbox FROM {role}"
        )
        await admin.execute(f"DROP ROLE {role}")
    finally:
        await admin.close()


async def test_a_service_writes_only_as_its_own_participant(store, service_role):
    await store.write(LogWrite(transaction=tx()))  # the platform role is unrestricted
    choreographed = Transaction(
        "c-1", "order.created", Coordination.CHOREOGRAPHED, initiator="inventory"
    )
    own = replace(event("c-1", "inventory.reserved"), source="inventory")
    await service_role.write(
        LogWrite(
            transaction=choreographed,
            events=[own],
            activities=[activity("c-1")],  # participant 'inventory'
        )
    )
    assert await service_role.claim_delivery("inventory", "e-1")

    forged = [
        LogWrite(events=[event(event_type="payment.charged")]),  # source 'orders'
        LogWrite(activities=[Activity("t-1", "a-2", "payments", "charge")]),
        LogWrite(transaction=tx("t-2")),  # initiator 'orders'
    ]
    for batch in forged:
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await service_role.write(batch)
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await service_role.claim_delivery("payments", "e-1")
    assert [e.source for e in await store.events("c-1")] == ["inventory"]


async def test_the_log_is_append_only_for_services(store, service_role):
    await store.write(LogWrite(transaction=tx(), events=[event()]))
    pool = await service_role._get_pool()
    async with pool.acquire() as conn:
        for sql in (
            "UPDATE saga_log_event SET event_type = 'forged'",
            "DELETE FROM saga_log_event",
        ):
            with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
                await conn.execute(sql)
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("INSERT INTO saga_participant (name) VALUES ('rogue')")
    assert [e.event_type for e in await store.events("t-1")] == ["SagaStarted"]


def test_role_names_are_validated():
    with pytest.raises(ValueError, match="Invalid role"):
        service_role_grants("x; DROP TABLE saga_log_event")


async def test_unify_migrates_a_postgresql_database(store, database_url):
    """The old PostgreSQL layout, filled by real sagaz code, into the saga log."""
    from click.testing import CliRunner

    from sagaz.choreography.state.postgresql import PostgreSQLParticipantState
    from sagaz.cli.app import cli
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage
    from sagaz.core.storage.event_store.postgresql import PostgreSQLEventStore
    from sagaz.core.tenant import system_scope
    from tests.unit.core.test_saga_log_migration import fill_old_layout

    state = PostgreSQLParticipantState(database_url)
    async with PostgreSQLSagaStorage(database_url) as old, PostgreSQLEventStore(database_url) as es:
        await fill_old_layout(old, es, state)
    await state.close()

    result = await asyncio.to_thread(
        CliRunner().invoke, cli, ["migrate", "unify", "--source", database_url]
    )
    assert result.exit_code == 0, result.output
    assert "orchestrated transactions: 2" in result.output
    assert "choreographed transactions: 3" in result.output
    with system_scope():
        transactions = {t.transaction_id: t for t in await store.list_transactions()}
        assert transactions["orch-bad"].tenant_id == "acme"
        assert transactions["c-bad"].status == "compensated"
        assert await store.events("orch-ok")
        before = {tid: len(await store.events(tid)) for tid in transactions}

    again = await asyncio.to_thread(
        CliRunner().invoke, cli, ["migrate", "unify", "--source", database_url]
    )
    assert again.exit_code == 0, again.output
    with system_scope():
        assert {tid: len(await store.events(tid)) for tid in transactions} == before


async def test_a_new_process_does_not_block_running_writers(store, database_url):
    """Starting a store on an up-to-date schema runs no DDL (no exclusive locks)."""
    await store.write(LogWrite(transaction=tx()))
    pool = await store._get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("LOCK TABLE saga_log_event IN ROW EXCLUSIVE MODE")  # a writer
        newcomer = PostgreSQLSagaLogStore(database_url)
        try:
            await asyncio.wait_for(newcomer.participants(), timeout=5)
        finally:
            await newcomer.close()


async def test_a_late_commit_is_not_skipped(store, database_url):
    """A transaction that started first but commits last is exported, after it commits."""
    await store.write(LogWrite(transaction=tx("t-1"), events=[event("t-1")]))
    long = await asyncpg.connect(database_url)
    try:
        transaction = long.transaction()
        await transaction.start()
        await long.execute(
            "INSERT INTO saga_log_event (tenant_id, transaction_id, sequence, event_id,"
            " event_type, kind, occurred_at) VALUES ('default', 't-long', 1, 'late',"
            " 'SagaStarted', 'lifecycle', now())"
        )
        # A shorter transaction commits while the long one is still open.
        await store.write(LogWrite(events=[event("t-1", "SagaCompleted")]))
        with system_scope():
            seen = await read_all(store)  # stops below the long transaction
        assert [e.event.event_type for e in seen] == ["SagaStarted"]
        await transaction.commit()
    finally:
        await long.close()

    with system_scope():
        rest = await read_all(store)
    assert [e.event.event_id for e in rest][0] == "late"
    assert [e.event.event_type for e in rest] == ["SagaStarted", "SagaCompleted"]


async def test_upgrading_adds_the_export_order(store, database_url):
    """An existing log gets writer_xid on its rows when the schema is re-applied."""
    await store.write(LogWrite(transaction=tx("t-1"), events=[event("t-1")]))
    async with store._pool.acquire() as conn:
        await conn.execute("ALTER TABLE saga_log_event DROP COLUMN writer_xid")
        await conn.execute("DELETE FROM sagaz_schema_version WHERE component = 'saga_log'")
    upgraded = PostgreSQLSagaLogStore(database_url)
    try:
        with system_scope():
            assert [e.event.event_type for e in await read_all(upgraded)] == ["SagaStarted"]
    finally:
        await upgraded.close()


async def test_exporting_to_fluss_resumes_after_an_outage(store):
    """The PostgreSQL log through the exporter, with Fluss failing mid-batch (#481)."""
    pytest.importorskip("pyarrow")
    from sagaz.core.storage.saga_log import SagaLogExporter, SagaLogReader
    from sagaz.integrations.fluss import FlussSink
    from tests.unit.test_fluss_export import FakeFluss, fill

    fake = FakeFluss()
    await fill(store)
    fake.fail_after = 3

    def exporter():
        reader = SagaLogReader(store, "fluss", batch_size=2)
        return SagaLogExporter(reader, FlussSink("fluss:9123", client=fake))

    with pytest.raises(ConnectionError):
        await exporter().export()
    fake.fail_after = None
    assert await exporter().export() == 3
    assert len(fake.rows) == 5
