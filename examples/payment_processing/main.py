
# ============================================
# EXAMPLE 2: PAYMENT PROCESSING WITH FALLBACK
# ============================================

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz.core import Saga as ClassicSaga, SagaContext
from sagaz.exceptions import SagaStepError

logger = logging.getLogger(__name__)


class PaymentProcessingSaga(ClassicSaga):
    """
    Payment processing with multiple provider fallback
    """

    def __init__(self, payment_id: str, amount: float, providers: list[str]):
        super().__init__(name=f"Payment-{payment_id}", version="1.0")
        self.payment_id = payment_id
        self.amount = amount
        self.providers = providers

    async def build(self):
        """Build payment saga with provider fallback"""

        # Step 1: Validate payment request
        await self.add_step(
            name="validate_payment",
            action=self._validate_payment,
            timeout=5.0,
        )

        # Step 2: Try primary payment provider
        await self.add_step(
            name="primary_payment",
            action=self._process_with_primary,
            compensation=self._refund_primary,
            timeout=30.0,
            max_retries=2,
        )

        # Step 3: Record transaction
        await self.add_step(
            name="record_transaction",
            action=self._record_transaction,
            timeout=5.0,
        )

    async def _validate_payment(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate payment request"""
        logger.info(f"Validating payment {self.payment_id}")
        await asyncio.sleep(0.05)

        if self.amount <= 0:
            raise ValueError("Invalid payment amount")

        return {"valid": True, "amount": self.amount}

    async def _process_with_primary(self, ctx: SagaContext) -> dict[str, Any]:
        """Process payment with primary provider"""
        primary_provider = self.providers[0]
        logger.info(f"Processing ${self.amount} with {primary_provider}")

        await asyncio.sleep(0.2)

        return {
            "provider": primary_provider,
            "transaction_id": f"TXN-{primary_provider}-{self.payment_id}",
            "amount": self.amount,
            "status": "completed",
        }

    async def _refund_primary(self, result: dict, ctx: SagaContext) -> None:
        """Refund payment from primary provider"""
        logger.warning(f"Refunding {result['transaction_id']}")
        await asyncio.sleep(0.2)

    async def _record_transaction(self, ctx: SagaContext) -> dict[str, Any]:
        """Record transaction in database"""
        logger.info(f"Recording transaction for payment {self.payment_id}")
        await asyncio.sleep(0.05)

        payment_result = ctx.get("primary_payment")
        return {
            "payment_id": self.payment_id,
            "transaction_id": payment_result["transaction_id"],
            "recorded_at": datetime.now().isoformat(),
        }

