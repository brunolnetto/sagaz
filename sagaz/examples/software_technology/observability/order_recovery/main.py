#!/usr/bin/env python3
"""Order Processing Recovery - Replay failed saga from checkpoint"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import (
    ReplayConfig,
    Saga,
    SagaConfig,
    SagaFailedError,
    SagaStepError,
    SnapshotStrategy,
    action,
    compensate,
)
from sagaz.core.decorators._snapshots import snapshot_saga_id
from sagaz.core.replay.saga_replay import SagaReplay
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class OrderSaga(Saga):
    """Order processing saga with potential payment failure."""

    saga_name = "order-processing"

    @action("reserve_inventory")
    async def reserve_inventory(self, ctx: dict[str, Any]) -> dict:
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

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: dict[str, Any]) -> None:
        """Release reserved inventory."""
        order_id = ctx.get("order_id")
        reservations = ctx.get("reservations", [])  # the step's result is in the context

        logger.warning(f"[ORDER {order_id}] ✗ Releasing {len(reservations)} reservations")
        await asyncio.sleep(0.1)

    @action("process_payment", depends_on=["reserve_inventory"], max_retries=0)
    async def process_payment(self, ctx: dict[str, Any]) -> dict:
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

    @compensate("process_payment")
    async def refund_payment(self, ctx: dict[str, Any]) -> None:
        """Refund payment."""
        order_id = ctx.get("order_id")
        transaction_id = ctx.get("transaction_id")

        if transaction_id:
            logger.warning(f"[ORDER {order_id}] ✗ Refunding payment {transaction_id}")
            await asyncio.sleep(0.1)

    @action("ship_order", depends_on=["process_payment"])
    async def ship_order(self, ctx: dict[str, Any]) -> dict:
        """Ship order to customer."""
        order_id = ctx.get("order_id")

        logger.info(f"[ORDER {order_id}] Shipping order")
        await asyncio.sleep(0.1)

        tracking_number = f"TRACK-{order_id}-{datetime.now().timestamp()}"
        logger.info(f"[ORDER {order_id}] ✓ Shipped: {tracking_number}")

        return {"tracking_number": tracking_number}

    @compensate("ship_order")
    async def cancel_shipment(self, ctx: dict[str, Any]) -> None:
        """Cancel shipment."""
        order_id = ctx.get("order_id")
        tracking_number = ctx.get("tracking_number")

        if tracking_number:
            logger.warning(f"[ORDER {order_id}] ✗ Cancelling shipment {tracking_number}")
            await asyncio.sleep(0.1)


async def main() -> None:
    """Demonstrate saga replay from checkpoint."""

    # Setup snapshot storage
    snapshot_storage = InMemorySnapshotStorage()

    # A snapshot before each step, kept for 30 days
    config = SagaConfig(
        replay_config=ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
            retention_days=30,
        ),
        snapshot_storage=snapshot_storage,
        metrics=False,
        logging=False,
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

    failed_saga_id = "order-ORD-12345"

    try:
        await OrderSaga(config=config).run(order_context, saga_id=failed_saga_id)
    except SagaFailedError as failure:
        logger.info(f"Saga failed at {failure.failed_step!r}: {failure.status.value}")

    # ========================================================================
    # PHASE 2: Inspect available checkpoints
    # ========================================================================

    snapshots = await snapshot_storage.list_snapshots(saga_id=snapshot_saga_id(failed_saga_id))

    for snapshot in sorted(snapshots, key=lambda s: s.step_index):
        logger.info(f"Checkpoint before {snapshot.step_name}: done={snapshot.completed_steps}")

    # ========================================================================
    # PHASE 3: Replay from checkpoint with corrected data
    # ========================================================================

    # Create replay instance
    replay = SagaReplay(
        saga_id=failed_saga_id,
        snapshot_storage=snapshot_storage,
        initiated_by="admin@example.com",
        saga_factory=lambda saga_name: OrderSaga(config=config),
    )

    # Replay from the payment step with the corrected gateway. A replay adopts the steps
    # its snapshot completed (here reserve_inventory) without running them again. The
    # failed run released that reservation when it compensated, so in a real system
    # replay from "reserve_inventory" instead, unless the reservation still holds.
    result = await replay.from_checkpoint(
        step_name="process_payment",
        context_override={
            "payment_gateway": "backup"  # Use backup gateway
        },
    )

    # ========================================================================
    # PHASE 4: Verify final state
    # ========================================================================

    logger.info(f"Replay {result.replay_status.value}: new saga {result.new_saga_id}")


if __name__ == "__main__":
    asyncio.run(main())
