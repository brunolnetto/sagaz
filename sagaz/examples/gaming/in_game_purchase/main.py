"""
In-Game Purchase Saga Example

Demonstrates payment charging as pivot point in gaming microtransactions.
Once payment is charged, virtual items are committed to the player.

Pivot Step: charge_payment
    Payment charged, cannot refund without TOS process.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class InGamePurchaseSaga(Saga):
    """In-game purchase saga with payment pivot."""

    saga_name = "in-game-purchase"

    @action("validate_cart")
    async def validate_cart(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"🛒 [{order_id}] Validating cart...")
        await asyncio.sleep(0.1)
        return {"cart_valid": True, "total_items": 3}

    @compensate("validate_cart")
    async def clear_cart(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Clearing cart...")
        await asyncio.sleep(0.05)

    @action("check_balance", depends_on=["validate_cart"])
    async def check_balance(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"💰 [{order_id}] Checking player balance...")
        await asyncio.sleep(0.1)
        return {"balance_sufficient": True, "current_balance": "50.00"}

    @compensate("check_balance")
    async def release_balance_hold(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Releasing balance hold...")
        await asyncio.sleep(0.05)

    @action("reserve_items", depends_on=["check_balance"])
    async def reserve_items(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"📦 [{order_id}] Reserving virtual items...")
        await asyncio.sleep(0.1)
        return {"items_reserved": True, "items": ["skin_rare", "emote_epic", "boost_xp"]}

    @compensate("reserve_items")
    async def release_items(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Releasing reserved items...")
        await asyncio.sleep(0.05)

    @action("charge_payment", depends_on=["reserve_items"])
    async def charge_payment(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Charge payment - items committed."""
        order_id = ctx.get("order_id")
        amount = Decimal(str(ctx.get("amount", 9.99)))
        logger.info(f"🔒 [{order_id}] PIVOT: Charging ${amount}...")
        await asyncio.sleep(0.3)
        return {
            "payment_id": f"PAY-{uuid.uuid4().hex[:8].upper()}",
            "amount_charged": str(amount),
            "pivot_reached": True,
        }

    @action("deliver_items", depends_on=["charge_payment"])
    async def deliver_items(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"🎁 [{order_id}] Delivering items to player inventory...")
        await asyncio.sleep(0.1)
        return {"items_delivered": True, "inventory_updated": True}

    @action("update_inventory", depends_on=["deliver_items"])
    async def update_inventory(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"📊 [{order_id}] Updating player inventory...")
        await asyncio.sleep(0.1)
        return {"sync_complete": True}


async def main():
    saga = InGamePurchaseSaga()
    await saga.run(
        {
            "order_id": "ORDER-2026-001",
            "player_id": "PLAYER-12345",
            "items": ["skin_rare", "emote_epic", "boost_xp"],
            "amount": Decimal("14.99"),
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
