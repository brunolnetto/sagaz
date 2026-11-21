"""The ``regions:`` block of ``sagaz.yaml``.

.. code-block:: yaml

    regions:
      home: us-east-1          # where this process runs
      stale_after: 3           # seconds without heartbeats before a region is down
      members:
        - {name: us-east-1,    jurisdiction: US, bus: "redis://us-redis:6379"}
        - {name: eu-west-1,    jurisdiction: EU, bus: "redis://eu-redis:6379"}
        - {name: eu-central-1, jurisdiction: EU, bus: "redis://eu2-redis:6379", priority: 1}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.regions.coordinator import MultiRegionCoordinator

from sagaz.core.regions._registry import Region


def regions_from_config(data: dict[str, Any]) -> list[Region]:
    members = data.get("members") or []
    if not members:
        msg = "regions: needs at least one entry under 'members'"
        raise ValueError(msg)
    regions = []
    for entry in members:
        try:
            regions.append(
                Region(
                    name=str(entry["name"]),
                    jurisdiction=str(entry["jurisdiction"]),
                    bus_url=str(entry.get("bus", "memory://")),
                    priority=int(entry.get("priority", 0)),
                )
            )
        except KeyError as missing:
            msg = f"regions.members entry {entry!r} lacks {missing}"
            raise ValueError(msg) from None
    return regions


def coordinator_from_config(data: dict[str, Any]) -> MultiRegionCoordinator:
    """A (not yet started) ``MultiRegionCoordinator`` for a ``regions:`` block."""
    from sagaz.core.regions.coordinator import MultiRegionCoordinator

    if "home" not in data:
        msg = "regions: needs 'home', the region this process runs in"
        raise ValueError(msg)
    return MultiRegionCoordinator.from_regions(
        regions_from_config(data),
        str(data["home"]),
        stale_after=float(data.get("stale_after", 3.0)),
    )
