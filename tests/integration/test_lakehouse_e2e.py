"""The v2.2.0 release gates, end to end on a real lakehouse (ADR-013, #484).

Runs against ``sagaz/deployment/resources/local/lakehouse/docker-compose.yaml``
with the tiering job submitted, when ``SAGAZ_TEST_LAKEHOUSE=1``. The scenario
runs once per module and the gates check it:

1. **No loss:** the exporter runs while sagas execute, the Fluss tablet server
   is stopped and restarted mid-load, and every event of the log reaches
   Iceberg (counted per tenant and transaction).
2. **Latency:** p99 from an event's ``occurred_at`` to Fluss acknowledging it
   is below 1 s, measured without an outage.
3. **Tiering:** Iceberg holds exactly the log's events, each once.
4. **Parity:** the flow summary over Iceberg equals the embedded pipeline's
   over the log.

Needs pyfluss (Python 3.12 or earlier), pyiceberg and the analytics extra.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sagaz.core.exceptions import SagaFailedError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("SAGAZ_TEST_LAKEHOUSE") != "1",
        reason="needs the lakehouse compose (SAGAZ_TEST_LAKEHOUSE=1)",
    ),
]

pytest.importorskip("fluss")
pytest.importorskip("pyiceberg")
pytest.importorskip("duckdb")
pytest.importorskip("sqldim")

from sagaz.core.storage.saga_log import SagaLogExporter, SagaLogReader  # noqa: E402
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore  # noqa: E402
from sagaz.core.tenant import system_scope, tenant_scope  # noqa: E402
from sagaz.integrations.fluss import FlussSink  # noqa: E402
from sagaz.integrations.iceberg_metrics import IcebergLogSource, flow_summary  # noqa: E402
from tests.unit.analytics.test_unified_analytics import reports  # noqa: E402
from tests.unit.core.test_unified_orchestration import order_saga  # noqa: E402
from tests.unit.test_choreography_unified import shop  # noqa: E402

COMPOSE = Path(__file__).parents[2] / "sagaz/deployment/resources/local/lakehouse"
BOOTSTRAP = os.environ.get("SAGAZ_FLUSS_BOOTSTRAP", "localhost:9124")
CATALOG = {
    "type": "sql",
    "uri": os.environ.get(
        "SAGAZ_ICEBERG_URI", "postgresql+psycopg2://iceberg:iceberg@localhost:15433/iceberg"
    ),
    "s3.endpoint": os.environ.get("SAGAZ_S3_ENDPOINT", "http://localhost:9000"),
    "s3.access-key-id": "rustfsadmin",
    "s3.secret-access-key": "rustfsadmin",
    "s3.region": "us-east-1",
    "s3.force-virtual-addressing": "false",
}
SAGAS = int(os.environ.get("SAGAZ_LAKEHOUSE_SAGAS", "1000"))
# cursor: a SQLite log read with SagaLogReader; cdc: a PostgreSQL log (the compose's
# catalog server, wal_level=logical) read with SagaLogCDCReader (#495).
READER = os.environ.get("SAGAZ_LAKEHOUSE_READER", "cursor")
PG_ADMIN = os.environ.get(
    "SAGAZ_LAKEHOUSE_PG", "postgresql://iceberg:iceberg@localhost:15433/iceberg"
)
RATE = float(os.environ.get("SAGAZ_LAKEHOUSE_RATE", "20"))  # sagas per second, latency phase
TABLE = f"sagaz.saga_log_e2e_{int(time.time())}"  # a fresh table per run


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=COMPOSE, check=True, capture_output=True)


class TimingSink(FlussSink):
    """Records, per event, the seconds from ``occurred_at`` to Fluss's acknowledgement."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.latencies: list[float] = []
        self.measure = True
        self.exported_ids: set[str] = set()

    async def write(self, events) -> None:
        await super().write(events)
        self.exported_ids.update(e.event.event_id for e in events)
        if self.measure:
            now = datetime.now(UTC)
            self.latencies += [(now - e.event.occurred_at).total_seconds() for e in events]


