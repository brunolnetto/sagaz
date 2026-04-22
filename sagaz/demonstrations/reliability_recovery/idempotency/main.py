#!/usr/bin/env python3
"""
Idempotency Key Enforcement Demo — high-value operation protection

Demonstrates how Sagaz enforces idempotency keys on high-value
trigger events to prevent accidental duplicate executions.

Scenario:
1. Fire a payment event WITHOUT an idempotency_key → expect an error
2. Fire a payment event WITH an idempotency_key  → succeeds

Usage:
    sagaz demo run idempotency
    python -m sagaz.demonstrations.idempotency.main
"""

import asyncio

from sagaz import Saga, action, compensate
from sagaz.core.exceptions import IdempotencyKeyRequiredError
from sagaz.core.triggers import fire_event, trigger

# ============================================================================
# Saga definitions
# ============================================================================


class PaymentSagaWithoutIdempotency(Saga):
    """Payment saga that will fail due to a missing idempotency key."""

    saga_name = "payment-saga"

    @trigger(source="payment_requested")  # Missing idempotency_key!
    def on_payment(self, event: dict) -> dict:
        return {
            "order_id": event["order_id"],
            "amount": event["amount"],
        }

    @action("process_payment")
    async def process_payment(self, ctx: dict) -> dict:
        print(f"Processing payment of ${ctx['amount']} for order {ctx['order_id']}")
        return {"transaction_id": "TXN-001"}

    @compensate("process_payment")
    async def refund_payment(self, ctx: dict) -> None:
        print(f"Refunding payment for order {ctx['order_id']}")


class PaymentSagaWithIdempotency(Saga):
    """Payment saga with a proper idempotency key configured."""

    saga_name = "safe-payment"

    @trigger(source="payment_requested_safe", idempotency_key="order_id")
    def on_payment(self, event: dict) -> dict:
        return {
            "order_id": event["order_id"],
            "amount": event["amount"],
        }

    @action("process_payment")
    async def process_payment(self, ctx: dict) -> dict:
        print(f"Processing payment of ${ctx['amount']} for order {ctx['order_id']}")
        return {"transaction_id": "TXN-001"}

    @compensate("process_payment")
    async def refund_payment(self, ctx: dict) -> None:
        print(f"Refunding payment for order {ctx['order_id']}")


# ============================================================================
# Entry point
# ============================================================================


async def _run():
    """Run the idempotency key enforcement demonstration."""
    print("=" * 70)
    print("IDEMPOTENCY KEY ENFORCEMENT DEMONSTRATION")
    print("=" * 70)

    # Test 1: Without idempotency key (engine warns but continues)
    print("\n" + "=" * 70)
    print("TEST 1: High-value operation WITHOUT idempotency_key")
    print("=" * 70)
    try:
        await fire_event("payment_requested", {"order_id": "ORD-001", "amount": 150.0})
        print("⚠️  Event fired without idempotency_key (engine warns but continues)")
    except IdempotencyKeyRequiredError as e:
        print("✅ Correctly raised IdempotencyKeyRequiredError")
        print(str(e))

    # Test 2: With idempotency key (should succeed)
    print("\n" + "=" * 70)
    print("TEST 2: High-value operation WITH idempotency_key")
    print("=" * 70)
    try:
        saga_ids = await fire_event(
            "payment_requested_safe", {"order_id": "ORD-002", "amount": 250.0}
        )
        print(f"✅ Saga created successfully: {saga_ids}")
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")

    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70 + "\n")


def main():
    """Main entry point for sagaz demo run idempotency."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
