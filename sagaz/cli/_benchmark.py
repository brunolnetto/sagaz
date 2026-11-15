"""In-process saga throughput and latency benchmark behind ``sagaz benchmark``.

Runs a small three-step saga many times with bounded concurrency against
in-memory storage, or against any backend given by URL, and reports
throughput and latency percentiles. It uses only the installed library, so it
works wherever sagaz is installed.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig


@dataclass(frozen=True)
class Profile:
    """How many sagas to run, and how many at once."""

    name: str
    sagas: int
    concurrency: int


PROFILES: dict[str, Profile] = {
    "quick": Profile("quick", sagas=20, concurrency=4),
    "local": Profile("local", sagas=500, concurrency=20),
    "production": Profile("production", sagas=5_000, concurrency=100),
    "stress": Profile("stress", sagas=20_000, concurrency=500),
}

#: ``--profile full`` runs these in order.
FULL = ("local", "production", "stress")


@dataclass(frozen=True)
class BenchmarkResult:
    profile: str
    storage: str
    sagas: int
    concurrency: int
    failed: int
    duration_s: float
    throughput: float
    p50_ms: float
    p95_ms: float
    p99_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BenchmarkSaga(Saga):
    """Reserve, charge and notify: two dependent steps, one compensable."""

    saga_name = "sagaz-benchmark"

    @action("reserve")
    async def reserve(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"reservation": ctx["order"]}

    @compensate("reserve")
    async def release(self, ctx: dict[str, Any]) -> None:
        return None

    @action("charge", depends_on=["reserve"])
    async def charge(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"charged": ctx["amount"]}

    @action("notify", depends_on=["charge"])
    async def notify(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"notified": True}


def percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile of already sorted values (0 for no values)."""
    if not sorted_values:
        return 0.0
    rank = max(1, round(pct / 100 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


async def _run_sagas(config: SagaConfig, profile: Profile, prefix: str) -> tuple[list[float], int]:
    latencies: list[float] = []
    failed = 0
    gate = asyncio.Semaphore(profile.concurrency)

    async def one(index: int) -> None:
        nonlocal failed
        async with gate:
            started = time.perf_counter()
            try:
                await BenchmarkSaga(config=config).run(
                    {"order": index, "amount": 10}, saga_id=f"{prefix}-{index}"
                )
            except Exception:
                failed += 1
                return
            latencies.append(time.perf_counter() - started)

    await asyncio.gather(*(one(i) for i in range(profile.sagas)))
    return latencies, failed


async def _cleanup(storage: Any, prefix: str, count: int) -> None:
    for index in range(count):
        await storage.delete_saga_state(f"{prefix}-{index}")


async def run_benchmark(profile: Profile, storage_url: str | None = None) -> BenchmarkResult:
    """Run ``profile`` and measure it; benchmark sagas are deleted afterwards."""
    from sagaz.core.storage import create_storage_manager

    prefix = f"sagaz-bench-{uuid4().hex[:8]}"
    async with create_storage_manager(url=storage_url or "memory://") as manager:
        storage: Any = manager.saga  # the manager's SagaStorage is the newer interface
        config = SagaConfig(storage=storage, metrics=False, logging=False, tracing=False)
        started = time.perf_counter()
        latencies, failed = await _run_sagas(config, profile, prefix)
        duration = time.perf_counter() - started
        if storage_url:
            await _cleanup(manager.saga, prefix, profile.sagas)

    ordered = sorted(latencies)
    return BenchmarkResult(
        profile=profile.name,
        storage=(storage_url or "memory://").split("://", 1)[0],
        sagas=profile.sagas,
        concurrency=profile.concurrency,
        failed=failed,
        duration_s=round(duration, 3),
        throughput=round(len(latencies) / duration, 1) if duration else 0.0,
        p50_ms=round(percentile(ordered, 50) * 1000, 2),
        p95_ms=round(percentile(ordered, 95) * 1000, 2),
        p99_ms=round(percentile(ordered, 99) * 1000, 2),
    )


def profiles_for(name: str, quick: bool) -> list[Profile]:
    """The profiles a ``--profile``/``--quick`` choice runs."""
    if quick:
        return [PROFILES["quick"]]
    if name == "full":
        return [PROFILES[p] for p in FULL]
    return [PROFILES[name]]


def summary(results: list[BenchmarkResult]) -> dict[str, Any]:
    """JSON-ready report of a benchmark run."""
    return {
        "results": [r.to_dict() for r in results],
        "median_throughput": statistics.median(r.throughput for r in results) if results else 0,
    }
