"""Regions, their jurisdictions and their health (ADR-034, #59)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass


class RegionUnavailableError(RuntimeError):
    """No healthy region may run a step (its own is down, and so are its stand-ins)."""


@dataclass(frozen=True)
class Region:
    """A region whose workers run the steps assigned to it.

    Attributes:
        name: Region name, as used in ``region=`` on steps (``"eu-west-1"``).
        jurisdiction: Data-residency zone (``"EU"``). A step only fails over to
            another region of the same jurisdiction, so its data never leaves it.
        bus_url: Message bus of the region (``redis://``, ``kafka://``,
            ``amqp://`` or ``memory://``).
        priority: Failover order within a jurisdiction (lower first).
    """

    name: str
    jurisdiction: str
    bus_url: str = "memory://"
    priority: int = 0


class RegionRegistry:
    """Known regions, which one is home, and which are healthy.

    A region is healthy while its workers' heartbeats are recent: within
    ``stale_after`` seconds. A region not heard from since the registry was
    created gets the same grace period.
    """

    def __init__(
        self,
        regions: Iterable[Region],
        home: str,
        stale_after: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._regions = {r.name: r for r in regions}
        if home not in self._regions:
            msg = f"Home region {home!r} is not among the regions {sorted(self._regions)}"
            raise ValueError(msg)
        self.home = home
        self.stale_after = stale_after
        self._clock = clock
        started = clock()
        self._last_seen = dict.fromkeys(self._regions, started)
        self._overrides: dict[str, str] = {}

    def __iter__(self) -> Iterator[Region]:
        return iter(sorted(self._regions.values(), key=lambda r: (r.jurisdiction, r.priority)))

    def get(self, name: str) -> Region:
        try:
            return self._regions[name]
        except KeyError:
            msg = f"Unknown region {name!r}; known: {sorted(self._regions)}"
            raise ValueError(msg) from None

    # -- health ---------------------------------------------------------------

    def heartbeat(self, name: str) -> None:
        if name in self._last_seen:
            self._last_seen[name] = self._clock()

    def seconds_since_heartbeat(self, name: str) -> float:
        return float(self._clock() - self._last_seen[name])

    def is_healthy(self, name: str) -> bool:
        return self.seconds_since_heartbeat(name) <= self.stale_after

    # -- routing --------------------------------------------------------------

    def failover(self, from_region: str, to_region: str, *, force: bool = False) -> None:
        """Route *from_region*'s steps to *to_region* until :meth:`restore`.

        Crossing jurisdictions moves data out of its zone, so it needs *force*.
        """
        source, target = self.get(from_region), self.get(to_region)
        if source.jurisdiction != target.jurisdiction and not force:
            msg = (
                f"{to_region} ({target.jurisdiction}) is outside {from_region}'s jurisdiction "
                f"({source.jurisdiction}); pass force=True to move its steps there anyway"
            )
            raise ValueError(msg)
        self._overrides[from_region] = to_region

    def restore(self, from_region: str) -> None:
        self._overrides.pop(from_region, None)

    @property
    def overrides(self) -> dict[str, str]:
        return dict(self._overrides)

    def route(self, name: str) -> str:
        """The region that runs a step declared for *name* now.

        A manual failover wins. Otherwise *name* itself while healthy, else the
        healthy region of the same jurisdiction with the lowest priority.
        """
        if name in self._overrides:
            return self._overrides[name]
        region = self.get(name)
        if self.is_healthy(name):
            return name
        standins = sorted(
            (
                r
                for r in self._regions.values()
                if r.jurisdiction == region.jurisdiction
                and r.name != name
                and self.is_healthy(r.name)
            ),
            key=lambda r: (r.priority, r.name),
        )
        if not standins:
            msg = (
                f"Region {name} is unavailable and no healthy region of its jurisdiction "
                f"({region.jurisdiction}) can stand in"
            )
            raise RegionUnavailableError(msg)
        return standins[0].name

    def serves(self, worker_region: str, step_region: str) -> bool:
        """Whether a worker of *worker_region* may run a step declared for *step_region*."""
        return self.get(worker_region).jurisdiction == self.get(step_region).jurisdiction
