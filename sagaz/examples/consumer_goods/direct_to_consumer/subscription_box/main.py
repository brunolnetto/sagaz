"""
Subscription Box Saga Example (Consumer Goods)

A brand ships a monthly box straight to its subscribers. Each cycle reserves
the box's items, charges the subscriber, then picks and packs the box. If a
step fails before the carrier takes the parcel, the charge is refunded and the
items go back to stock.

Pivot Step: hand_to_carrier
    Once the carrier scans the parcel, the box is on its way; a problem after
    that is a delivery issue (reship or refund), not a rollback.

Run it:
    python -m sagaz.examples.consumer_goods.direct_to_consumer.subscription_box.main
"""

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.core.exceptions import SagaFailedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class SubscriptionBoxSaga(Saga):
    """One subscription cycle: reserve, charge, pack, ship, notify."""

    saga_name = "subscription-box"

    @action("check_subscription")
    async def check_subscription(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🔁 [{ctx.get('subscriber_id')}] Checking the subscription is active...")
        await asyncio.sleep(0.05)
        return {"plan": ctx.get("plan", "monthly-snacks"), "price": "29.90"}

    @action("reserve_box_items", depends_on=["check_subscription"])
    async def reserve_box_items(self, ctx: SagaContext) -> dict[str, Any]:
        items = ctx.get("box_items", [])
        logger.info(f"📦 [{ctx.get('subscriber_id')}] Reserving {len(items)} items for the box...")
        await asyncio.sleep(0.1)
        return {"reservation": f"RSV-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("reserve_box_items")
    async def release_box_items(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('subscriber_id')}] Releasing {ctx.get('reservation')}")
        await asyncio.sleep(0.05)

    @action("charge_subscriber", depends_on=["check_subscription"])
    async def charge_subscriber(self, ctx: SagaContext) -> dict[str, Any]:
        price = Decimal(ctx.get("price", "0"))
        logger.info(f"💳 [{ctx.get('subscriber_id')}] Charging ${price} to the card on file...")
        await asyncio.sleep(0.1)
        return {"charge_id": f"CH-{uuid.uuid4().hex[:8].upper()}"}

    @compensate("charge_subscriber")
    async def refund_subscriber(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('subscriber_id')}] Refunding {ctx.get('charge_id')}")
        await asyncio.sleep(0.05)

    @action("pick_and_pack", depends_on=["reserve_box_items", "charge_subscriber"])
    async def pick_and_pack(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🧺 [{ctx.get('subscriber_id')}] Picking and packing the box...")
        await asyncio.sleep(0.1)
        missing = ctx.get("missing_item")
        if missing:
            msg = f"{missing} is not on the shelf"
            raise RuntimeError(msg)
        return {"parcel_id": f"PCL-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("pick_and_pack")
    async def unpack_box(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('subscriber_id')}] Unpacking {ctx.get('parcel_id')}")
        await asyncio.sleep(0.05)

    @action("hand_to_carrier", depends_on=["pick_and_pack"], pivot=True)
    async def hand_to_carrier(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT: the carrier scans the parcel."""
        logger.info(f"🔒 [{ctx.get('subscriber_id')}] PIVOT: {ctx.get('parcel_id')} handed over")
        await asyncio.sleep(0.05)
        return {"tracking": f"1Z{uuid.uuid4().hex[:10].upper()}"}

    @action("send_tracking", depends_on=["hand_to_carrier"])
    async def send_tracking(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"✉️ [{ctx.get('subscriber_id')}] Emailing tracking {ctx.get('tracking')}")
        await asyncio.sleep(0.05)
        return {"notified": True}


async def main() -> None:
    cycle = {"subscriber_id": "SUB-4410", "box_items": ["granola", "trail-mix", "oat-bar"]}
    logger.info("=== A box that ships ===")
    await SubscriptionBoxSaga().run(dict(cycle))

    logger.info("=== An item is missing: the charge is refunded and the items released ===")
    try:
        await SubscriptionBoxSaga().run({**cycle, "missing_item": "trail-mix"})
    except SagaFailedError as e:
        logger.info(f"Cycle rolled back: {e}")


if __name__ == "__main__":
    asyncio.run(main())
