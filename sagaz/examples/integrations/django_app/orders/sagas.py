"""
Order processing saga for Django example.

Demonstrates the declarative saga pattern with event-driven triggers.
"""

import asyncio
from typing import Any

from sagaz import Saga, action, compensate
from sagaz.triggers import trigger


class OrderSaga(Saga):
    """
    E-commerce order processing saga.

    Can be triggered via:
    - Direct API call (POST /orders/)
    - Webhook event (POST /webhooks/order_created/)
    - Programmatic fire_event("order_created", {...})
    """

    saga_name = "django-order"

    # =========================================================================
    # TRIGGER: Webhook/Event Handler
    # =========================================================================

    @trigger(
        source="order_created",  # Matches POST /webhooks/order_created
        idempotency_key="order_id",  # Prevents duplicate processing
        max_concurrent=5  # Limit concurrent orders
    )
    def on_order_created(self, event: dict) -> dict | None:
        """
        Transform webhook event into saga context.

        Return a dict to start the saga, or None to skip.
        """
        if not event.get("order_id"):
            return None

        return {
            "order_id": event["order_id"],
            "user_id": event.get("user_id", "unknown"),
            "items": event.get("items", []),
            "amount": float(event.get("amount", 0)),
        }

    @action("reserve_inventory")
    async def reserve_inventory(self, ctx: dict) -> dict[str, Any]:
        """Reserve inventory for items."""
        order_id = ctx.get("order_id")
        await asyncio.sleep(0.1)
        return {"reservation_id": f"RES-{order_id}"}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: dict) -> None:
        """Release reserved inventory."""
        ctx.get("reservation_id")
        await asyncio.sleep(0.05)

    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx: dict) -> dict[str, Any]:
        """Charge customer payment."""
        order_id = ctx.get("order_id")
        amount = ctx.get("amount", 0)
        await asyncio.sleep(0.2)

        if amount > 1000:
            msg = f"Payment declined: ${amount} exceeds limit"
            raise ValueError(msg)

        return {"transaction_id": f"TXN-{order_id}"}

    @compensate("charge_payment")
    async def refund_payment(self, ctx: dict) -> None:
        """Refund customer payment."""
        ctx.get("transaction_id")
        await asyncio.sleep(0.1)

    @action("ship_order", depends_on=["charge_payment"])
    async def ship_order(self, ctx: dict) -> dict[str, Any]:
        """Create shipment."""
        order_id = ctx.get("order_id")
        await asyncio.sleep(0.1)
        return {"shipment_id": f"SHIP-{order_id}", "tracking": f"TRACK-{order_id}"}
