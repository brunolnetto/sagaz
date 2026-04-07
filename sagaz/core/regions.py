"""
Region dataclass and RegionRegistry for multi-region saga coordination.

A ``Region`` represents a geographic deployment zone with its own storage
and broker endpoints.  ``RegionRegistry`` manages the set of known regions
and tracks their health state.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RegionHealth(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


@dataclass
class Region:
    """
    A geographic deployment region.

    Parameters
    ----------
    name:
        Unique region identifier, e.g. ``"us-east-1"``.
    storage_url:
        Connection string for the region's storage backend.
    broker_url:
        Message-broker endpoint used for cross-region step dispatch.
    priority:
        Lower value = preferred for failover.  Home region should be 0.
    """

    name: str
    storage_url: str = ""
    broker_url: str = ""
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    # Mutable runtime fields (excluded from hash)
    health: RegionHealth = field(default=RegionHealth.UNKNOWN, compare=False, hash=False)
    latency_ms: float = field(default=float("inf"), compare=False, hash=False)
    last_checked: datetime | None = field(default=None, compare=False, hash=False)

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Region):
            return self.name == other.name
        return NotImplemented

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "storage_url": self.storage_url,
            "broker_url": self.broker_url,
            "priority": self.priority,
            "health": self.health.value,
            "latency_ms": self.latency_ms if self.latency_ms != float("inf") else None,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
        }


class RegionRegistry:
    """
    Manages a collection of ``Region`` objects and their health state.

    Example
    -------
    ::

        registry = RegionRegistry()
        registry.register(Region("us-east-1", priority=0))
        registry.register(Region("eu-west-1", priority=1))
        healthy = registry.healthy_regions()
    """

    def __init__(self) -> None:
        self._regions: dict[str, Region] = {}
        self._home: str | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, region: Region, home: bool = False) -> None:
        """Add *region* to the registry.  Set *home=True* for the local region."""
        self._regions[region.name] = region
        if home or self._home is None:
            self._home = region.name

    def get(self, name: str) -> Region | None:
        return self._regions.get(name)

    def all_regions(self) -> list[Region]:
        return list(self._regions.values())

    def healthy_regions(self) -> list[Region]:
        return [r for r in self._regions.values() if r.health == RegionHealth.HEALTHY]

    @property
    def home_region(self) -> Region | None:
        if self._home:
            return self._regions.get(self._home)
        return None

    def best_failover(self, exclude: str | None = None) -> Region | None:
        """Return the highest-priority healthy region, excluding *exclude*."""
        candidates = [r for r in self.healthy_regions() if r.name != exclude]
        if not candidates:
            return None
        return min(candidates, key=lambda r: r.priority)

    def update_health(
        self, name: str, health: RegionHealth, latency_ms: float = float("inf")
    ) -> None:
        region = self._regions.get(name)
        if region:
            region.health = health
            region.latency_ms = latency_ms
            region.last_checked = datetime.now(UTC)
