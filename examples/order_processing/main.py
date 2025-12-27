# ============================================
# EXAMPLE 1: E-COMMERCE ORDER PROCESSING
# ============================================

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz.core import Saga as ClassicSaga, SagaContext
from sagaz.exceptions import SagaStepError

logger = logging.getLogger(__name__)


class OrderProcessingSaga(ClassicSaga):
    """
    E-commerce order processing with inventory, payment, and shipping
    """

    def __init__(self, order_id: str, user_id: str, items: list[dict], total_amount: float):
        super().__init__(name=f"OrderProcessing-{order_id}", version="1.0")
        self.order_id = order_id
        self.user_id = user_id
        self.items = items
        self.total_amount = total_amount

    async def build(self):
        """Build the order processing saga"""

        # Step 1: Reserve inventory
        await self.add_step(
            name="reserve_inventory",
            action=self._reserve_inventory,
            compensation=self._release_inventory,
            timeout=15.0,
            max_retries=3,
        )

        # Step 2: Process payment
        await self.add_step(
            name="process_payment",
            action=self._process_payment,
            compensation=self._refund_payment,
            timeout=30.0,
            max_retries=2,
        )

        # Step 3: Create shipment
        await self.add_step(
            name="create_shipment",
            action=self._create_shipment,
            compensation=self._cancel_shipment,
            timeout=20.0,
            max_retries=3,
        )

        # Step 4: Send confirmation email (no compensation - idempotent)
        await self.add_step(
            name="send_confirmation",
            action=self._send_confirmation_email,
            timeout=10.0,
        )

        # Step 5: Update order status
        await self.add_step(
            name="update_order_status",
            action=self._update_order_status,
            timeout=5.0,
        )

    async def _reserve_inventory(self, ctx: SagaContext) -> dict[str, Any]:
        """Reserve inventory for all items"""
        logger.info(f"Reserving inventory for order {self.order_id}")

        # Simulate API call to inventory service
        await asyncio.sleep(0.1)

        reserved_items = []
        for item in self.items:
            # Simulate inventory failure for large quantities
            if item["quantity"] > 100:
                raise SagaStepError(
                    f"Insufficient inventory for item {item['id']}: requested {item['quantity']}, available 100"
                )

            reserved_items.append(
                {
                    "item_id": item["id"],
                    "quantity": item["quantity"],
                    "reservation_id": f"RES-{item['id']}",
                }
            )

        return {"reservations": reserved_items, "timestamp": datetime.now().isoformat()}

    async def _release_inventory(self, result: dict, ctx: SagaContext) -> None:
        """Release reserved inventory"""
        logger.warning(f"Releasing inventory for order {self.order_id}")

        # Simulate API call to release reservations
        await asyncio.sleep(0.1)

        for reservation in result["reservations"]:
            logger.info(f"Released reservation {reservation['reservation_id']}")

    async def _process_payment(self, ctx: SagaContext) -> dict[str, Any]:
        """Process payment"""
        logger.info(f"Processing payment of ${self.total_amount} for order {self.order_id}")

        # Simulate payment gateway API call
        await asyncio.sleep(0.2)

        # Simulate payment failure for large amounts (more realistic than random)
        if self.total_amount > 10000:
            raise SagaStepError(
                f"Payment declined: amount ${self.total_amount} exceeds credit limit"
            )

        payment_result = {
            "transaction_id": f"TXN-{self.order_id}",
            "amount": self.total_amount,
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
        }

        return payment_result

    async def _refund_payment(self, result: dict, ctx: SagaContext) -> None:
        """Refund payment"""
        logger.warning(f"Refunding payment {result['transaction_id']}")

        # Simulate refund API call
        await asyncio.sleep(0.2)

        logger.info(f"Refunded ${result['amount']} to user {self.user_id}")

    async def _create_shipment(self, ctx: SagaContext) -> dict[str, Any]:
        """Create shipment"""
        logger.info(f"Creating shipment for order {self.order_id}")

        # Get payment info from context
        payment_info = ctx.get("process_payment")

        # Simulate shipping service API call
        await asyncio.sleep(0.15)

        shipment = {
            "shipment_id": f"SHIP-{self.order_id}",
            "tracking_number": f"TRACK-{self.order_id}",
            "carrier": "FastShip",
            "estimated_delivery": "2024-12-15",
        }

        return shipment

    async def _cancel_shipment(self, result: dict, ctx: SagaContext) -> None:
        """Cancel shipment"""
        logger.warning(f"Canceling shipment {result['shipment_id']}")

        # Simulate shipment cancellation API call
        await asyncio.sleep(0.1)

        logger.info(f"Canceled shipment with tracking {result['tracking_number']}")

    async def _send_confirmation_email(self, ctx: SagaContext) -> dict[str, Any]:
        """Send order confirmation email"""
        logger.info(f"Sending confirmation email for order {self.order_id}")

        # Get shipment info from context
        shipment_info = ctx.get("create_shipment")

        # Simulate email service API call
        await asyncio.sleep(0.05)

        return {
            "email_sent": True,
            "recipient": self.user_id,
            "tracking_number": shipment_info["tracking_number"],
        }

    async def _update_order_status(self, ctx: SagaContext) -> dict[str, Any]:
        """Update order status to completed"""
        logger.info(f"Updating order {self.order_id} status to COMPLETED")

        # Simulate database update
        await asyncio.sleep(0.05)

        return {
            "order_id": self.order_id,
            "status": "COMPLETED",
            "updated_at": datetime.now().isoformat(),
        }


async def demo_order_processing():
    """Demo: E-commerce order processing"""
    print("\n" + "=" * 60)
    print("DEMO 1: E-Commerce Order Processing")
    print("=" * 60)

    orchestrator = MonitoredSagaOrchestrator()

    # Create order saga
    order = OrderProcessingSaga(
        order_id="ORD-12345",
        user_id="USER-789",
        items=[
            {"id": "ITEM-1", "name": "Laptop", "quantity": 1, "price": 999.99},
            {"id": "ITEM-2", "name": "Mouse", "quantity": 2, "price": 29.99},
        ],
        total_amount=1059.97,
    )

    await order.build()

    # Execute saga
    result = await orchestrator.execute_saga(order)

    # Print result
    print(f"\n✅ Order Processing Result:")
    print(f"   Success: {result.success}")
    print(f"   Status: {result.status.value}")
    print(f"   Completed Steps: {result.completed_steps}/{result.total_steps}")
    print(f"   Execution Time: {result.execution_time:.2f}s")

    if result.error:
        print(f"   Error: {result.error}")

    # Show metrics
    print(f"\n📊 Orchestrator Metrics:")
    metrics = orchestrator.get_metrics()
    for key, value in metrics.items():
        print(f"   {key}: {value}")
