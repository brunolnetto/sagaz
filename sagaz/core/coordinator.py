"""
MultiRegionCoordinator — routes saga steps to the correct regional worker,
runs background health checks, and triggers automatic failover.

This implementation uses an in-process model suitable for testing and
single-node deployments.  In production, ``_dispatch_step`` would publish to
a regional message-broker.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from sagaz.core.regions import Region, RegionHealth, RegionRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vector clock for OCC conflict resolution
# ---------------------------------------------------------------------------


class VectorClock:
    """Simple vector clock for causal ordering across regions."""

    def __init__(self) -> None:
        self._clock: dict[str, int] = defaultdict(int)

    def tick(self, region_name: str) -> dict[str, int]:
        self._clock[region_name] += 1
        return dict(self._clock)

    def merge(self, other: dict[str, int]) -> None:
        for region, ts in other.items():
            self._clock[region] = max(self._clock[region], ts)

    def snapshot(self) -> dict[str, int]:
        return dict(self._clock)

    def happens_before(self, a: dict[str, int], b: dict[str, int]) -> bool:
        """Return True if clock *a* happened-before *b*."""
        return all(a.get(r, 0) <= b.get(r, 0) for r in set(a) | set(b)) and a != b


# ---------------------------------------------------------------------------
# Conflict resolution policies
# ---------------------------------------------------------------------------


class ConflictPolicy:
    LAST_WRITER_WINS = "last_writer_wins"
    FIRST_WRITER_WINS = "first_writer_wins"
    MANUAL = "manual"


@dataclass
class ConflictResult:
    saga_id: str
    winner: str  # region name
    policy: str
    ts_a: dict[str, int]
    ts_b: dict[str, int]


def resolve_conflict(
    saga_id: str,
    region_a: str,
    ts_a: dict[str, int],
    region_b: str,
    ts_b: dict[str, int],
    policy: str = ConflictPolicy.LAST_WRITER_WINS,
) -> ConflictResult:
    vc = VectorClock()
    if policy == ConflictPolicy.FIRST_WRITER_WINS:
        winner = region_a if vc.happens_before(ts_a, ts_b) else region_b
    elif policy == ConflictPolicy.LAST_WRITER_WINS:
        winner = region_b if vc.happens_before(ts_a, ts_b) else region_a
    else:
        msg = f"Manual conflict resolution requires human intervention for saga {saga_id}"
        raise NotImplementedError(msg)
    return ConflictResult(saga_id=saga_id, winner=winner, policy=policy, ts_a=ts_a, ts_b=ts_b)


# ---------------------------------------------------------------------------
# Step dispatch result
# ---------------------------------------------------------------------------


@dataclass
class StepDispatchResult:
    saga_id: str
    step_name: str
    region: str
    correlation_id: str
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0

    @property
    def success(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# Multi-region coordinator
# ---------------------------------------------------------------------------


class MultiRegionCoordinator:
    """
    Routes saga steps to regional workers, detects region failures, and
    triggers automatic failover.

    Parameters
    ----------
    registry:
        ``RegionRegistry`` with all known regions.
    health_check_interval:
        Seconds between background health probes.
    failover_timeout:
        Maximum seconds to wait for failover completion (target: < 5s).
    conflict_policy:
        Default conflict resolution strategy.
    """

    def __init__(
        self,
        registry: RegionRegistry,
        health_check_interval: float = 30.0,
        failover_timeout: float = 5.0,
        conflict_policy: str = ConflictPolicy.LAST_WRITER_WINS,
    ) -> None:
        self._registry = registry
        self._health_check_interval = health_check_interval
        self._failover_timeout = failover_timeout
        self._conflict_policy = conflict_policy
        self._vector_clock = VectorClock()
        self._health_task: asyncio.Task | None = None
        self._running = False
        # Prometheus-style counters (in-process)
        self.cross_region_calls: int = 0
        self.failover_count: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._health_task = asyncio.create_task(self._health_check_loop())
        logger.info("MultiRegionCoordinator started")

    async def stop(self) -> None:
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        logger.info("MultiRegionCoordinator stopped")

    # ------------------------------------------------------------------
    # Step routing
    # ------------------------------------------------------------------

    async def dispatch_step(
        self,
        saga_id: str,
        step_name: str,
        region_name: str | None,
        action: Callable[..., Coroutine],
        context: Any = None,
    ) -> StepDispatchResult:
        """
        Execute *action* in the designated *region_name* (or home region if None).

        If the target region is unhealthy, automatic failover is attempted
        within ``failover_timeout`` seconds.
        """
        target = self._resolve_region(region_name)
        if target is None:
            target = self._registry.home_region
        if target is None:
            return StepDispatchResult(
                saga_id=saga_id,
                step_name=step_name,
                region="none",
                correlation_id="",
                error="No available region",
            )

        if target.health == RegionHealth.UNREACHABLE:
            logger.warning("Region %s unreachable; triggering failover", target.name)
            new_target = await self._failover(target.name)
            if new_target is None:
                return StepDispatchResult(
                    saga_id=saga_id,
                    step_name=step_name,
                    region=target.name,
                    correlation_id="",
                    error=f"Region {target.name} unreachable and no failover available",
                )
            target = new_target

        correlation_id = str(uuid.uuid4())
        if region_name and region_name != (
            self._registry.home_region.name if self._registry.home_region else None
        ):
            self.cross_region_calls += 1

        ts_before = time.monotonic()
        try:
            result = await action(context) if context is not None else await action()
            duration_ms = (time.monotonic() - ts_before) * 1000
            self._vector_clock.tick(target.name)
            return StepDispatchResult(
                saga_id=saga_id,
                step_name=step_name,
                region=target.name,
                correlation_id=correlation_id,
                result=result,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - ts_before) * 1000
            return StepDispatchResult(
                saga_id=saga_id,
                step_name=step_name,
                region=target.name,
                correlation_id=correlation_id,
                error=str(exc),
                duration_ms=duration_ms,
            )

    def _resolve_region(self, name: str | None) -> Region | None:
        if name is None:
            return self._registry.home_region
        return self._registry.get(name)

    # ------------------------------------------------------------------
    # Failover
    # ------------------------------------------------------------------

    async def failover(self, from_region: str, to_region: str | None = None) -> Region | None:
        """
        Manually trigger failover from *from_region* to *to_region* (or best
        available if *to_region* is None).
        """
        return await self._failover(from_region, to_region)

    async def _failover(self, from_region: str, to_region: str | None = None) -> Region | None:
        if to_region:
            target = self._registry.get(to_region)
        else:
            target = self._registry.best_failover(exclude=from_region)

        if target is None:
            logger.error("Failover from %s: no healthy region available", from_region)
            return None

        # Mark source as unreachable
        self._registry.update_health(from_region, RegionHealth.UNREACHABLE)
        # Update home if needed
        if self._registry.home_region and self._registry.home_region.name == from_region:
            self._registry._home = target.name

        self.failover_count += 1
        logger.warning("Failover: %s → %s", from_region, target.name)
        return target

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def _health_check_loop(self) -> None:
        while self._running:
            for region in self._registry.all_regions():
                await self._probe_region(region)
            await asyncio.sleep(self._health_check_interval)

    async def _probe_region(self, region: Region) -> None:
        """Probe *region* health.  In production this would be an HTTP check."""
        start = time.monotonic()
        try:
            # Simulate: regions with broker_url starting with "fail://" are treated as down
            if region.broker_url.startswith("fail://"):
                msg = "simulated failure"
                raise ConnectionError(msg)
            await asyncio.sleep(0)  # yield control
            latency_ms = (time.monotonic() - start) * 1000
            self._registry.update_health(region.name, RegionHealth.HEALTHY, latency_ms)
        except Exception:
            self._registry.update_health(region.name, RegionHealth.UNREACHABLE)
            logger.warning("Health check failed for region %s", region.name)

    # ------------------------------------------------------------------
    # Conflict resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        saga_id: str,
        region_a: str,
        ts_a: dict[str, int],
        region_b: str,
        ts_b: dict[str, int],
    ) -> ConflictResult:
        return resolve_conflict(
            saga_id, region_a, ts_a, region_b, ts_b, policy=self._conflict_policy
        )
