"""
Prescription Fulfillment Saga Example

Demonstrates controlled substance dispensing as pivot point.
Once medication is dispensed, it's logged with DEA and PDMP.

Pivot Step: dispense_medication
    Medication removed from inventory, sealed for patient.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class PrescriptionFulfillmentSaga(Saga):
    """Prescription fulfillment saga with dispensing pivot."""

    saga_name = "prescription-fulfillment"

    @action("verify_prescription")
    async def verify_prescription(self, ctx: SagaContext) -> dict[str, Any]:
        rx_id = ctx.get("prescription_id")
        logger.info(f"💊 [{rx_id}] Verifying prescription...")
        await asyncio.sleep(0.1)
        return {"rx_valid": True, "prescriber_verified": True}

    @compensate("verify_prescription")
    async def void_verification(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('prescription_id')}] Voiding verification...")
        await asyncio.sleep(0.05)

    @action("check_inventory", depends_on=["verify_prescription"])
    async def check_inventory(self, ctx: SagaContext) -> dict[str, Any]:
        rx_id = ctx.get("prescription_id")
        logger.info(f"📦 [{rx_id}] Checking inventory...")
        await asyncio.sleep(0.1)
        return {"in_stock": True, "lot_number": "LOT-2026-A", "expiration": "2027-06-30"}

    @compensate("check_inventory")
    async def release_inventory(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('prescription_id')}] Releasing inventory hold...")
        await asyncio.sleep(0.05)

    @action("insurance_adjudicate", depends_on=["check_inventory"])
    async def insurance_adjudicate(self, ctx: SagaContext) -> dict[str, Any]:
        rx_id = ctx.get("prescription_id")
        logger.info(f"🏥 [{rx_id}] Adjudicating with insurance...")
        await asyncio.sleep(0.2)
        return {"adjudicated": True, "copay": "25.00", "insurance_paid": "150.00"}

    @compensate("insurance_adjudicate")
    async def reverse_claim(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('prescription_id')}] Reversing insurance claim...")
        await asyncio.sleep(0.05)

    @action("dispense_medication", depends_on=["insurance_adjudicate"])
    async def dispense_medication(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Dispense medication - DEA/PDMP logged."""
        rx_id = ctx.get("prescription_id")
        logger.info(f"🔒 [{rx_id}] PIVOT: Dispensing medication...")
        await asyncio.sleep(0.3)
        return {
            "dispensed": True,
            "ndc": "12345-678-90",
            "quantity": 30,
            "dea_logged": True,
            "pdmp_updated": True,
            "pivot_reached": True,
        }

    @action("patient_pickup", depends_on=["dispense_medication"])
    async def patient_pickup(self, ctx: SagaContext) -> dict[str, Any]:
        rx_id = ctx.get("prescription_id")
        logger.info(f"👤 [{rx_id}] Awaiting patient pickup...")
        await asyncio.sleep(0.1)
        return {"picked_up": True, "picked_up_at": datetime.now().isoformat()}


async def main():

    saga = PrescriptionFulfillmentSaga()
    await saga.run({
        "prescription_id": "RX-2026-12345",
        "patient_id": "PAT-67890",
        "medication": "Lisinopril 10mg",
        "quantity": 30,
    })



if __name__ == "__main__":
    asyncio.run(main())