async def run_sagas(log, count: int, offset: int = 0, rate: float | None = None) -> None:
    """Orchestrated sagas (completed, rolled back, failed compensating) in two tenants,
    at most *rate* per second."""
    for i in range(offset, offset + count):
        if rate:
            await asyncio.sleep(1 / rate)
        kind = i % 4
        saga = order_saga(log, fail_charge=kind >= 2, fail_release=kind == 3)
        with tenant_scope("acme" if i % 2 else "globex"):
            try:
                await saga.run({"order_id": f"o-{i}"}, saga_id=f"orch-{i}")
            except SagaFailedError:  # a failed run raises it since #536
                pass


async def run_choreography(log, count: int) -> None:
    service, orders, _ = shop(log)
    async with service:
        for i in range(count):
            await orders.begin(
                "order.created", {"order_id": f"c-{i}", "amount": 500 if i % 3 else 40}
            )
        await service.settle()


async def logged_events(log) -> list:
    with system_scope():
        logged, position = [], None
        while batch := await log.read_committed(position, 1000):
            logged += batch.events
            position = batch.position
    return logged


async def wait_until_exported(
    log, sink: TimingSink, exporter: SagaLogExporter, timeout: float = 120
) -> None:
    """Until every committed event of the log reached the sink (any reader)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ids = {e.event.event_id for e in await logged_events(log)}
        if ids <= sink.exported_ids:
            return
        await asyncio.sleep(0.5)
    pytest.fail(f"exporter did not catch up: {exporter.metrics()}")


async def open_log(path: str):
    """The log, and the reader, of this run's mode."""
    if READER == "cursor":
        log = SQLiteSagaLogStore(path)
        return log, SagaLogReader(log, "e2e"), None
    from urllib.parse import urlsplit, urlunsplit

    import asyncpg

    from sagaz.core.storage.saga_log.postgresql import PostgreSQLSagaLogStore
    from sagaz.integrations.cdc.saga_log import SagaLogCDCReader

    name = f"sagaz_e2e_{int(time.time())}"
    admin = await asyncpg.connect(PG_ADMIN)
    try:
        await admin.execute(f"CREATE DATABASE {name}")
    finally:
        await admin.close()
    dsn = urlunsplit(urlsplit(PG_ADMIN)._replace(path=f"/{name}"))
    log = PostgreSQLSagaLogStore(dsn)
    reader = SagaLogCDCReader(log, dsn, name=name, idle_timeout=0.2)
    await reader.read()  # create the slot first: earlier commits are not streamed
    return log, reader, name


async def drop_database(name: str | None) -> None:
    if name is None:
        return
    import asyncpg

    admin = await asyncpg.connect(PG_ADMIN)
    try:
        # A closed reader's walsender releases its slot shortly after it disconnects.
        for _ in range(60):
            active = await admin.fetchval(
                "SELECT count(*) FROM pg_replication_slots WHERE database = $1 AND active", name
            )
            if not active:
                break
            await asyncio.sleep(0.5)
        await admin.execute(
            "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots"
            " WHERE database = $1",
            name,
        )
        await admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
    finally:
        await admin.close()


