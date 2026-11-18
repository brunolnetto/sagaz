"""Routes region-assigned saga steps to regional workers (ADR-034, #59).

The saga keeps one coordinator: the process running it. A step declared with
``region="eu-west-1"`` is sent over that region's bus to its workers, and the
coordinator waits for the reply (matched by request id). Data-residency comes
first: when a region is down, its steps only fail over to a healthy region of
the same jurisdiction. If none is healthy, the step fails and the saga
compensates; nothing moves to another jurisdiction unless an operator forces it
(``sagaz region failover --force``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sagaz.choreography.events import AbstractEventBus, Event
from sagaz.core.events import json_safe
from sagaz.core.regions._protocol import (
    FAILOVER,
    HEARTBEAT,
    REPLY_PREFIX,
    REQUEST,
    RemoteStepError,
    bus_from_url,
)
from sagaz.core.regions._registry import Region, RegionRegistry
from sagaz.core.tenant import current_tenant_id

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram

    CROSS_REGION_LATENCY: Any = Histogram(
        "sagaz_cross_region_latency_seconds",
        "Round trip of a saga step run in another region",
        ["from_region", "to_region", "kind"],
    )
    REGION_FAILOVERS: Any = Counter(
        "sagaz_region_failover_total",
        "Times a region's steps started running in another region",
        ["from_region", "to_region", "reason"],
    )
except ImportError:  # pragma: no cover - prometheus_client is optional
    CROSS_REGION_LATENCY = REGION_FAILOVERS = None


class MultiRegionCoordinator:
    """Sends steps to the regions they are declared for, and waits for the result.

    Args:
        registry: The regions, the home region and the health rules.
        buses: One event bus per region (by name). The coordinator subscribes
            to replies, heartbeats and failover commands on each.
        coordinator_id: Identifies this process's replies (default: random).
    """

    def __init__(
        self,
        registry: RegionRegistry,
        buses: Mapping[str, AbstractEventBus],
        *,
        coordinator_id: str | None = None,
    ) -> None:
        missing = {r.name for r in registry} - set(buses)
        if missing:
            msg = f"No bus for regions {sorted(missing)}"
            raise ValueError(msg)
        self.registry = registry
        self.buses = dict(buses)
        self.coordinator_id = coordinator_id or uuid4().hex
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._routes: dict[str, str] = {}
        self._seen_commands: set[str] = set()
        self._started = False
        self._lock = asyncio.Lock()

    @classmethod
    def from_regions(
        cls,
        regions: list[Region],
        home: str,
        *,
        stale_after: float = 3.0,
        coordinator_id: str | None = None,
    ) -> MultiRegionCoordinator:
        """A coordinator with a bus per region built from each ``bus_url``."""
        coordinator_id = coordinator_id or uuid4().hex
        buses = {
            r.name: bus_from_url(r.bus_url, f"sagaz-coordinator-{coordinator_id}", coordinator_id)
            for r in regions
        }
        registry = RegionRegistry(regions, home, stale_after=stale_after)
        coordinator = cls(registry, buses, coordinator_id=coordinator_id)
        coordinator._owns_buses = True
        return coordinator

    _owns_buses = False

    @property
    def home(self) -> str:
        return self.registry.home

    @property
    def _reply_type(self) -> str:
        return REPLY_PREFIX + self.coordinator_id

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        """Subscribe to every region bus (idempotent)."""
        async with self._lock:
            if self._started:
                return
            for bus in self.buses.values():
                if self._owns_buses:
                    await bus.start()
                bus.subscribe(self._reply_type, self._on_reply)
                bus.subscribe(HEARTBEAT, self._on_heartbeat)
                bus.subscribe(FAILOVER, self._on_failover)
            self._started = True

    async def stop(self) -> None:
        for bus in self.buses.values():
            bus.unsubscribe(self._reply_type, self._on_reply)
            bus.unsubscribe(HEARTBEAT, self._on_heartbeat)
            bus.unsubscribe(FAILOVER, self._on_failover)
            if self._owns_buses:
                await bus.stop()
        for future in self._pending.values():
            future.cancel()
        self._pending.clear()
        self._started = False

    # -- routing ---------------------------------------------------------------

    def target(self, region: str) -> str:
        """The region that runs a step declared for *region* now (see ``RegionRegistry.route``)."""
        target = self.registry.route(region)
        previous = self._routes.get(region, region)
        if target != previous:
            reason = "manual" if region in self.registry.overrides else "automatic"
            if target != region:
                logger.warning("Region %s: steps now run in %s (%s)", region, target, reason)
                if REGION_FAILOVERS is not None:
                    REGION_FAILOVERS.labels(region, target, reason).inc()
            else:
                logger.info("Region %s: steps run there again", region)
        self._routes[region] = target
        return target

    async def run(
        self,
        target: str,
        *,
        saga_name: str,
        saga_id: str,
        step: str,
        kind: str,
        context: dict[str, Any],
        declared: str | None = None,
    ) -> Any:
        """Run *step* (``kind`` is ``"action"`` or ``"compensation"``) in *target*.

        Returns the step's result; raises :class:`RemoteStepError` if it raised
        there. The caller bounds the wait (the step's timeout).
        """
        await self.start()
        forced = declared is not None and not self.registry.serves(target, declared)
        request = Event(
            REQUEST,
            {
                "target": target,
                "coordinator": self.coordinator_id,
                "saga_name": saga_name,
                "step": step,
                "kind": kind,
                "context": json_safe(context),
                "forced": forced,
            },
            saga_id=saga_id,
            tenant_id=current_tenant_id(),
            source=self.coordinator_id,
        )
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request.event_id] = future
        started = time.perf_counter()
        try:
            await self.buses[target].publish(request)
            reply = await future
        finally:
            self._pending.pop(request.event_id, None)
            if CROSS_REGION_LATENCY is not None:
                CROSS_REGION_LATENCY.labels(self.home, target, kind).observe(
                    time.perf_counter() - started
                )
        if not reply.get("ok"):
            raise RemoteStepError(
                target, reply.get("error_type", "Error"), reply.get("error_message", "")
            )
        return reply.get("result")

    # -- bus handlers ------------------------------------------------------------

    async def _on_reply(self, event: Event) -> None:
        future = self._pending.get(event.data.get("request_id", ""))
        if future is not None and not future.done():
            future.set_result(event.data)

    async def _on_heartbeat(self, event: Event) -> None:
        self.registry.heartbeat(event.data.get("region", ""))

    async def _on_failover(self, event: Event) -> None:
        if event.event_id in self._seen_commands:  # published on every region bus
            return
        self._seen_commands.add(event.event_id)
        source, to = str(event.data.get("from") or ""), event.data.get("to")
        try:
            if to:
                self.registry.failover(source, to, force=bool(event.data.get("force")))
            else:
                self.registry.restore(source)
        except ValueError as error:
            logger.error("Ignoring failover command: %s", error)
            return
        self.target(source)


async def publish_failover(
    buses: Mapping[str, AbstractEventBus], from_region: str, to_region: str | None, force: bool
) -> int:
    """Tell every coordinator to route *from_region* to *to_region* (``None`` restores).

    Published on every reachable region bus; returns how many accepted it.
    """
    command = Event(FAILOVER, {"from": from_region, "to": to_region, "force": force})
    delivered = 0
    for name, bus in buses.items():
        try:
            await bus.publish(command)
            delivered += 1
        except Exception as error:
            logger.warning("Could not publish the failover on region %s: %s", name, error)
    return delivered
