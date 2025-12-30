"""
Payment Processing Saga Example

Demonstrates payment processing with provider fallback and the declarative pattern.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import Saga, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PaymentProcessingSaga(Saga):
    """Payment processing with multiple provider fallback."""
    
    saga_name = "payment-processing"

    def __init__(self, payment_id: str, amount: float, providers: list[str]):
        super().__init__()
        self.payment_id = payment_id
        self.amount = amount
        self.providers = providers

    @action("validate_payment")
    async def validate_payment(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Validate payment request."""
        logger.info(f"Validating payment {self.payment_id}")
        await asyncio.sleep(0.05)

        if self.amount <= 0:
            raise SagaStepError("Invalid payment amount")

        return {"valid": True, "amount": self.amount}

    @action("primary_payment", depends_on=["validate_payment"])
    async def process_with_primary(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Process payment with primary provider."""
        primary_provider = self.providers[0]
        logger.info(f"Processing ${self.amount} with {primary_provider}")

        await asyncio.sleep(0.2)

        return {
            "provider": primary_provider,
            "transaction_id": f"TXN-{primary_provider}-{self.payment_id}",
            "amount": self.amount,
            "status": "completed",
        }

    @compensate("primary_payment")
    async def refund_primary(self, ctx: dict[str, Any]) -> None:
        """Refund payment from primary provider."""
        logger.warning(f"Refunding payment {self.payment_id}")
        await asyncio.sleep(0.2)

    @action("record_transaction", depends_on=["primary_payment"])
    async def record_transaction(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Record transaction in database."""
        logger.info(f"Recording transaction for payment {self.payment_id}")
        await asyncio.sleep(0.05)

        return {
            "payment_id": self.payment_id,
            "recorded_at": datetime.now().isoformat(),
        }


async def main():
    """Run the payment processing saga demo."""
    print("=" * 60)
    print("Payment Processing Saga Demo")
    print("=" * 60)

    saga = PaymentProcessingSaga(
        payment_id="PAY-12345",
        amount=250.00,
        providers=["Stripe", "PayPal", "Square"],
    )

    result = await saga.run({"payment_id": saga.payment_id})

    print(f"\n{'✅' if result.get('saga_id') else '❌'} Payment Processing Result:")
    print(f"   Saga ID: {result.get('saga_id')}")
    print(f"   Payment ID: {result.get('payment_id')}")


if __name__ == "__main__":
    asyncio.run(main())
