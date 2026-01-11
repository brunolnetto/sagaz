#!/usr/bin/env python3
"""
Test script to demonstrate idempotency key enforcement.
"""

import asyncio

from sagaz import Saga, action, compensate
from sagaz.core.exceptions import IdempotencyKeyRequiredError
from sagaz.triggers import fire_event, trigger


class PaymentSagaWithoutIdempotency(Saga):
    """Example saga that will fail due to missing idempotency key."""

    saga_name = "payment-saga"

    @trigger(source="payment_requested")  # Missing idempotency_key!
    def on_payment(self, event: dict) -> dict:
        return {
            "order_id": event["order_id"],
            "amount": event["amount"],  # High-value field
        }

    @action("process_payment")
    async def process_payment(self, ctx: dict) -> dict:
        print(f"Processing payment of ${ctx['amount']} for order {ctx['order_id']}")
        return {"transaction_id": "TXN-001"}

    @compensate("process_payment")
    async def refund_payment(self, ctx: dict) -> None:
        print(f"Refunding payment for order {ctx['order_id']}")


class PaymentSagaWithIdempotency(Saga):
    """Example saga with proper idempotency key configured."""

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


async def main():
    print("=" * 70)
    print("IDEMPOTENCY KEY ENFORCEMENT DEMONSTRATION")
    print("=" * 70)

    # Test 1: Without idempotency key (should fail)
    print("\n" + "=" * 70)
    print("TEST 1: High-value operation WITHOUT idempotency_key")
    print("=" * 70)
    try:
        await fire_event(
            "payment_requested", {"order_id": "ORD-001", "amount": 150.0}
        )
        print("❌ UNEXPECTED: Should have raised IdempotencyKeyRequiredError!")
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
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
