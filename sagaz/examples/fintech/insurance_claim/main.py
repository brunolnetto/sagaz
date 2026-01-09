"""
Insurance Claim Processing Saga Example

Demonstrates payment disbursement as pivot point. Once a claim
payment is issued, the funds are committed to the claimant.

Pivot Step: disburse_payment
    Once payment is sent, it cannot be easily reversed.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class InsuranceClaimSaga(Saga):
    """Insurance claim processing saga with payment disbursement pivot."""

    saga_name = "insurance-claim"

    @action("submit_claim")
    async def submit_claim(self, ctx: SagaContext) -> dict[str, Any]:
        claim_id = ctx.get("claim_id")
        logger.info(f"📋 [{claim_id}] Submitting insurance claim...")
        await asyncio.sleep(0.1)
        return {"claim_status": "submitted", "submitted_at": datetime.now().isoformat()}

    @compensate("submit_claim")
    async def withdraw_claim(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('claim_id')}] Withdrawing claim...")
        await asyncio.sleep(0.05)

    @action("validate_policy", depends_on=["submit_claim"])
    async def validate_policy(self, ctx: SagaContext) -> dict[str, Any]:
        claim_id = ctx.get("claim_id")
        logger.info(f"📄 [{claim_id}] Validating policy coverage...")
        await asyncio.sleep(0.15)
        return {"policy_valid": True, "coverage_amount": "100000", "deductible": "1000"}

    @compensate("validate_policy")
    async def release_policy_hold(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('claim_id')}] Releasing policy hold...")
        await asyncio.sleep(0.05)

    @action("assess_damage", depends_on=["validate_policy"])
    async def assess_damage(self, ctx: SagaContext) -> dict[str, Any]:
        claim_id = ctx.get("claim_id")
        claim_amount = ctx.get("claim_amount", 5000)
        logger.info(f"🔍 [{claim_id}] Assessing damage...")
        await asyncio.sleep(0.2)
        return {"assessed_amount": str(claim_amount), "assessment_id": f"ASSESS-{claim_id}"}

    @compensate("assess_damage")
    async def archive_assessment(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('claim_id')}] Archiving assessment...")
        await asyncio.sleep(0.05)

    @action("approve_claim", depends_on=["assess_damage"])
    async def approve_claim(self, ctx: SagaContext) -> dict[str, Any]:
        claim_id = ctx.get("claim_id")
        logger.info(f"✔️ [{claim_id}] Approving claim...")
        await asyncio.sleep(0.1)
        return {"approval_id": f"APPR-{claim_id}", "approved_amount": ctx.get("assessed_amount")}

    @compensate("approve_claim")
    async def revoke_approval(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('claim_id')}] Revoking approval...")
        await asyncio.sleep(0.05)

    @action("disburse_payment", depends_on=["approve_claim"])
    async def disburse_payment(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Disburse claim payment to claimant."""
        claim_id = ctx.get("claim_id")
        amount = Decimal(str(ctx.get("approved_amount", ctx.get("claim_amount", 5000))))
        logger.info(f"🔒 [{claim_id}] PIVOT: Disbursing ${amount:,.2f}...")
        await asyncio.sleep(0.3)
        return {
            "payment_id": f"PAY-{uuid.uuid4().hex[:8].upper()}",
            "amount_paid": str(amount),
            "payment_method": "ACH",
            "pivot_reached": True,
        }

    @action("close_case", depends_on=["disburse_payment"])
    async def close_case(self, ctx: SagaContext) -> dict[str, Any]:
        claim_id = ctx.get("claim_id")
        logger.info(f"✅ [{claim_id}] Closing case...")
        await asyncio.sleep(0.1)
        return {"case_closed": True, "closed_at": datetime.now().isoformat()}


async def main():

    saga = InsuranceClaimSaga()
    await saga.run({
        "claim_id": "CLAIM-2026-001",
        "policy_id": "POL-12345",
        "claimant_id": "CUST-67890",
        "claim_amount": Decimal("7500"),
        "incident_type": "auto_collision",
    })



if __name__ == "__main__":
    asyncio.run(main())
