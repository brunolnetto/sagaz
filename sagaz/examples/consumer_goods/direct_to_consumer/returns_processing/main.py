"""
Returns Processing Saga Example (Consumer Goods)

A consumer sends a product back. The brand authorizes the return, receives and
inspects the parcel, then restocks or disposes of the item before refunding.
If the inspection finds the return is not eligible (wrong item, used beyond
the policy), the authorization is voided and the stock adjustment reversed.

Pivot Step: issue_refund
    Money returned to the consumer is not clawed back; once the refund is
    issued, the inventory decision before it stands.

Run it:
    python -m sagaz.examples.consumer_goods.direct_to_consumer.returns_processing.main
"""

import asyncio
import logging
import uuid
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.core.exceptions import SagaFailedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ReturnsProcessingSaga(Saga):
    """Authorize, receive, inspect, restock or dispose, refund."""

    saga_name = "returns-processing"

    @action("authorize_return")
    async def authorize_return(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"📝 [{ctx.get('order_id')}] Issuing a return authorization...")
        await asyncio.sleep(0.05)
        return {"rma": f"RMA-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("authorize_return")
    async def void_return(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Voiding {ctx.get('rma')}")
        await asyncio.sleep(0.05)

    @action("receive_parcel", depends_on=["authorize_return"])
    async def receive_parcel(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"📬 [{ctx.get('order_id')}] Parcel received at the returns center")
        await asyncio.sleep(0.05)
        return {"received": True}

    @action("inspect_item", depends_on=["receive_parcel"])
    async def inspect_item(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🔍 [{ctx.get('order_id')}] Inspecting {ctx.get('sku')}...")
        await asyncio.sleep(0.1)
        condition = ctx.get("condition", "sealed")
        if condition == "not_ours":
            msg = "the parcel holds a different product"
            raise RuntimeError(msg)
        return {"disposition": "restock" if condition == "sealed" else "dispose"}

    @action("adjust_inventory", depends_on=["inspect_item"])
    async def adjust_inventory(self, ctx: SagaContext) -> dict[str, Any]:
        disposition = ctx.get("disposition")
        verb = "Restocking" if disposition == "restock" else "Writing off"
        logger.info(f"🏷️ [{ctx.get('order_id')}] {verb} {ctx.get('sku')}")
        await asyncio.sleep(0.05)
        return {"adjustment": f"ADJ-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("adjust_inventory")
    async def reverse_adjustment(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Reversing {ctx.get('adjustment')}")
        await asyncio.sleep(0.05)

    @action("issue_refund", depends_on=["adjust_inventory"], pivot=True)
    async def issue_refund(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT: money goes back to the consumer."""
        logger.info(f"🔒 [{ctx.get('order_id')}] PIVOT: refunding ${ctx.get('amount')}")
        await asyncio.sleep(0.05)
        return {"refund_id": f"RF-{uuid.uuid4().hex[:8].upper()}"}

    @action("close_return", depends_on=["issue_refund"])
    async def close_return(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"✅ [{ctx.get('order_id')}] Closing {ctx.get('rma')}")
        await asyncio.sleep(0.05)
        return {"closed": True}


async def main() -> None:
    parcel = {"order_id": "ORD-88213", "sku": "SKU-BLENDER-2", "amount": "89.00"}
    logger.info("=== A sealed return is restocked and refunded ===")
    await ReturnsProcessingSaga().run({**parcel, "condition": "sealed"})

    logger.info("=== The parcel holds another product: the authorization is voided ===")
    try:
        await ReturnsProcessingSaga().run({**parcel, "condition": "not_ours"})
    except SagaFailedError as e:
        logger.info(f"Return refused: {e}")


if __name__ == "__main__":
    asyncio.run(main())
