"""Multi-region saga steps with data residency (ADR-034, #59).

Declare where a step runs, and run a worker in that region::

    class CheckoutSaga(Saga):
        @action("charge", region="eu-west-1")   # EU card data stays in the EU
        async def charge(self, ctx): ...

    coordinator = MultiRegionCoordinator.from_regions(
        [Region("us-east-1", "US", "redis://us..."),
         Region("eu-west-1", "EU", "redis://eu..."),
         Region("eu-central-1", "EU", "redis://eu2...", priority=1)],
        home="us-east-1",
    )
    configure(SagaConfig(regions=coordinator))

    # in eu-west-1 (and eu-central-1, its stand-in):
    worker = RegionalWorker("eu-west-1", bus_from_url("redis://eu...", "sagaz-worker-eu-west-1", "w1"))
    worker.serve(CheckoutSaga)
    await worker.start()
"""

from sagaz.core.regions._protocol import (
    ACTION,
    COMPENSATION,
    RemoteStepError,
    bus_from_url,
)
from sagaz.core.regions._registry import Region, RegionRegistry, RegionUnavailableError
from sagaz.core.regions.coordinator import MultiRegionCoordinator, publish_failover
from sagaz.core.regions.worker import RegionalWorker

__all__ = [
    "ACTION",
    "COMPENSATION",
    "MultiRegionCoordinator",
    "Region",
    "RegionRegistry",
    "RegionUnavailableError",
    "RegionalWorker",
    "RemoteStepError",
    "bus_from_url",
    "publish_failover",
]
