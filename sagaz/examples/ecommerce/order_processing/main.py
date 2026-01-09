"""
E-commerce Order Processing Saga Example

Demonstrates the declarative saga pattern with @action and @compensate decorators.
Data is passed through the run() method's initial context, not the constructor.
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
    """
    E-commerce order processing with inventory, payment, and shipping.

    This saga is stateless - all order data is passed through the context
    via the run() method. The same saga instance can process multiple orders.

    Expected context:
        - order_id: str - Unique order identifier
        - user_id: str - Customer identifier
        - items: list[dict] - List of items with 'id', 'name', 'quantity'
        - total_amount: float - Total order amount
    """

    saga_name = "order-processing"

    @action("reserve_inventory")
    async def reserve_inventory(self, ctx: SagaContext) -> dict[str, Any]:
        """Reserve inventory for all items."""
        order_id = ctx.get("order_id")
        items = ctx.get("items", [])

        logger.info(f"Reserving inventory for order {order_id}")
        await asyncio.sleep(0.1)

        reserved_items = []
        for item in items:
            if item["quantity"] > 100:
                msg = f"Insufficient inventory for {item['id']}"
                raise SagaStepError(msg)
            reserved_items.append({
                "item_id": item["id"],
                "quantity": item["quantity"],
                "reservation_id": f"RES-{item['id']}",
            })

        return {"reservations": reserved_items, "timestamp": datetime.now().isoformat()}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: SagaContext) -> None:
        """Release reserved inventory using data from context."""
        order_id = ctx.get("order_id")
        logger.warning(f"Releasing inventory for order {order_id}")

        # Access the action result from context
        reservations = ctx.get("reservations", [])
        for reservation in reservations:
            logger.info(f"Releasing reservation: {reservation['reservation_id']}")

        await asyncio.sleep(0.1)

    @action("process_payment", depends_on=["reserve_inventory"])
    async def process_payment(self, ctx: SagaContext) -> dict[str, Any]:
        """Process payment."""
        order_id = ctx.get("order_id")
        total_amount = ctx.get("total_amount", 0)

        logger.info(f"Processing payment of ${total_amount}")
        await asyncio.sleep(0.2)

        if total_amount > 10000:
            msg = f"Payment declined: ${total_amount} exceeds limit"
            raise SagaStepError(msg)

        return {
            "transaction_id": f"TXN-{order_id}",
            "amount": total_amount,
            "status": "completed",
        }

    @compensate("process_payment")
    async def refund_payment(self, ctx: SagaContext) -> None:
        """Refund payment using transaction data from context."""
        order_id = ctx.get("order_id")
        logger.warning(f"Refunding payment for order {order_id}")

        # Access the payment result from context
        transaction_id = ctx.get("transaction_id")
        amount = ctx.get("amount")
        if transaction_id:
            logger.info(f"Refunding transaction {transaction_id} for ${amount}")

        await asyncio.sleep(0.2)

    @action("create_shipment", depends_on=["process_payment"])
    async def create_shipment(self, ctx: SagaContext) -> dict[str, Any]:
        """Create shipment."""
        order_id = ctx.get("order_id")

        logger.info(f"Creating shipment for order {order_id}")
        await asyncio.sleep(0.15)

        return {
            "shipment_id": f"SHIP-{order_id}",
            "tracking_number": f"TRACK-{order_id}",
            "carrier": "FastShip",
        }

    @compensate("create_shipment")
    async def cancel_shipment(self, ctx: SagaContext) -> None:
        """Cancel shipment using shipment data from context."""
        order_id = ctx.get("order_id")
        logger.warning(f"Canceling shipment for order {order_id}")

        # Access the shipment result from context
        shipment_id = ctx.get("shipment_id")
        tracking_number = ctx.get("tracking_number")
        if shipment_id:
            logger.info(f"Canceling shipment {shipment_id} with tracking {tracking_number}")

        await asyncio.sleep(0.1)

    @action("send_confirmation", depends_on=["create_shipment"])
    async def send_confirmation(self, ctx: SagaContext) -> dict[str, Any]:
        """Send confirmation email (idempotent - no compensation needed)."""
        order_id = ctx.get("order_id")
        user_id = ctx.get("user_id")

        logger.info(f"Sending confirmation for order {order_id}")
        await asyncio.sleep(0.05)
        return {"email_sent": True, "recipient": user_id}


async def main():
    """Run the order processing saga demo."""

    # Create a reusable saga instance
    saga = OrderProcessingSaga()

    # Pass order data through the run() method
    await saga.run({
        "order_id": "ORD-12345",
        "user_id": "USER-789",
        "items": [
            {"id": "ITEM-1", "name": "Laptop", "quantity": 1},
            {"id": "ITEM-2", "name": "Mouse", "quantity": 2},
        ],
        "total_amount": 1059.97,
    })


    # Demonstrate reusability - same saga, different order

    await saga.run({
        "order_id": "ORD-67890",
        "user_id": "USER-456",
        "items": [
            {"id": "ITEM-3", "name": "Keyboard", "quantity": 1},
        ],
        "total_amount": 149.99,
    })



if __name__ == "__main__":
    asyncio.run(main())
