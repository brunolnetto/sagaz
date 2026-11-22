"""Saga → outbox → logical replication → CDC-mode worker → broker (ADR-011, #50).

The issue's acceptance test: a saga writes its state and outbox events to
PostgreSQL, and a worker in CDC mode publishes each event within 200 ms of the
commit, without polling. Each tenant's events come out with their tenant.

Uses ``logical_postgres_dsn`` (a container with ``wal_level=logical``, or the
server in ``SAGAZ_CDC_PG_DSN``).
"""

from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import pytest

from sagaz import Saga, action
from sagaz.core.config import SagaConfig
from sagaz.core.outbox.brokers.memory import InMemoryBroker
from sagaz.core.outbox.types import OutboxConfig
from sagaz.core.outbox.worker import OutboxWorker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

asyncpg = pytest.importorskip("asyncpg")
pytest.importorskip("psycopg2")

from sagaz.integrations.cdc import PgLogicalSource  # noqa: E402

DEADLINE = 0.2  # seconds from commit to publication


class OrderSaga(Saga):
    saga_name = "order"

    @action("reserve")
    async def reserve(self, ctx):
        return {"reserved": True}

    @action("charge", depends_on=["reserve"])
    async def charge(self, ctx):
        return {"charged": ctx["amount"]}


class TimingBroker(InMemoryBroker):
    """Records when each event was published."""

    def __init__(self) -> None:
        super().__init__()
        self.published_at: dict[str, float] = {}

    async def publish_event(self, event):
        await super().publish_event(event)
        self.published_at[event.event_id] = time.monotonic()


@pytest.fixture
async def stack(logical_postgres_dsn):
    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    suffix = uuid4().hex[:8]
    outbox = PostgreSQLOutboxStorage(logical_postgres_dsn, pool_min_size=1, pool_max_size=4)
    await outbox.initialize()
    saga_storage = PostgreSQLSagaStorage(logical_postgres_dsn, pool_min_size=1, pool_max_size=4)
    await saga_storage.__aenter__()
    source = PgLogicalSource(
        logical_postgres_dsn, slot=f"e2e_{suffix}", publication=f"e2e_{suffix}"
    )
    broker = TimingBroker()
    await broker.connect()
    config = OutboxConfig(cdc_sweep_interval_seconds=None)
    worker = OutboxWorker(outbox, broker, config, cdc_source=source)
    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.5)  # slot created and streaming
    try:
        yield saga_storage, outbox, broker
    finally:
        await worker.stop()
        await asyncio.wait_for(task, 10)
        await source.drop_slot(drop_publication=True)
        await outbox.close()
        await saga_storage.__aexit__(None, None, None)


async def test_saga_events_are_published_within_200ms_of_commit(stack):
    saga_storage, outbox, broker = stack
    config = SagaConfig(
        storage=saga_storage, outbox_storage=outbox, broker=broker, metrics=False, logging=False
    )

    committed = {}
    for tenant in ("acme", "globex"):
        before = set(broker.published_at)
        await OrderSaga(config=config).run(
            {"amount": 10}, saga_id=f"o-{uuid4().hex[:6]}", tenant=tenant
        )
        # The listener inserted the events while the saga ran; they are committed now.
        committed[tenant] = (time.monotonic(), before)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        published = [json.loads(m["message"]) for ms in broker._messages.values() for m in ms]
        if {e["tenant_id"] for e in published} >= {"acme", "globex"}:
            break
        await asyncio.sleep(0.01)

    published = [json.loads(m["message"]) for ms in broker._messages.values() for m in ms]
    assert {e["tenant_id"] for e in published} == {"acme", "globex"}
    assert {e["event_type"] for e in published} >= {"order.completed"}

    for tenant, (saga_done, before) in committed.items():
        new = [
            eid
            for eid in broker.published_at
            if eid not in before
            and any(e["event_id"] == eid and e["tenant_id"] == tenant for e in published)
        ]
        assert new, f"no event published for {tenant}"
        latest = max(broker.published_at[eid] for eid in new)
        assert latest - saga_done < DEADLINE, (
            f"{tenant}: published {latest - saga_done:.3f}s after commit"
        )
