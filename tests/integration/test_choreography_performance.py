"""
Performance benchmarks for the sagaz choreography module.

Measures in-process EventBus throughput and latency under various loads:

1. Publish throughput — raw events/sec through the in-process EventBus.
2. Fan-out throughput — one publisher → N concurrent handlers.
3. Event-chain latency — end-to-end latency for a multi-step saga chain.
4. Engine registration overhead — cost of register/unregister per saga.

Run with:
    pytest tests/integration/test_choreography_performance.py -v -m performance

"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass

import pytest

from sagaz.choreography import (
    ChoreographedSaga,
    ChoreographyEngine,
    Event,
    EventBus,
    on_event,
)

pytestmark = pytest.mark.performance


# ---------------------------------------------------------------------------
# Benchmark configuration
# ---------------------------------------------------------------------------


@dataclass
class BenchConfig:
    """Tunable parameters for each benchmark scenario."""

    iterations: int
    concurrency: int


LOCAL = BenchConfig(iterations=500, concurrency=10)
CI = BenchConfig(iterations=200, concurrency=5)


def _config() -> BenchConfig:
    """Return LOCAL config (CI guard can lower it via env)."""
    import os

    return CI if os.getenv("CI") else LOCAL


# ---------------------------------------------------------------------------
# Result dataclass and helpers
# ---------------------------------------------------------------------------


@dataclass
class BenchResult:
    total: int
    elapsed: float
    latencies_ms: list[float]

    @property
    def throughput(self) -> float:
        return self.total / self.elapsed if self.elapsed else 0.0

    @property
    def p50(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p95(self) -> float:
        if not self.latencies_ms:
            return 0.0
        s = sorted(self.latencies_ms)
        return s[int(len(s) * 0.95)]

    @property
    def p99(self) -> float:
        if not self.latencies_ms:
            return 0.0
        s = sorted(self.latencies_ms)
        return s[int(len(s) * 0.99)]

    @property
    def mean(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0

    def print_summary(self, label: str) -> None:
        print(
            f"\n--- {label} ---\n"
            f"  iterations : {self.total}\n"
            f"  elapsed    : {self.elapsed:.3f}s\n"
            f"  throughput : {self.throughput:,.0f} ops/sec\n"
            f"  mean       : {self.mean:.4f} ms\n"
            f"  p50        : {self.p50:.4f} ms\n"
            f"  p95        : {self.p95:.4f} ms\n"
            f"  p99        : {self.p99:.4f} ms"
        )


async def _run_batched(coro_factory, iterations: int, concurrency: int) -> BenchResult:
    """Run *coro_factory()* *iterations* times in batches of *concurrency*."""
    latencies: list[float] = []
    t0 = time.perf_counter()
    remaining = iterations
    while remaining > 0:
        batch = min(concurrency, remaining)
        t_batch = time.perf_counter()
        await asyncio.gather(*[coro_factory() for _ in range(batch)])
        elapsed_batch = (time.perf_counter() - t_batch) * 1000 / batch
        latencies.extend([elapsed_batch] * batch)
        remaining -= batch
    return BenchResult(
        total=iterations,
        elapsed=time.perf_counter() - t0,
        latencies_ms=latencies,
    )


# ---------------------------------------------------------------------------
# Saga definitions used across benchmarks
# ---------------------------------------------------------------------------


class NoopSaga(ChoreographedSaga):
    """A saga with one event handler that does nothing — baseline overhead."""

    @on_event("bench.event")
    async def handle(self, event: Event) -> None:
        pass  # intentional no-op for measuring dispatch overhead


class FanOutSaga(ChoreographedSaga):
    """Receives fan-out events and records arrival."""

    def __init__(self, saga_id: str, collector: list[str]) -> None:
        super().__init__(saga_id=saga_id)
        self._collector = collector

    @on_event("fanout.event")
    async def handle(self, event: Event) -> None:
        self._collector.append(self.saga_id)


class ChainStep(ChoreographedSaga):
    """One link in a multi-step event chain."""

    def __init__(
        self,
        saga_id: str,
        listen_for: str,
        emit: str | None,
        bus: EventBus,
        trace: list[str],
    ) -> None:
        super().__init__(saga_id=saga_id)
        self._emit_event = emit
        self._bus = bus
        self._trace = trace
        # Register the handler manually after init to support parameterized event types.
        self._handlers[listen_for] = self._step

    async def _step(self, event: Event) -> None:
        self._trace.append(self.saga_id)
        if self._emit_event:
            await self._bus.publish(Event(self._emit_event, event.data))


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pub_sub_throughput() -> None:
    """Measure raw publish → single handler throughput on the in-process EventBus."""
    cfg = _config()
    bus = EventBus()
    received: list[Event] = []

    async def handler(e: Event) -> None:
        received.append(e)

    bus.subscribe("bench.event", handler)

    async def one_publish() -> None:
        await bus.publish(Event("bench.event", {"n": 1}))

    result = await _run_batched(one_publish, cfg.iterations, cfg.concurrency)
    result.print_summary("Publish → single handler throughput")

    assert len(received) == cfg.iterations
    assert result.throughput > 100, f"throughput too low: {result.throughput:.0f} ops/sec"
    assert result.p99 < 50, f"p99 too high: {result.p99:.2f} ms"


@pytest.mark.asyncio
async def test_engine_dispatch_throughput() -> None:
    """Measure ChoreographyEngine dispatch throughput (register + publish)."""
    cfg = _config()
    bus = EventBus()
    engine = ChoreographyEngine(bus)

    dispatched: list[str] = []
    saga = NoopSaga(saga_id="bench-saga")
    # Override handle to record dispatches.
    original_handle = saga.handle

    async def recording_handle(event: Event) -> None:
        dispatched.append(event.event_type)
        await original_handle(event)

    saga.handle = recording_handle  # type: ignore[method-assign]

    engine.register(saga)
    await engine.start()

    async def fire_one() -> None:
        await bus.publish(Event("bench.event", {"n": 1}))

    result = await _run_batched(fire_one, cfg.iterations, cfg.concurrency)
    await engine.stop()

    result.print_summary("ChoreographyEngine dispatch throughput")

    assert len(dispatched) == cfg.iterations
    assert result.throughput > 100, f"throughput too low: {result.throughput:.0f} ops/sec"


@pytest.mark.asyncio
async def test_fan_out_throughput() -> None:
    """Measure fan-out: one event published to N sagas simultaneously."""
    cfg = _config()
    fan_out_size = 10
    bus = EventBus()
    engine = ChoreographyEngine(bus)
    collector: list[str] = []

    for i in range(fan_out_size):
        engine.register(FanOutSaga(saga_id=f"fan-{i}", collector=collector))

    await engine.start()

    async def one_event() -> None:
        collector.clear()
        await bus.publish(Event("fanout.event", {}))

    latencies: list[float] = []
    t0 = time.perf_counter()
    for _ in range(cfg.iterations):
        t1 = time.perf_counter()
        collector.clear()
        await bus.publish(Event("fanout.event", {}))
        latencies.append((time.perf_counter() - t1) * 1000)

    result = BenchResult(
        total=cfg.iterations,
        elapsed=time.perf_counter() - t0,
        latencies_ms=latencies,
    )
    await engine.stop()

    result.print_summary(f"Fan-out → {fan_out_size} sagas throughput")

    assert result.throughput > 50, f"throughput too low: {result.throughput:.0f} ops/sec"
    assert result.p99 < 100, f"p99 too high: {result.p99:.2f} ms"


@pytest.mark.asyncio
async def test_event_chain_latency() -> None:
    """
    Measure end-to-end latency for a 4-step event chain.

    Chain: trigger → step-a → step-b → step-c → step-d (terminal)
    """
    iterations = 50  # chains take more time — keep count lower
    bus = EventBus()
    engine = ChoreographyEngine(bus)
    trace: list[str] = []

    chain = [
        ChainStep("step-a", "chain.trigger", "chain.b", bus, trace),
        ChainStep("step-b", "chain.b", "chain.c", bus, trace),
        ChainStep("step-c", "chain.c", "chain.d", bus, trace),
        ChainStep("step-d", "chain.d", None, bus, trace),
    ]
    for step in chain:
        engine.register(step)

    await engine.start()

    latencies_ms: list[float] = []
    t0 = time.perf_counter()
    for _ in range(iterations):
        trace.clear()
        t1 = time.perf_counter()
        await bus.publish(Event("chain.trigger", {"run": 1}))
        latencies_ms.append((time.perf_counter() - t1) * 1000)

    result = BenchResult(
        total=iterations,
        elapsed=time.perf_counter() - t0,
        latencies_ms=latencies_ms,
    )
    await engine.stop()

    result.print_summary("4-step event chain end-to-end latency")

    assert result.p99 < 50, f"chain p99 too high: {result.p99:.2f} ms"
    assert result.mean < 10, f"chain mean too high: {result.mean:.2f} ms"


@pytest.mark.asyncio
async def test_register_unregister_throughput() -> None:
    """Measure the overhead of engine.register() / engine.unregister() cycles."""
    cfg = _config()
    bus = EventBus()
    engine = ChoreographyEngine(bus)
    await engine.start()

    latencies_ms: list[float] = []
    t0 = time.perf_counter()
    for i in range(cfg.iterations):
        saga = NoopSaga(saga_id=f"reg-{i}")
        t1 = time.perf_counter()
        engine.register(saga)
        engine.unregister(saga.saga_id)
        latencies_ms.append((time.perf_counter() - t1) * 1000)

    result = BenchResult(
        total=cfg.iterations,
        elapsed=time.perf_counter() - t0,
        latencies_ms=latencies_ms,
    )
    await engine.stop()

    result.print_summary("Register + unregister throughput")

    assert result.throughput > 500, f"register/unregister too slow: {result.throughput:.0f} ops/sec"
    assert result.p99 < 10, f"p99 too high: {result.p99:.2f} ms"


@pytest.mark.asyncio
async def test_wildcard_handler_throughput() -> None:
    """Publish diverse event types to a bus with a single wildcard handler."""
    cfg = _config()
    bus = EventBus()
    received = 0
    event_types = [f"domain.event.{i}" for i in range(20)]

    async def wildcard(e: Event) -> None:
        nonlocal received
        received += 1

    bus.subscribe("*", wildcard)

    import random

    latencies_ms: list[float] = []
    t0 = time.perf_counter()
    for _ in range(cfg.iterations):
        evt = Event(random.choice(event_types), {"n": 1})
        t1 = time.perf_counter()
        await bus.publish(evt)
        latencies_ms.append((time.perf_counter() - t1) * 1000)

    result = BenchResult(
        total=cfg.iterations,
        elapsed=time.perf_counter() - t0,
        latencies_ms=latencies_ms,
    )

    result.print_summary("Wildcard handler throughput (20 distinct event types)")

    assert received == cfg.iterations
    assert result.throughput > 100, f"throughput too low: {result.throughput:.0f} ops/sec"
