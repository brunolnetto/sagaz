#!/usr/bin/env python3
"""Order Processing Recovery - Replay failed saga from checkpoint"""

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from sagaz.core.context import SagaContext
from sagaz.core.exceptions import SagaStepError
from sagaz.core.replay import ReplayConfig, SnapshotStrategy
from sagaz.core.saga import Saga
from sagaz.core.saga_replay import SagaReplay
from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class OrderSaga(Saga):
    """Order processing saga with potential payment failure."""

    def __init__(self, fail_at_step: str | None = None, **kwargs):
        super().__init__(name="order-processing", **kwargs)
        self.fail_at_step = fail_at_step

    async def build(self):
        await self.add_step("reserve_inventory", self.reserve_inventory, self.release_inventory)
        await self.add_step("process_payment", self.process_payment, self.refund_payment)
        await self.add_step("ship_order", self.ship_order, self.cancel_shipment)

    async def reserve_inventory(self, ctx: SagaContext) -> dict:
        """Reserve inventory for order."""
        order_id = ctx.get("order_id")
        items = ctx.get("items", [])

        logger.info(f"[ORDER {order_id}] Reserving inventory for {len(items)} items")
        await asyncio.sleep(0.1)

        reservations = [
            {
                "item_id": item["id"],
                "quantity": item["quantity"],
                "reservation_id": f"RES-{item['id']}-{datetime.now().timestamp()}",
            }
            for item in items
        ]

        logger.info(f"[ORDER {order_id}] ✓ Reserved {len(reservations)} items")
        return {"reservations": reservations}

    async def release_inventory(self, result, ctx: SagaContext) -> None:
        """Release reserved inventory."""
        order_id = ctx.get("order_id")
        reservations = result.get("reservations", []) if result else []

        logger.warning(f"[ORDER {order_id}] ✗ Releasing {len(reservations)} reservations")
        await asyncio.sleep(0.1)

    async def process_payment(self, ctx: SagaContext) -> dict:
        """Process payment - may fail on first attempt."""
        order_id = ctx.get("order_id")
        total_amount = ctx.get("total_amount", 0)
        payment_gateway = ctx.get("payment_gateway", "primary")

        logger.info(f"[ORDER {order_id}] Processing ${total_amount:.2f} via {payment_gateway}")
        await asyncio.sleep(0.1)

        # Simulate primary gateway failure
        if payment_gateway == "primary":
            logger.error(f"[ORDER {order_id}] ✗ Payment gateway timeout!")
            msg = "Payment gateway timeout - try backup gateway"
            raise SagaStepError(msg)

        # Backup gateway succeeds
        transaction_id = f"TXN-{order_id}-{datetime.now().timestamp()}"
        logger.info(f"[ORDER {order_id}] ✓ Payment successful: {transaction_id}")

        return {
            "transaction_id": transaction_id,
            "gateway": payment_gateway,
            "amount": total_amount,
        }

    async def refund_payment(self, result, ctx: SagaContext) -> None:
        """Refund payment."""
        order_id = ctx.get("order_id")
        transaction_id = result.get("transaction_id") if result else None

        if transaction_id:
            logger.warning(f"[ORDER {order_id}] ✗ Refunding payment {transaction_id}")
            await asyncio.sleep(0.1)

    async def ship_order(self, ctx: SagaContext) -> dict:
        """Ship order to customer."""
        order_id = ctx.get("order_id")

        logger.info(f"[ORDER {order_id}] Shipping order")
        await asyncio.sleep(0.1)

        tracking_number = f"TRACK-{order_id}-{datetime.now().timestamp()}"
        logger.info(f"[ORDER {order_id}] ✓ Shipped: {tracking_number}")

        return {"tracking_number": tracking_number}

    async def cancel_shipment(self, result, ctx: SagaContext) -> None:
        """Cancel shipment."""
        order_id = ctx.get("order_id")
        tracking_number = result.get("tracking_number") if result else None

        if tracking_number:
            logger.warning(f"[ORDER {order_id}] ✗ Cancelling shipment {tracking_number}")
            await asyncio.sleep(0.1)


async def main():
    """Demonstrate saga replay from checkpoint."""

    # Setup snapshot storage
    snapshot_storage = InMemorySnapshotStorage()

    # Configure replay settings
    replay_config = ReplayConfig(
        enable_snapshots=True,
        snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
        retention_days=30,
    )

    # Initial order data
    order_context = {
        "order_id": "ORD-12345",
        "user_id": "USER-789",
        "items": [
            {"id": "ITEM-001", "name": "Laptop", "quantity": 1},
            {"id": "ITEM-002", "name": "Mouse", "quantity": 2},
        ],
        "total_amount": 1250.00,
        "payment_gateway": "primary",  # This will fail
    }

    # ========================================================================
    # PHASE 1: Initial saga execution (FAILS at payment step)
    # ========================================================================

    saga = OrderSaga(replay_config=replay_config, snapshot_storage=snapshot_storage)

    # Set context data
    for key, value in order_context.items():
        saga.context.set(key, value)

    await saga.build()

    failed_saga_id = str(saga.saga_id)  # Store saga ID before execution

    try:
        await saga.execute()
    except Exception:
        pass

    # ========================================================================
    # PHASE 2: Inspect available checkpoints
    # ========================================================================

    snapshots = await snapshot_storage.list_snapshots(saga_id=UUID(failed_saga_id))

    for _i, _snapshot in enumerate(snapshots, 1):
        pass

    # ========================================================================
    # PHASE 3: Replay from checkpoint with corrected data
    # ========================================================================

    # Create replay instance
    replay = SagaReplay(
        saga_id=UUID(failed_saga_id),
        snapshot_storage=snapshot_storage,
        initiated_by="admin@example.com",
        saga_factory=lambda saga_name: OrderSaga(
            replay_config=replay_config, snapshot_storage=snapshot_storage
        ),
    )

    # Replay from payment step with corrected gateway
    await replay.from_checkpoint(
        step_name="process_payment",
        context_override={
            "payment_gateway": "backup"  # Use backup gateway
        },
    )

    # ========================================================================
    # PHASE 4: Verify final state
    # ========================================================================


if __name__ == "__main__":
    asyncio.run(main())
