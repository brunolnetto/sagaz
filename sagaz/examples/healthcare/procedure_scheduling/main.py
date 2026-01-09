"""
Medical Procedure Scheduling Saga Example

Demonstrates procedure confirmation as pivot point. Once the procedure
is scheduled with a confirmed slot, resources are committed.

Pivot Step: confirm_procedure
    OR time reserved, staff assigned.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate, forward_recovery
from sagaz.pivot import RecoveryAction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class MedicalProcedureSchedulingSaga(Saga):
    """Medical procedure scheduling saga with confirmation pivot."""

    saga_name = "medical-procedure-scheduling"

    @action("verify_authorization")
    async def verify_authorization(self, ctx: SagaContext) -> dict[str, Any]:
        case_id = ctx.get("case_id")
        logger.info(f"📋 [{case_id}] Verifying insurance authorization...")
        await asyncio.sleep(0.1)
        return {"authorized": True, "auth_number": f"AUTH-{uuid.uuid4().hex[:8].upper()}"}

    @compensate("verify_authorization")
    async def void_authorization(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('case_id')}] Voiding authorization...")
        await asyncio.sleep(0.05)

    @action("check_patient_history", depends_on=["verify_authorization"])
    async def check_patient_history(self, ctx: SagaContext) -> dict[str, Any]:
        case_id = ctx.get("case_id")
        logger.info(f"📖 [{case_id}] Reviewing patient history...")
        await asyncio.sleep(0.15)
        return {"history_reviewed": True, "allergies_noted": True, "clearance": "green"}

    @compensate("check_patient_history")
    async def archive_review(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('case_id')}] Archiving review...")
        await asyncio.sleep(0.05)

    @action("reserve_or_time", depends_on=["check_patient_history"])
    async def reserve_or_time(self, ctx: SagaContext) -> dict[str, Any]:
        case_id = ctx.get("case_id")
        logger.info(f"🏥 [{case_id}] Reserving OR time slot...")
        await asyncio.sleep(0.2)
        return {
            "or_reserved": True,
            "or_room": "OR-3",
            "scheduled_date": "2026-01-20",
            "start_time": "08:00",
            "duration_hours": 2,
        }

    @compensate("reserve_or_time")
    async def release_or_time(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('case_id')}] Releasing OR reservation...")
        await asyncio.sleep(0.1)

    @action("assign_staff", depends_on=["reserve_or_time"])
    async def assign_staff(self, ctx: SagaContext) -> dict[str, Any]:
        case_id = ctx.get("case_id")
        logger.info(f"👨‍⚕️ [{case_id}] Assigning surgical staff...")
        await asyncio.sleep(0.15)
        return {
            "surgeon": "Dr. Smith",
            "anesthesiologist": "Dr. Jones",
            "nurses": ["Nurse A", "Nurse B"],
        }

    @compensate("assign_staff")
    async def release_staff(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('case_id')}] Releasing staff assignments...")
        await asyncio.sleep(0.05)

    @action("confirm_procedure", depends_on=["assign_staff"], pivot=True)
    async def confirm_procedure(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Confirm procedure - resources locked."""
        case_id = ctx.get("case_id")
        logger.info(f"🔒 [{case_id}] PIVOT: Confirming procedure...")
        await asyncio.sleep(0.3)
        return {
            "procedure_confirmed": True,
            "confirmation_id": f"CONF-{uuid.uuid4().hex[:8].upper()}",
            "patient_notified": True,
            "pivot_reached": True,
        }

    @action("order_supplies", depends_on=["confirm_procedure"])
    async def order_supplies(self, ctx: SagaContext) -> dict[str, Any]:
        case_id = ctx.get("case_id")
        logger.info(f"📦 [{case_id}] Ordering surgical supplies...")
        await asyncio.sleep(0.15)
        return {"supplies_ordered": True, "sterilization_scheduled": True}

    @forward_recovery("order_supplies")
    async def handle_supply_issue(self, ctx: SagaContext, error: Exception) -> RecoveryAction:
        """Forward recovery if supplies unavailable."""
        case_id = ctx.get("case_id")
        logger.warning(f"⚠️ [{case_id}] Supply issue: {error}")

        # Try alternate supplier
        if not ctx.get("_tried_alternate_supplier"):
            ctx.set("_tried_alternate_supplier", True)
            logger.info(f"🔄 [{case_id}] Trying alternate supplier...")
            return RecoveryAction.RETRY_WITH_ALTERNATE

        return RecoveryAction.MANUAL_INTERVENTION

    @action("send_prep_instructions", depends_on=["order_supplies"])
    async def send_prep_instructions(self, ctx: SagaContext) -> dict[str, Any]:
        case_id = ctx.get("case_id")
        logger.info(f"📧 [{case_id}] Sending prep instructions to patient...")
        await asyncio.sleep(0.1)
        return {"instructions_sent": True, "fasting_required": True}


async def main():

    saga = MedicalProcedureSchedulingSaga()
    await saga.run({
        "case_id": "CASE-2026-001",
        "patient_id": "PAT-12345",
        "procedure_code": "27447",
        "procedure_name": "Total Knee Arthroplasty",
    })



if __name__ == "__main__":
    asyncio.run(main())
