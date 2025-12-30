"""
E-commerce Order Processing Saga Example

Demonstrates the declarative saga pattern with @action and @compensate decorators.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class OrderProcessingSaga(Saga):
    """E-commerce order processing with inventory, payment, and shipping."""
    
    saga_name = "order-processing"

    def __init__(self, order_id: str, user_id: str, items: list[dict], total_amount: float):
        super().__init__()
        self.order_id = order_id
        self.user_id = user_id
        self.items = items
        self.total_amount = total_amount

    @action("reserve_inventory")
    async def reserve_inventory(self, ctx: SagaContext) -> dict[str, Any]:
        """Reserve inventory for all items."""
        logger.info(f"Reserving inventory for order {self.order_id}")
        await asyncio.sleep(0.1)

        reserved_items = []
        for item in self.items:
            if item["quantity"] > 100:
                raise SagaStepError(f"Insufficient inventory for {item['id']}")
            reserved_items.append({
                "item_id": item["id"],
                "quantity": item["quantity"],
                "reservation_id": f"RES-{item['id']}",
            })

        return {"reservations": reserved_items, "timestamp": datetime.now().isoformat()}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: SagaContext) -> None:
        """Release reserved inventory."""
        logger.warning(f"Releasing inventory for order {self.order_id}")
        await asyncio.sleep(0.1)

    @action("process_payment", depends_on=["reserve_inventory"])
    async def process_payment(self, ctx: SagaContext) -> dict[str, Any]:
        """Process payment."""
        logger.info(f"Processing payment of ${self.total_amount}")
        await asyncio.sleep(0.2)

        if self.total_amount > 10000:
            raise SagaStepError(f"Payment declined: ${self.total_amount} exceeds limit")

        return {
            "transaction_id": f"TXN-{self.order_id}",
            "amount": self.total_amount,
            "status": "completed",
        }

    @compensate("process_payment")
    async def refund_payment(self, ctx: SagaContext) -> None:
        """Refund payment."""
        logger.warning(f"Refunding payment for order {self.order_id}")
        await asyncio.sleep(0.2)

    @action("create_shipment", depends_on=["process_payment"])
    async def create_shipment(self, ctx: SagaContext) -> dict[str, Any]:
        """Create shipment."""
        logger.info(f"Creating shipment for order {self.order_id}")
        await asyncio.sleep(0.15)

        return {
            "shipment_id": f"SHIP-{self.order_id}",
            "tracking_number": f"TRACK-{self.order_id}",
            "carrier": "FastShip",
        }

    @compensate("create_shipment")
    async def cancel_shipment(self, ctx: SagaContext) -> None:
        """Cancel shipment."""
        logger.warning(f"Canceling shipment for order {self.order_id}")
        await asyncio.sleep(0.1)

    @action("send_confirmation", depends_on=["create_shipment"])
    async def send_confirmation(self, ctx: SagaContext) -> dict[str, Any]:
        """Send confirmation email (idempotent - no compensation needed)."""
        logger.info(f"Sending confirmation for order {self.order_id}")
        await asyncio.sleep(0.05)
        return {"email_sent": True, "recipient": self.user_id}


async def main():
    """Run the order processing saga demo."""
    print("=" * 60)
    print("Order Processing Saga Demo")
    print("=" * 60)

    saga = OrderProcessingSaga(
        order_id="ORD-12345",
        user_id="USER-789",
        items=[
            {"id": "ITEM-1", "name": "Laptop", "quantity": 1},
            {"id": "ITEM-2", "name": "Mouse", "quantity": 2},
        ],
        total_amount=1059.97,
    )

    result = await saga.run({"order_id": saga.order_id})

    print(f"\n{'✅' if result.get('saga_id') else '❌'} Order Processing Result:")
    print(f"   Saga ID: {result.get('saga_id')}")
    print(f"   Order ID: {result.get('order_id')}")
    

if __name__ == "__main__":
    asyncio.run(main())
