"""Debezium CDC of the outbox end to end (ADR-011, #50).

PostgreSQL (``wal_level=logical``), Kafka (KRaft) and Debezium Connect run in
containers on a shared network. The shipped connector is registered through
Kafka Connect's REST API, outbox rows are written by
``PostgreSQLOutboxStorage.insert`` in two tenants, and
:class:`DebeziumKafkaSource` must yield them, honour acknowledgements across
reconnects and redeliver what was not acknowledged.

Heavy (three JVM/DB containers): run on its own, without coverage::

    pytest -m integration tests/integration/test_cdc_debezium.py -p no:cacheprovider
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.tenant import tenant_scope
from sagaz.integrations.cdc import CDCChange
from sagaz.integrations.cdc.debezium import DebeziumKafkaSource
from sagaz.integrations.cdc.debezium_connect import (
    connector_status,
    is_running,
    outbox_connector_config,
    register_connector,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

asyncpg = pytest.importorskip("asyncpg")
pytest.importorskip("aiokafka")

POSTGRES_IMAGE = "postgres:16-alpine"
KAFKA_IMAGE = "confluentinc/cp-kafka:7.6.0"
CONNECT_IMAGE = "quay.io/debezium/connect:3.7.1.Final"
TOPIC_PREFIX = "itest"
SLOT = "sagaz_outbox_itest"
STARTUP_TIMEOUT = 180.0
RECEIVE_TIMEOUT = 90.0


@dataclass
class CDCStack:
    postgres_url: str
    bootstrap_servers: str
    connect_url: str


def _wait_for_connect(url: str, timeout: float = STARTUP_TIMEOUT) -> None:
    import httpx

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/connectors", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    msg = f"Kafka Connect did not come up at {url}"
    raise TimeoutError(msg)


@pytest.fixture(scope="module")
def cdc_stack(container_manager) -> Iterator[CDCStack]:
    if container_manager is None:
        pytest.skip("testcontainers not available")
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.network import Network
    from testcontainers.kafka import KafkaContainer
    from testcontainers.postgres import PostgresContainer

    with Network() as network:
        postgres = (
            PostgresContainer(POSTGRES_IMAGE)
            .with_command("postgres -c wal_level=logical")
            .with_network(network)
            .with_network_aliases("postgres")
        )
        kafka = (
            KafkaContainer(KAFKA_IMAGE)
            .with_kraft()
            .with_network(network)
            .with_network_aliases("kafka")
        )
        connect = (
            DockerContainer(CONNECT_IMAGE)
            .with_env("BOOTSTRAP_SERVERS", "kafka:9092")
            .with_env("GROUP_ID", "sagaz-itest-connect")
            .with_env("CONFIG_STORAGE_TOPIC", "itest_connect_configs")
            .with_env("OFFSET_STORAGE_TOPIC", "itest_connect_offsets")
            .with_env("STATUS_STORAGE_TOPIC", "itest_connect_statuses")
            .with_exposed_ports(8083)
            .with_network(network)
        )
        with postgres, kafka, connect:
            connect_url = (
                f"http://{connect.get_container_host_ip()}:{connect.get_exposed_port(8083)}"
            )
            _wait_for_connect(connect_url)
            stack = CDCStack(
                postgres_url=postgres.get_connection_url().replace(
                    "postgresql+psycopg2://", "postgresql://"
                ),
                bootstrap_servers=kafka.get_bootstrap_server(),
                connect_url=connect_url,
            )
            asyncio.run(_prepare(stack, postgres))
            yield stack


async def _prepare(stack: CDCStack, postgres) -> None:
    """Create the outbox schema, register the connector and wait for its slot."""
    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

    storage = PostgreSQLOutboxStorage(stack.postgres_url, pool_min_size=1, pool_max_size=2)
    await storage.initialize()
    await storage.close()

    config = outbox_connector_config(
        {
            "database.hostname": "postgres",
            "database.port": 5432,
            "database.user": postgres.username,
            "database.password": postgres.password,
            "database.dbname": postgres.dbname,
            "topic.prefix": TOPIC_PREFIX,
            "slot.name": SLOT,
            "heartbeat.interval.ms": 1000,
        }
    )
    await register_connector(stack.connect_url, config)

    # snapshot.mode=no_data: only rows committed after the slot exists are captured.
    deadline = time.monotonic() + STARTUP_TIMEOUT
    conn = await asyncpg.connect(stack.postgres_url)
    try:
        while time.monotonic() < deadline:
            status = await connector_status(stack.connect_url)
            active = await conn.fetchval(
                "SELECT active FROM pg_replication_slots WHERE slot_name = $1", SLOT
            )
            if is_running(status) and active:
                return
            await asyncio.sleep(2)
    finally:
        await conn.close()
    msg = f"Debezium connector did not start streaming: {status}"
    raise TimeoutError(msg)


async def _insert(stack: CDCStack, tenant: str, **fields) -> OutboxEvent:
    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

    event = OutboxEvent(
        saga_id=fields.pop("saga_id", f"saga-{uuid4().hex[:8]}"),
        event_type=fields.pop("event_type", "OrderCreated"),
        payload=fields.pop("payload", {"tenant": tenant, "amount": 12.5}),
        aggregate_type="order",
        aggregate_id=f"ORD-{uuid4().hex[:6]}",
        headers={"trace_id": uuid4().hex},
        routing_key="orders",
        partition_key="p-1",
        **fields,
    )
    storage = PostgreSQLOutboxStorage(stack.postgres_url, pool_min_size=1, pool_max_size=2)
    await storage.initialize()
    try:
        with tenant_scope(tenant):
            return await storage.insert(event)
    finally:
        await storage.close()


async def _receive(source: DebeziumKafkaSource, until: set[str], *, ack: bool) -> list[CDCChange]:
    """Changes up to and including the batch holding every id in ``until``."""
    received: list[CDCChange] = []
    stream = source.changes()

    async def run() -> None:
        async for batch in stream:
            received.extend(batch)
            if ack:
                await source.ack(batch[-1].position)
            if until <= {change.event.event_id for change in received}:
                return

    try:
        await asyncio.wait_for(run(), RECEIVE_TIMEOUT)
    finally:
        await stream.aclose()
    return received


def _source(stack: CDCStack, group: str) -> DebeziumKafkaSource:
    return DebeziumKafkaSource(
        stack.bootstrap_servers,
        topic_prefix=TOPIC_PREFIX,
        group_id=group,
        max_batch_size=50,
        max_wait_ms=500,
    )


@pytest.mark.asyncio
async def test_streams_outbox_inserts_of_each_tenant(cdc_stack):
    before = datetime.now(UTC)
    acme = await _insert(cdc_stack, "acme", payload={"order": 1, "items": ["a", "b"]})
    globex = await _insert(cdc_stack, "globex", event_type="PaymentCharged")

    source = _source(cdc_stack, f"itest-{uuid4().hex[:8]}")
    await source.start()
    try:
        received = await _receive(source, {acme.event_id, globex.event_id}, ack=True)
    finally:
        await source.stop()

    by_id = {change.event.event_id: change for change in received}
    got_acme, got_globex = by_id[acme.event_id].event, by_id[globex.event_id].event
    assert got_acme.tenant_id == "acme"
    assert got_globex.tenant_id == "globex"
    assert got_acme.payload == {"order": 1, "items": ["a", "b"]}
    assert got_acme.headers == acme.headers
    assert got_acme.saga_id == acme.saga_id
    assert got_acme.aggregate_id == acme.aggregate_id
    assert got_acme.routing_key == "orders"
    assert got_acme.partition_key == "p-1"
    assert got_acme.status is OutboxStatus.PENDING
    assert got_globex.event_type == "PaymentCharged"
    assert abs(got_acme.created_at - acme.created_at) < timedelta(milliseconds=1)
    committed_at = by_id[acme.event_id].committed_at
    assert committed_at is not None
    assert before - timedelta(seconds=5) <= committed_at <= datetime.now(UTC)
    assert source.stats.failed == 0


@pytest.mark.asyncio
async def test_acknowledged_changes_are_not_redelivered(cdc_stack):
    group = f"itest-{uuid4().hex[:8]}"
    first = await _insert(cdc_stack, "acme")

    source = _source(cdc_stack, group)
    await source.start()
    try:
        await _receive(source, {first.event_id}, ack=True)
    finally:
        await source.stop()

    second = await _insert(cdc_stack, "globex")

    # Reconnect: the group resumes after the acknowledged batch.
    source = _source(cdc_stack, group)
    await source.start()
    try:
        received = await _receive(source, {second.event_id}, ack=False)
    finally:
        await source.stop()
    assert [c.event.event_id for c in received] == [second.event_id]

    # That batch was not acknowledged, so it comes again (at least once).
    source = _source(cdc_stack, group)
    await source.start()
    try:
        received = await _receive(source, {second.event_id}, ack=True)
    finally:
        await source.stop()
    assert [c.event.event_id for c in received] == [second.event_id]
