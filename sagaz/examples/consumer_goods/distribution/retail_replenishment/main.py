"""
Retail Replenishment Saga Example (Consumer Goods)

Vendor-managed inventory: the manufacturer watches a retailer's stock and
replenishes it. The order runs through EDI documents: the retailer's purchase
order acknowledgment (855), the advance ship notice (856) and the invoice (810).

Pivot Step: dispatch_truck
    Once the truck leaves, the goods are in transit to the retailer; before
    that, the stock reservation, the acknowledgment, the carrier and the ASN
    are all withdrawn if a step fails.

Run it:
    python -m sagaz.examples.consumer_goods.distribution.retail_replenishment.main
"""

import asyncio
import logging
import uuid
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.core.exceptions import SagaFailedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class RetailReplenishmentSaga(Saga):
    """Replenish a retailer's distribution center from the manufacturer's stock."""

    saga_name = "retail-replenishment"

    @action("forecast_demand")
    async def forecast_demand(self, ctx: SagaContext) -> dict[str, Any]:
        store = ctx.get("retailer_dc")
        logger.info(f"📈 [{store}] Forecasting two weeks of sell-through...")
        await asyncio.sleep(0.1)
        return {"order_cases": max(0, ctx.get("target_cases", 1200) - ctx.get("on_hand", 300))}

    @action("reserve_stock", depends_on=["forecast_demand"])
    async def reserve_stock(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🏬 Reserving {ctx.get('order_cases')} cases in the plant warehouse...")
        await asyncio.sleep(0.1)
        return {"reservation": f"RSV-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("reserve_stock")
    async def release_stock(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ Releasing reservation {ctx.get('reservation')}")
        await asyncio.sleep(0.05)

    @action("acknowledge_po", depends_on=["forecast_demand"])
    async def acknowledge_po(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"📨 Sending the PO acknowledgment (EDI 855) to {ctx.get('retailer_dc')}")
        await asyncio.sleep(0.1)
        return {"po_number": f"PO-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("acknowledge_po")
    async def reject_po(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ Sending a PO change (EDI 865) cancelling {ctx.get('po_number')}")
        await asyncio.sleep(0.05)

    @action("book_carrier", depends_on=["reserve_stock", "acknowledge_po"])
    async def book_carrier(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info("🚛 Booking a full truckload...")
        await asyncio.sleep(0.1)
        if ctx.get("no_carrier"):
            msg = "no carrier capacity for the delivery window"
            raise RuntimeError(msg)
        return {"load_id": f"LOAD-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("book_carrier")
    async def cancel_carrier(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ Cancelling load {ctx.get('load_id')}")
        await asyncio.sleep(0.05)

    @action("send_ship_notice", depends_on=["book_carrier"])
    async def send_ship_notice(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info("📄 Sending the advance ship notice (EDI 856)...")
        await asyncio.sleep(0.1)
        return {"asn": f"ASN-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("send_ship_notice")
    async def cancel_ship_notice(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ Cancelling ASN {ctx.get('asn')}")
        await asyncio.sleep(0.05)

    @action("dispatch_truck", depends_on=["send_ship_notice"], pivot=True)
    async def dispatch_truck(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT: the goods are in transit."""
        logger.info(f"🔒 PIVOT: load {ctx.get('load_id')} leaves for {ctx.get('retailer_dc')}")
        await asyncio.sleep(0.1)
        return {"dispatched": True}

    @action("invoice_retailer", depends_on=["dispatch_truck"])
    async def invoice_retailer(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🧾 Invoicing {ctx.get('po_number')} (EDI 810)")
        await asyncio.sleep(0.05)
        return {"invoice": f"INV-{uuid.uuid4().hex[:6].upper()}"}


async def main() -> None:
    order = {"retailer_dc": "DC-ATL-04", "target_cases": 1200, "on_hand": 300}
    logger.info("=== Replenishment that ships ===")
    await RetailReplenishmentSaga().run(dict(order))

    logger.info("=== No carrier capacity: the PO and the stock are released ===")
    try:
        await RetailReplenishmentSaga().run({**order, "no_carrier": True})
    except SagaFailedError as e:
        logger.info(f"Replenishment rolled back: {e}")


if __name__ == "__main__":
    asyncio.run(main())
