#!/usr/bin/env python3
"""
Basic Saga Pattern — hello-world entry point

Demonstrates the simplest possible saga with three steps, each with
its own compensation.  First runs a success path, then deliberately
triggers a failure to show the automatic compensation chain in action.

No external infrastructure required — runs fully in-memory.

Usage:
    sagaz demo run basic_saga
    python -m sagaz.demonstrations.basic_saga.main
"""

import asyncio
import logging

from sagaz import Saga, action, compensate

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.basic_saga")


# ============================================================================
# 1. Declarative saga — success path
# ============================================================================


class OrderSaga(Saga):
    """
    Three-step order saga: validate → process → notify.

    Each step returns data merged into the context so that downstream
    steps (and compensations) can access it.
    """

    saga_name = "order-processing"

    @action("validate_order")
    async def validate_order(self, ctx: dict) -> dict:
        order_id = ctx.get("order_id", "ORD-001")
        logger.info(f"  ✓ Validating order {order_id}")
        await asyncio.sleep(0.05)
        return {"validated": True, "order_id": order_id}

    @compensate("validate_order")
    async def undo_validate(self, ctx: dict) -> None:
        logger.info(f"  ↩ Rolling back validation for {ctx.get('order_id')}")

    @action("process_payment", depends_on=["validate_order"])
    async def process_payment(self, ctx: dict) -> dict:
        amount = ctx.get("amount", 99.99)
        logger.info(f"  ✓ Processing payment of ${amount:.2f}")
        await asyncio.sleep(0.05)
        return {"payment_id": "PAY-42", "charged": amount}

    @compensate("process_payment")
    async def refund_payment(self, ctx: dict) -> None:
        logger.info(f"  ↩ Refunding payment {ctx.get('payment_id')}")

    @action("send_notification", depends_on=["process_payment"])
    async def send_notification(self, ctx: dict) -> dict:
        logger.info(f"  ✓ Sending confirmation for order {ctx.get('order_id')}")
        await asyncio.sleep(0.02)
        return {"notified": True}

    @compensate("send_notification")
    async def cancel_notification(self, ctx: dict) -> None:
        logger.info(f"  ↩ Cancelling notification for {ctx.get('order_id')}")


# ============================================================================
# 2. Declarative saga — failure path (step 3 always fails)
# ============================================================================


class FailingOrderSaga(Saga):
    """Same flow but the notification step deliberately raises."""

    saga_name = "failing-order"

    @action("validate_order")
    async def validate_order(self, ctx: dict) -> dict:
        logger.info(f"  ✓ Validating order {ctx.get('order_id', 'ORD-002')}")
        await asyncio.sleep(0.02)
        return {"validated": True, "order_id": ctx.get("order_id", "ORD-002")}

    @compensate("validate_order")
    async def undo_validate(self, ctx: dict) -> None:
        logger.info(f"  ↩ Rolling back validation for {ctx.get('order_id')}")

    @action("process_payment", depends_on=["validate_order"])
    async def process_payment(self, ctx: dict) -> dict:
        logger.info("  ✓ Processing payment of $49.99")
        await asyncio.sleep(0.02)
        return {"payment_id": "PAY-99", "charged": 49.99}

    @compensate("process_payment")
    async def refund_payment(self, ctx: dict) -> None:
        logger.info(f"  ↩ Refunding payment {ctx.get('payment_id')}")

    @action("send_notification", depends_on=["process_payment"])
    async def send_notification(self, ctx: dict) -> dict:
        msg = "Email service unavailable!"
        raise RuntimeError(msg)

    @compensate("send_notification")
    async def cancel_notification(self, ctx: dict) -> None:
        logger.info("  ↩ Cancelling notification (nothing to cancel)")


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    # --- Phase 1: Success ---------------------------------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — Successful saga execution")
    print("=" * 60)

    saga = OrderSaga()
    result = await saga.run({"order_id": "ORD-001", "amount": 99.99})

    print(f"\n  Final context keys: {sorted(result.keys())}")
    print(f"  Payment ID:         {result.get('payment_id')}")
    print(f"  Notified:           {result.get('notified')}")

    # --- Phase 2: Failure with automatic compensation ------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — Saga failure with automatic compensation")
    print("=" * 60)

    failing_saga = FailingOrderSaga()
    try:
        await failing_saga.run({"order_id": "ORD-002", "amount": 49.99})
    except Exception as exc:
        print(f"\n  Saga raised: {type(exc).__name__}: {exc}")
        print("  All completed steps were compensated automatically.")

    print("\n" + "=" * 60)
    print("Done — basic saga demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