def wait_for_tiering(expected: int, timeout: float = 180) -> list[dict]:
    source = IcebergLogSource(dict(CATALOG), TABLE, catalog_name="iceberg")
    deadline = time.monotonic() + timeout
    rows: list[dict] = []
    reads = failed_reads = 0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        reads += 1
        try:
            rows = source.read().to_pylist()
            last_error = None
        except Exception as exc:  # the table appears with the first tiering round
            rows, last_error = [], exc
            failed_reads += 1
        if len(rows) >= expected:
            return rows
        time.sleep(5)
    # A read that keeps failing looks like an empty table: say which it was.
    detail = (
        f"; {failed_reads} of {reads} reads failed, the last with {last_error!r}"
        if failed_reads
        else f"; all {reads} reads succeeded"
    )
    pytest.fail(f"Iceberg holds {len(rows)} of {expected} events after {timeout}s{detail}")


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("lakehouse") / "log.db")

    async def run() -> dict:
        log, reader, database = await open_log(path)
        try:
            return await scenario_on(log, reader)
        finally:
            await log.close()
            await drop_database(database)

    async def scenario_on(log, reader) -> dict:
        sink = TimingSink(BOOTSTRAP, TABLE, freshness="10s", timeout=5)
        exporter = SagaLogExporter(reader, sink, poll_interval=0.05, max_backoff=2)
        try:
            return await steps(log, sink, exporter)
        finally:
            await exporter.close()  # also stops a CDC reader, releasing its slot

    async def steps(log, sink: TimingSink, exporter: SagaLogExporter) -> dict:
        await exporter.start()
        # Warm up: the first write creates the table and the day's partition.
        sink.measure = False
        await run_sagas(log, 1, offset=SAGAS)
        await wait_until_exported(log, sink, exporter)
        # Latency at a steady rate, without an outage.
        sink.measure = True
        await run_sagas(log, SAGAS // 2, rate=RATE)
        await wait_until_exported(log, sink, exporter)
        latencies = list(sink.latencies)
        # No loss: Fluss's tablet server goes away mid-load.
        sink.measure = False
        await run_sagas(log, SAGAS // 4, offset=SAGAS // 2)
        compose("stop", "tablet-server")
        await run_sagas(log, SAGAS // 4, offset=SAGAS * 3 // 4)
        await run_choreography(log, 30)
        await asyncio.sleep(5)
        compose("start", "tablet-server")
        await wait_until_exported(log, sink, exporter, timeout=300)
        errors = exporter.errors
        await exporter.stop()
        logged = await logged_events(log)
        (embedded,) = (await reports(log, "FLOW_SUMMARY")).values()
        return {
            "latencies": latencies,
            "errors": errors,
            "logged": logged,
            "embedded": embedded,
        }

    result = asyncio.run(run())
    result["iceberg"] = wait_for_tiering(len(result["logged"]))
    return result


def test_no_event_is_lost_across_an_outage(scenario):
    assert scenario["errors"] > 0, "the outage should have made the exporter retry"
    logged = Counter((e.event.tenant_id, e.event.transaction_id) for e in scenario["logged"])
    tiered = Counter((r["tenant_id"], r["transaction_id"]) for r in scenario["iceberg"])
    assert tiered == logged


def test_p99_latency_below_one_second(scenario):
    latencies = sorted(scenario["latencies"])
    assert len(latencies) >= SAGAS // 2
    p99 = latencies[int(len(latencies) * 0.99) - 1]
    print(f"\nlatency p50={latencies[len(latencies) // 2]:.3f}s p99={p99:.3f}s")
    assert p99 < 1.0


def test_iceberg_holds_each_event_once(scenario):
    keys = [(r["tenant_id"], r["transaction_id"], r["sequence"]) for r in scenario["iceberg"]]
    assert len(keys) == len(set(keys)) == len(scenario["logged"])


def test_the_flow_summary_matches_the_embedded_pipeline(scenario):
    import pyarrow as pa

    from_iceberg = flow_summary(pa.Table.from_pylist(scenario["iceberg"]))
    embedded = scenario["embedded"]

    def counts(rows):
        return [{k: v for k, v in r.items() if "duration" not in k} for r in rows]

    assert counts(from_iceberg) == counts(embedded)
    for row, reference in zip(from_iceberg, embedded, strict=True):
        for column in ("p50_duration_ms", "p95_duration_ms"):
            assert row[column] == pytest.approx(reference[column], abs=1.0)
