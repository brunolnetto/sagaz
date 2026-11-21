"""
Product Launch Saga Example (Consumer Goods)

Launching a new product line coordinates the factory, packaging suppliers,
retail partners, carriers and marketing. Until the goods leave for the
retailers, every commitment can be cancelled; once they ship, the launch is
committed.

Pivot Step: ship_to_retailers
    Once the first wave leaves the distribution center, the launch cannot be
    undone, only followed up (returns, markdowns). Steps before it are
    compensated in reverse dependency order if anything fails.

Run it:
    python -m sagaz.examples.consumer_goods.product.product_launch.main
"""

import asyncio
import logging
import uuid
from typing import Any

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _maybe_fail(ctx: SagaContext, step: str) -> None:
    """Simulate a failure at ``ctx["fail_at"]`` to show the compensation."""
    if ctx.get("fail_at") == step:
        msg = f"{step} failed (simulated)"
        raise RuntimeError(msg)


class ProductLaunchSaga(Saga):
    """Launch a product line: capacity, packaging, shelf space, carriers, campaign."""

    saga_name = "product-launch"

    @action("reserve_production_capacity")
    async def reserve_production_capacity(self, ctx: SagaContext) -> dict[str, Any]:
        sku = ctx.get("sku")
        logger.info(f"🏭 [{sku}] Reserving {ctx.get('launch_units')} units of line capacity...")
        await asyncio.sleep(0.1)
        _maybe_fail(ctx, "reserve_production_capacity")
        return {"production_slot": f"SLOT-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("reserve_production_capacity")
    async def release_production_capacity(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('sku')}] Releasing slot {ctx.get('production_slot')}")
        await asyncio.sleep(0.05)

    @action("order_packaging", depends_on=["reserve_production_capacity"])
    async def order_packaging(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"📦 [{ctx.get('sku')}] Ordering cartons and labels from the supplier...")
        await asyncio.sleep(0.1)
        _maybe_fail(ctx, "order_packaging")
        return {"packaging_po": f"PO-PKG-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("order_packaging")
    async def cancel_packaging(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('sku')}] Cancelling packaging PO {ctx.get('packaging_po')}")
        await asyncio.sleep(0.05)

    @action("allocate_shelf_space", depends_on=["reserve_production_capacity"])
    async def allocate_shelf_space(self, ctx: SagaContext) -> dict[str, Any]:
        retailers = ctx.get("retailers", [])
        logger.info(
            f"🛒 [{ctx.get('sku')}] Allocating shelf space at {len(retailers)} retailers..."
        )
        await asyncio.sleep(0.1)
        _maybe_fail(ctx, "allocate_shelf_space")
        return {"planograms": [f"PLAN-{r}" for r in retailers]}

    @compensate("allocate_shelf_space")
    async def release_shelf_space(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('sku')}] Releasing planograms {ctx.get('planograms')}")
        await asyncio.sleep(0.05)

    @action("book_distribution", depends_on=["order_packaging", "allocate_shelf_space"])
    async def book_distribution(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🚚 [{ctx.get('sku')}] Booking carriers for the first wave...")
        await asyncio.sleep(0.1)
        _maybe_fail(ctx, "book_distribution")
        return {"carrier_booking": f"BK-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("book_distribution")
    async def cancel_distribution(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('sku')}] Cancelling booking {ctx.get('carrier_booking')}")
        await asyncio.sleep(0.05)

    @action("schedule_campaign", depends_on=["allocate_shelf_space"])
    async def schedule_campaign(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"📣 [{ctx.get('sku')}] Scheduling the launch campaign...")
        await asyncio.sleep(0.1)
        _maybe_fail(ctx, "schedule_campaign")
        return {"campaign_id": f"CMP-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("schedule_campaign")
    async def cancel_campaign(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('sku')}] Cancelling campaign {ctx.get('campaign_id')}")
        await asyncio.sleep(0.05)

    @action("ship_to_retailers", depends_on=["book_distribution", "schedule_campaign"], pivot=True)
    async def ship_to_retailers(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT: the first wave leaves the distribution center."""
        logger.info(f"🔒 [{ctx.get('sku')}] PIVOT: shipping the first wave to retailers...")
        await asyncio.sleep(0.15)
        _maybe_fail(ctx, "ship_to_retailers")
        return {"shipment_wave": f"WAVE-{uuid.uuid4().hex[:6].upper()}"}

    @action("announce_launch", depends_on=["ship_to_retailers"])
    async def announce_launch(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🎉 [{ctx.get('sku')}] Product launched!")
        await asyncio.sleep(0.05)
        return {"launched": True}


async def main() -> None:
    order = {
        "sku": "SKU-OAT-BAR-12",
        "launch_units": 50_000,
        "retailers": ["GROCER-01", "GROCER-02", "PHARMA-07"],
    }
    logger.info("=== Launch that ships ===")
    await ProductLaunchSaga().run(dict(order))

    logger.info("=== Launch whose carrier booking fails: everything before it is undone ===")
    try:
        await ProductLaunchSaga().run({**order, "fail_at": "book_distribution"})
    except RuntimeError as e:
        logger.info(f"Launch rolled back: {e}")


if __name__ == "__main__":
    asyncio.run(main())
