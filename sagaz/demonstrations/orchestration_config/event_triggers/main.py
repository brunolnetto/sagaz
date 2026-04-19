#!/usr/bin/env python3
"""
Event Triggers — fire events to start sagas automatically

Demonstrates the trigger ecosystem:
  1. @trigger decorator to register saga methods as event handlers
  2. fire_event() to dispatch events programmatically
  3. TriggerEngine routing events to the correct saga class
  4. Idempotency keys to prevent duplicate saga execution

Requires minimal config (SagaConfig with in-memory storage).
No external infrastructure required.

Usage:
    sagaz demo run event_triggers
    python -m sagaz.demonstrations.event_triggers.main
"""

import asyncio
import logging

from sagaz import Saga, SagaConfig, action, compensate, configure
from sagaz.core.triggers.decorators import trigger
from sagaz.core.triggers.engine import fire_event
from sagaz.core.triggers.registry import TriggerRegistry

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.event_triggers")


# ============================================================================
# Saga with @trigger-decorated handler
# ============================================================================


class OrderSaga(Saga):
    """Saga that is automatically triggered by 'webhook' events."""

    saga_name = "triggered-order"

    @trigger(source="webhook", idempotency_key="order_id")
    def on_order_created(self, event: dict) -> dict:
        """Transform incoming webhook payload into saga context."""
        return {
            "order_id": event["order_id"],
            "customer": event.get("customer", "unknown"),
            "amount": event.get("amount", 0),
        }

    @action("validate")
    async def validate(self, ctx: dict) -> dict:
        logger.info(f"  ✓ Validating order {ctx.get('order_id')}")
        await asyncio.sleep(0.02)
        return {"validated": True}

    @compensate("validate")
    async def undo_validate(self, ctx: dict) -> None:
        logger.info(f"  ↩ Undoing validation for {ctx.get('order_id')}")

    @action("process", depends_on=["validate"])
    async def process(self, ctx: dict) -> dict:
        logger.info(f"  ✓ Processing order {ctx.get('order_id')} — ${ctx.get('amount', 0):.2f}")
        await asyncio.sleep(0.02)
        return {"processed": True}

    @compensate("process")
    async def undo_process(self, ctx: dict) -> None:
        logger.info(f"  ↩ Undoing processing for {ctx.get('order_id')}")


class NotificationSaga(Saga):
    """A second saga triggered by the same 'webhook' source."""

    saga_name = "triggered-notification"

    @trigger(source="webhook")
    def on_webhook(self, event: dict) -> dict | None:
        # Only trigger if event has a notify flag
        if not event.get("notify"):
            return None
        return {"order_id": event["order_id"], "channel": "email"}

    @action("send_notification")
    async def send(self, ctx: dict) -> dict:
        logger.info(f"  ✓ Sending {ctx.get('channel')} notification for {ctx.get('order_id')}")
        await asyncio.sleep(0.02)
        return {"sent": True}

    @compensate("send_notification")
    async def unsend(self, ctx: dict) -> None:
        logger.info("  ↩ Cancelling notification")


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    # Configure sagaz with in-memory storage
    configure(SagaConfig())

    # Show registered triggers
    registry = TriggerRegistry.get_all()
    print("\n" + "=" * 60)
    print("Registered triggers")
    print("=" * 60)
    for source, triggers in registry.items():
        for t in triggers:
            print(f"  source={source}  → {t.saga_class.__name__}.{t.method_name}")

    # --- Phase 1: Fire webhook event → triggers OrderSaga + NotificationSaga --
    print("\n" + "=" * 60)
    print("Phase 1 — Fire webhook event (triggers OrderSaga + NotificationSaga)")
    print("=" * 60)

    saga_ids = await fire_event("webhook", {
        "order_id": "ORD-100",
        "customer": "Alice",
        "amount": 59.99,
        "notify": True,
    })
    print(f"\n  Saga IDs started: {saga_ids}")

    # Allow background tasks to complete
    await asyncio.sleep(0.5)

    # --- Phase 2: Fire same event again → idempotent (OrderSaga skipped) -----
    print("\n" + "=" * 60)
    print("Phase 2 — Fire duplicate event (OrderSaga skipped via idempotency)")
    print("=" * 60)

    saga_ids_2 = await fire_event("webhook", {
        "order_id": "ORD-100",
        "customer": "Alice",
        "amount": 59.99,
        "notify": True,
    })
    print(f"\n  Saga IDs returned: {saga_ids_2}")
    print("  (OrderSaga reuses existing ID; NotificationSaga has no idempotency key)")

    await asyncio.sleep(0.3)

    # --- Phase 3: Fire event that only triggers OrderSaga --------------------
    print("\n" + "=" * 60)
    print("Phase 3 — Fire event without notify flag (only OrderSaga triggers)")
    print("=" * 60)

    saga_ids_3 = await fire_event("webhook", {
        "order_id": "ORD-200",
        "customer": "Bob",
        "amount": 120.00,
    })
    print(f"\n  Saga IDs started: {saga_ids_3}")

    await asyncio.sleep(0.3)

    # --- Phase 4: Fire to unknown source → nothing happens -------------------
    print("\n" + "=" * 60)
    print("Phase 4 — Fire to unregistered source (no sagas triggered)")
    print("=" * 60)

    saga_ids_4 = await fire_event("unknown_source", {"data": "ignored"})
    print(f"\n  Saga IDs started: {saga_ids_4}  (empty — no triggers for this source)")

    # Clean up registry to avoid polluting other demos
    TriggerRegistry.clear()

    print("\n" + "=" * 60)
    print("Done — event triggers demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
