"""
Payment Processing Saga Example

Demonstrates payment processing with provider fallback and the declarative pattern.
Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.core.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PaymentProcessingSaga(Saga):
    """
    Payment processing with multiple provider fallback.

    This saga is stateless - all payment data is passed through the context
    via the run() method. The same saga instance can process multiple payments.

    Expected context:
        - payment_id: str - Unique payment identifier
        - amount: float - Payment amount
        - providers: list[str] - List of payment providers to try (in order)
    """

    saga_name = "payment-processing"

    @action("validate_payment")
    async def validate_payment(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate payment request."""
        payment_id = ctx.get("payment_id")
        amount = ctx.get("amount", 0)

        logger.info(f"Validating payment {payment_id}")
        await asyncio.sleep(0.05)

        if amount <= 0:
            msg = "Invalid payment amount"
            raise SagaStepError(msg)

        return {"valid": True, "amount": amount}

    @action("primary_payment", depends_on=["validate_payment"])
    async def process_with_primary(self, ctx: SagaContext) -> dict[str, Any]:
        """Process payment with primary provider."""
        payment_id = ctx.get("payment_id")
        amount = ctx.get("amount", 0)
        providers = ctx.get("providers", ["DefaultProvider"])

        primary_provider = providers[0]
        logger.info(f"Processing ${amount} with {primary_provider}")

        await asyncio.sleep(0.2)

        return {
            "provider": primary_provider,
            "transaction_id": f"TXN-{primary_provider}-{payment_id}",
            "amount": amount,
            "status": "completed",
        }

    @compensate("primary_payment")
    async def refund_primary(self, ctx: SagaContext) -> None:
        """Refund payment from primary provider using transaction data from context."""
        payment_id = ctx.get("payment_id")
        logger.warning(f"Refunding payment {payment_id}")

        # Access payment result from context
        provider = ctx.get("provider")
        transaction_id = ctx.get("transaction_id")
        amount = ctx.get("amount")

        if transaction_id:
            logger.info(f"Refunding {provider} transaction {transaction_id} for ${amount}")

        await asyncio.sleep(0.2)

    @action("record_transaction", depends_on=["primary_payment"])
    async def record_transaction(self, ctx: SagaContext) -> dict[str, Any]:
        """Record transaction in database."""
        payment_id = ctx.get("payment_id")

        logger.info(f"Recording transaction for payment {payment_id}")
        await asyncio.sleep(0.05)

        return {
            "payment_id": payment_id,
            "recorded_at": datetime.now().isoformat(),
        }


async def main():
    """Run the payment processing saga demo."""

    # Create a reusable saga instance
    saga = PaymentProcessingSaga()

    # Pass payment data through the run() method
    await saga.run(
        {
            "payment_id": "PAY-12345",
            "amount": 250.00,
            "providers": ["Stripe", "PayPal", "Square"],
        }
    )

    # Demonstrate reusability - same saga, different payment

    await saga.run(
        {
            "payment_id": "PAY-67890",
            "amount": 99.99,
            "providers": ["PayPal", "Stripe"],
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
