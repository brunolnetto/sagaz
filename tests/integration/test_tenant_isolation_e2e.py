"""End-to-end tenant isolation on a real PostgreSQL (ADR-020, #54).

Two tenants run the same saga, with the same saga id, at the same time: one
completes and the other fails and compensates. The application connects as an
ordinary role (no superuser, no BYPASSRLS), so row-level security applies.

Checked afterwards:
- each tenant sees only its own saga state and outbox events;
- raw SQL in a tenant's session sees only that tenant's rows;
- code with no tenant (the default tenant) sees neither;
- the outbox worker publishes every tenant's events, each carrying its tenant.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.outbox.brokers.memory import InMemoryBroker
from sagaz.core.outbox.types import OutboxConfig
from sagaz.core.outbox.worker import OutboxWorker
from sagaz.core.tenant import system_scope, tenant_scope

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

asyncpg = pytest.importorskip("asyncpg")

SAGA_ID = "order-1"
TENANTS = ("acme", "globex")


class OrderSaga(Saga):
    saga_name = "order"

    @action("reserve")
    async def reserve(self, ctx):
        await asyncio.sleep(0.05)  # let the two tenants' sagas interleave
        return {"reserved_for": ctx["tenant_id"]}

    @compensate("reserve")
    async def release(self, ctx):
        return None

    @action("charge", depends_on=["reserve"])
    async def charge(self, ctx):
        if ctx.get("declined"):
            msg = "card declined"
            raise RuntimeError(msg)
        return {"charged": ctx["amount"]}


@pytest.fixture
async def stores(app_role_url):
    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    outbox = PostgreSQLOutboxStorage(app_role_url, pool_min_size=1, pool_max_size=4)
    await outbox.initialize()
    try:
        async with PostgreSQLSagaStorage(
            app_role_url, pool_min_size=1, pool_max_size=4
        ) as saga_storage:
            yield saga_storage, outbox
    finally:
        await outbox.close()


async def _run_both(saga_storage, outbox, broker):
    config = SagaConfig(
        storage=saga_storage,
        outbox_storage=outbox,
        broker=broker,
        metrics=False,
        logging=False,
    )
    runs = [
        OrderSaga(config=config).run({"amount": 10}, saga_id=SAGA_ID, tenant_context="acme"),
        OrderSaga(config=config).run(
            {"amount": 99, "declined": True}, saga_id=SAGA_ID, tenant_context="globex"
        ),
    ]
    return await asyncio.gather(*runs, return_exceptions=True)


async def _raw_rows(url, tenant, sql):
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", tenant)
        return [tuple(r) for r in await conn.fetch(sql)]
    finally:
        await conn.close()


async def test_two_tenants_running_the_same_saga_stay_isolated(stores, app_role_url):
    saga_storage, outbox = stores
    broker = InMemoryBroker()
    await broker.connect()

    acme_result, globex_result = await _run_both(saga_storage, outbox, broker)

    # The run itself: acme completed, globex failed and compensated.
    assert acme_result["tenant_id"] == "acme"
    assert isinstance(globex_result, RuntimeError)

    # Saga state: same id, two independent sagas.
    with tenant_scope("acme"):
        acme = await saga_storage.load_saga_state(SAGA_ID)
    with tenant_scope("globex"):
        globex = await saga_storage.load_saga_state(SAGA_ID)
    assert (acme["status"], acme["context"]["amount"]) == ("completed", 10)
    assert (globex["status"], globex["context"]["amount"]) == ("rolled_back", 99)
    assert acme["context"]["tenant_id"] == "acme"
    assert globex["context"]["tenant_id"] == "globex"
    assert await saga_storage.load_saga_state(SAGA_ID) is None  # default tenant

    # Outbox events: each tenant sees only its own.
    events = {}
    for tenant in TENANTS:
        with tenant_scope(tenant):
            events[tenant] = await outbox.get_events_by_saga(SAGA_ID)
        assert events[tenant], f"no outbox events recorded for {tenant}"
        assert {e.tenant_id for e in events[tenant]} == {tenant}
    assert not {e.event_id for e in events["acme"]} & {e.event_id for e in events["globex"]}
    assert await outbox.get_events_by_saga(SAGA_ID) == []

    # The database enforces it: raw SQL in a tenant session (row-level security).
    for tenant in TENANTS:
        for table in ("sagas", "saga_steps", "saga_outbox"):
            rows = await _raw_rows(app_role_url, tenant, f"SELECT DISTINCT tenant_id FROM {table}")
            assert rows in ([(tenant,)], []), (tenant, table, rows)
        assert await _raw_rows(app_role_url, tenant, "SELECT saga_id FROM sagas") == [(SAGA_ID,)]
    assert await _raw_rows(app_role_url, "", "SELECT saga_id FROM sagas") == []

    # The worker publishes every tenant's events, each with its tenant.
    worker = OutboxWorker(outbox, broker, OutboxConfig(batch_size=100))
    published = 0
    while processed := await worker.process_batch():
        published += processed
    assert published == len(events["acme"]) + len(events["globex"])

    seen: dict[str, set[str]] = {tenant: set() for tenant in TENANTS}
    for messages in broker._messages.values():
        for message in messages:
            tenant = message["headers"]["tenant_id"]
            assert json.loads(message["message"])["tenant_id"] == tenant
            seen[tenant].add(message["headers"].get("event_id") or message["key"])
    assert all(seen.values()), seen

    with system_scope():
        pending = [e for e in await outbox.get_events_by_saga(SAGA_ID) if e.status == "pending"]
    assert pending == []
