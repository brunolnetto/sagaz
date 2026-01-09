"""
Loan Origination Saga Example

Demonstrates funds disbursement as pivot point. Once loan funds
are transferred to the borrower, the loan is active and can only
be "compensated" via loan payoff.

Pivot Step: disburse_funds
    Once funds are in borrower's account, the loan is active.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class LoanOriginationSaga(Saga):
    """Loan origination saga with funds disbursement pivot."""

    saga_name = "loan-origination"

    @action("submit_application")
    async def submit_application(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"📝 [{app_id}] Submitting loan application...")
        await asyncio.sleep(0.1)
        return {"application_status": "submitted", "submitted_at": datetime.now().isoformat()}

    @compensate("submit_application")
    async def withdraw_application(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Withdrawing application...")
        await asyncio.sleep(0.05)

    @action("run_credit_check", depends_on=["submit_application"])
    async def run_credit_check(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        credit_score = ctx.get("credit_score", 720)
        logger.info(f"📊 [{app_id}] Running credit check...")
        await asyncio.sleep(0.2)
        return {"credit_score": credit_score, "credit_tier": "prime" if credit_score >= 700 else "subprime"}

    @compensate("run_credit_check")
    async def archive_credit_inquiry(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Archiving credit inquiry...")
        await asyncio.sleep(0.05)

    @action("underwriting_review", depends_on=["run_credit_check"])
    async def underwriting_review(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"🔍 [{app_id}] Underwriting review...")
        await asyncio.sleep(0.3)
        return {"underwriting_decision": "approved", "approved_rate": "6.5%"}

    @compensate("underwriting_review")
    async def cancel_underwriting(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Cancelling underwriting decision...")
        await asyncio.sleep(0.05)

    @action("generate_loan_documents", depends_on=["underwriting_review"])
    async def generate_loan_documents(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"📄 [{app_id}] Generating loan documents...")
        await asyncio.sleep(0.2)
        return {"document_package_id": f"DOC-{app_id}", "documents": ["promissory_note", "disclosure", "agreement"]}

    @compensate("generate_loan_documents")
    async def void_documents(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Voiding loan documents...")
        await asyncio.sleep(0.05)

    @action("disburse_funds", depends_on=["generate_loan_documents"])
    async def disburse_funds(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Disburse loan funds to borrower."""
        app_id = ctx.get("application_id")
        amount = Decimal(str(ctx.get("loan_amount", 25000)))
        logger.info(f"🔒 [{app_id}] PIVOT: Disbursing ${amount:,.2f}...")
        await asyncio.sleep(0.3)
        return {
            "disbursement_id": f"DISB-{uuid.uuid4().hex[:8].upper()}",
            "amount_disbursed": str(amount),
            "disbursed_at": datetime.now().isoformat(),
            "pivot_reached": True,
        }

    @action("send_welcome", depends_on=["disburse_funds"])
    async def send_welcome(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"📧 [{app_id}] Sending welcome package...")
        await asyncio.sleep(0.1)
        return {"welcome_sent": True}


async def main():

    saga = LoanOriginationSaga()
    await saga.run({
        "application_id": "LOAN-2026-001",
        "applicant_id": "CUST-12345",
        "loan_amount": Decimal("35000"),
        "loan_term_months": 60,
        "credit_score": 745,
    })



if __name__ == "__main__":
    asyncio.run(main())
