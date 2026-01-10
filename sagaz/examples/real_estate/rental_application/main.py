"""
Rental Application Processing Saga Example

Demonstrates credit check and deposit charging as pivot points.
Once deposit is charged, the applicant is financially committed.

Pivot Step: charge_deposit
    Deposit charged, application committed.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sagaz import Saga, SagaContext, action, compensate, forward_recovery
from sagaz.execution.pivot import RecoveryAction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class RentalApplicationSaga(Saga):
    """Rental application saga with deposit charge pivot."""

    saga_name = "rental-application"

    @action("validate_application")
    async def validate_application(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"📋 [{app_id}] Validating application...")
        await asyncio.sleep(0.1)
        return {"application_valid": True}

    @compensate("validate_application")
    async def void_application(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Voiding application...")
        await asyncio.sleep(0.05)

    @action("verify_income", depends_on=["validate_application"])
    async def verify_income(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"💰 [{app_id}] Verifying income...")
        await asyncio.sleep(0.15)
        return {"income_verified": True, "income_ratio": 2.8}

    @compensate("verify_income")
    async def archive_income_docs(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Archiving income docs...")
        await asyncio.sleep(0.05)

    @action("run_credit_check", depends_on=["verify_income"])
    async def run_credit_check(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"📊 [{app_id}] Running credit check...")
        await asyncio.sleep(0.2)
        return {"credit_score": 720, "credit_tier": "prime"}

    @compensate("run_credit_check")
    async def void_credit_inquiry(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Noting inquiry void...")
        await asyncio.sleep(0.05)

    @action("charge_deposit", depends_on=["run_credit_check"], pivot=True)
    async def charge_deposit(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Charge deposit - financial commitment."""
        app_id = ctx.get("application_id")
        deposit = Decimal(str(ctx.get("deposit_amount", 2500)))
        logger.info(f"🔒 [{app_id}] PIVOT: Charging deposit ${deposit}...")
        await asyncio.sleep(0.3)
        return {
            "deposit_charged": True,
            "payment_id": f"DEP-{uuid.uuid4().hex[:8].upper()}",
            "amount": str(deposit),
            "pivot_reached": True,
        }

    @action("reserve_unit", depends_on=["charge_deposit"])
    async def reserve_unit(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        unit_id = ctx.get("unit_id", "UNIT-A101")
        logger.info(f"🏠 [{app_id}] Reserving unit {unit_id}...")
        await asyncio.sleep(0.15)
        return {"unit_reserved": True, "move_in_date": "2026-02-01"}

    @forward_recovery("reserve_unit")
    async def handle_reservation_failure(
        self, ctx: SagaContext, error: Exception
    ) -> RecoveryAction:
        """Forward recovery if unit can't be reserved after deposit."""
        retry_count = ctx.get("_reservation_retries", 0)
        if retry_count < 2:
            ctx.set("_reservation_retries", retry_count + 1)
            logger.info(f"⏳ Retrying reservation (attempt {retry_count + 1}/2)...")
            return RecoveryAction.RETRY

        # Offer alternate unit
        alternate_units = ctx.get("alternate_units", ["UNIT-A102", "UNIT-B101"])
        if alternate_units:
            ctx.set("unit_id", alternate_units.pop(0))
            ctx.set("alternate_units", alternate_units)
            logger.info(f"🔄 Trying alternate unit: {ctx.get('unit_id')}")
            return RecoveryAction.RETRY_WITH_ALTERNATE

        logger.warning("❌ No units available, manual intervention needed")
        return RecoveryAction.MANUAL_INTERVENTION

    @action("generate_lease", depends_on=["reserve_unit"])
    async def generate_lease(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"📄 [{app_id}] Generating lease agreement...")
        await asyncio.sleep(0.1)
        return {"lease_id": f"LEASE-{app_id}", "lease_term_months": 12}


async def main():
    saga = RentalApplicationSaga()
    await saga.run(
        {
            "application_id": "APP-2026-001",
            "applicant_name": "Jane Smith",
            "unit_id": "UNIT-A101",
            "deposit_amount": Decimal("2500"),
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
