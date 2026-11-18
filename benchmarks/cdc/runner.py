"""Insert outbox events at a target rate and time how long each takes to reach the broker.

The same load runs against the outbox worker in CDC mode (``PgLogicalSource``)
and in polling mode, on a PostgreSQL with ``wal_level=logical``. Lag is
measured from the producer's COMMIT returning to the broker's publish call, so
it slightly underestimates the true commit-to-publish time.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from benchmarks.tenancy.stats import percentile
from sagaz.core.outbox.brokers.memory import InMemoryBroker
from sagaz.core.outbox.types import OutboxConfig
from sagaz.core.outbox.worker import OutboxWorker

INSERT = """
    INSERT INTO saga_outbox (event_id, saga_id, aggregate_id, event_type, payload)
    VALUES ($1, $2, $2, 'bench.created', $3::jsonb)
"""


class RecordingBroker(InMemoryBroker):
    """Counts publications and remembers when each event was published."""

    def __init__(self) -> None:
        super().__init__()
        self.published_at: dict[str, float] = {}

    async def publish_event(self, event: Any, topic: str | None = None) -> None:
        self.published_at[event.event_id] = time.monotonic()


@dataclass(frozen=True)
class Load:
    events: int
    rate: float  # events per second; 0 = as fast as the producer can go
    rows_per_tx: int
    producers: int = 1


@dataclass(frozen=True)
class Result:
    mode: str
    events: int
    target_rate: float
    produced_rate: float
    published: int
    throughput: float  # events/s from the first commit to the last publication
    lag_p50_ms: float
    lag_p95_ms: float
    lag_p99_ms: float
    lag_max_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def _produce_share(conn: Any, load: Load, share: int, started: float) -> dict[str, float]:
    """One producer's share of the load, paced to its fraction of the target rate."""
    committed: dict[str, float] = {}
    payload = json.dumps({"order": 1, "items": [{"sku": "A", "qty": 2}]})
    rate = load.rate / load.producers if load.rate else 0.0
    for first in range(0, share, load.rows_per_tx):
        ids = [str(uuid.uuid4()) for _ in range(min(load.rows_per_tx, share - first))]
        if rate and (delay := started + first / rate - time.monotonic()) > 0:
            await asyncio.sleep(delay)
        async with conn.transaction():
            await conn.executemany(INSERT, [(i, f"bench-{i[:8]}", payload) for i in ids])
        committed.update(dict.fromkeys(ids, time.monotonic()))
    return committed


async def _produce(conns: list[Any], load: Load) -> tuple[dict[str, float], float, float]:
    shares = [load.events // len(conns)] * len(conns)
    shares[0] += load.events - sum(shares)
    started = time.monotonic()
    parts = await asyncio.gather(
        *(_produce_share(c, load, n, started) for c, n in zip(conns, shares, strict=True))
    )
    committed = {k: v for part in parts for k, v in part.items()}
    return committed, started, time.monotonic()


def _source(dsn: str, suffix: str, max_batch_delay: float) -> Any:
    from sagaz.integrations.cdc import PgLogicalSource

    return PgLogicalSource(
        dsn,
        slot=f"bench_{suffix}",
        publication=f"bench_{suffix}",
        max_batch_delay=max_batch_delay,
    )


async def run(
    dsn: str, mode: str, load: Load, poll_interval: float = 1.0, max_batch_delay: float = 0.005
) -> Result:
    """One run of ``load`` with the worker in ``mode`` ('cdc' or 'polling')."""
    import asyncpg

    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

    storage = PostgreSQLOutboxStorage(dsn, pool_min_size=2, pool_max_size=20)
    await storage.initialize()
    conns = [await asyncpg.connect(dsn) for _ in range(load.producers)]
    await conns[0].execute("TRUNCATE saga_outbox")
    broker = RecordingBroker()
    await broker.connect()
    source = _source(dsn, uuid.uuid4().hex[:8], max_batch_delay) if mode == "cdc" else None
    config = OutboxConfig(
        batch_size=500, poll_interval_seconds=poll_interval, cdc_sweep_interval_seconds=None
    )
    worker = OutboxWorker(storage, broker, config, cdc_source=source)
    task = asyncio.create_task(worker.start())
    await asyncio.sleep(1.0)  # slot created and streaming / first poll done
    try:
        committed, started, produced_end = await _produce(conns, load)
        deadline = time.monotonic() + 120
        while len(broker.published_at) < load.events and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
    finally:
        await worker.stop()
        await asyncio.wait_for(task, 30)
        if source is not None:
            await source.drop_slot(drop_publication=True)
        for conn in conns:
            await conn.close()
        await storage.close()
    return _result(mode, load, committed, broker.published_at, started, produced_end)


def _result(
    mode: str,
    load: Load,
    committed: dict[str, float],
    published: dict[str, float],
    started: float,
    produced_end: float,
) -> Result:
    lags = sorted(published[i] - committed[i] for i in committed if i in published)

    def pct(q: float) -> float:
        return round(percentile(lags, q) * 1000, 2) if lags else 0.0

    last = max(published.values(), default=started)
    duration = max(last - started, 1e-9)
    return Result(
        mode=mode,
        events=load.events,
        target_rate=load.rate,
        produced_rate=round(load.events / max(produced_end - started, 1e-9), 1),
        published=len(lags),
        throughput=round(len(lags) / duration, 1),
        lag_p50_ms=pct(50),
        lag_p95_ms=pct(95),
        lag_p99_ms=pct(99),
        lag_max_ms=round((lags[-1] if lags else 0.0) * 1000, 2),
    )
