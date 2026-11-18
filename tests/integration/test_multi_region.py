"""Multi-region saga steps over Redis Streams (ADR-034, #59).

Each region gets its own Redis database (standing in for its own broker), its
own workers and the production timings: a heartbeat per second, a region is
down after 3 s without one. Skipped without Docker.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.regions import MultiRegionCoordinator, Region, RegionalWorker, bus_from_url

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

served: list[str] = []


class Checkout(Saga):
    saga_name = "checkout-it"

    @action("reserve")
    async def reserve(self, ctx):
        return {"reservation": "r-1"}

    @compensate("reserve")
    async def release(self, ctx):
        return None

    @action("charge", depends_on=["reserve"], region="eu-west-1", timeout_seconds=10)
    async def charge(self, ctx):
        return {"charge": f"ch-{ctx['reservation']}"}


@pytest.fixture
async def world(redis_container):
    host, port = redis_container.get_container_host_ip(), redis_container.get_exposed_port(6379)
    regions = [
        Region("us-east-1", "US", f"redis://{host}:{port}/1"),
        Region("eu-west-1", "EU", f"redis://{host}:{port}/2"),
        Region("eu-central-1", "EU", f"redis://{host}:{port}/3", priority=1),
    ]
    coordinator = MultiRegionCoordinator.from_regions(regions, "us-east-1", stale_after=3)
    workers = {}
    for region in regions[1:]:
        bus = bus_from_url(region.bus_url, f"sagaz-worker-{region.name}", f"{region.name}-w1")
        await bus.start()
        worker = RegionalWorker(region.name, bus, heartbeat_interval=1)
        worker.register(
            "checkout-it",
            "charge",
            _tagged(region.name, Checkout().get_step("charge").forward_fn),
        )
        await worker.start()
        workers[region.name] = worker
    await coordinator.start()
    served.clear()
    yield coordinator, workers
    await coordinator.stop()
    for worker in workers.values():
        await worker.stop()
        await worker.bus.stop()


def _tagged(region, fn):
    async def run(ctx):
        served.append(region)
        return await fn(ctx)

    return run


def config(coordinator) -> SagaConfig:
    return SagaConfig(regions=coordinator, metrics=False, logging=False)


async def test_a_step_runs_in_a_non_home_region(world):
    coordinator, _ = world
    result = await Checkout(config=config(coordinator)).run({})
    assert result["charge"] == "ch-r-1"
    assert served == ["eu-west-1"]


async def test_failover_within_the_jurisdiction_in_under_5_seconds(world):
    coordinator, workers = world
    await Checkout(config=config(coordinator)).run({})  # eu-west-1 is serving
    await workers["eu-west-1"].stop()  # the region goes dark
    down_at = time.monotonic()
    while coordinator.target("eu-west-1") != "eu-central-1":
        assert time.monotonic() - down_at < 5, "failover took 5 s or more"
        await asyncio.sleep(0.1)
    result = await Checkout(config=config(coordinator)).run({})
    elapsed = time.monotonic() - down_at
    assert result["charge"] == "ch-r-1"
    assert served == ["eu-west-1", "eu-central-1"]
    assert elapsed < 5
