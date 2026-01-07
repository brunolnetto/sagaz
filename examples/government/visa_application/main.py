"""
Visa Application Processing Saga Example

Demonstrates biometric capture as pivot point. Once biometrics
are captured and stored in government database, the data cannot
be simply "deleted" - only flagged.

Pivot Step: capture_biometrics
    Fingerprints and photo stored in government database.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any
import uuid

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class VisaApplicationSaga(Saga):
    """Visa application processing saga with biometric capture pivot."""
    
    saga_name = "visa-application"
    
    @action("submit_application")
    async def submit_application(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"📋 [{app_id}] Submitting visa application...")
        await asyncio.sleep(0.1)
        return {"application_status": "submitted", "case_number": f"CASE-{app_id}"}
    
    @compensate("submit_application")
    async def withdraw_application(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Withdrawing application...")
        await asyncio.sleep(0.05)
    
    @action("document_check", depends_on=["submit_application"])
    async def document_check(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"📄 [{app_id}] Checking documents...")
        await asyncio.sleep(0.15)
        return {"documents_valid": True, "passport_verified": True}
    
    @compensate("document_check")
    async def archive_documents(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Archiving documents...")
        await asyncio.sleep(0.05)
    
    @action("schedule_interview", depends_on=["document_check"])
    async def schedule_interview(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"📅 [{app_id}] Scheduling interview...")
        await asyncio.sleep(0.1)
        return {"interview_scheduled": True, "interview_date": "2026-02-15"}
    
    @compensate("schedule_interview")
    async def cancel_interview(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('application_id')}] Cancelling interview...")
        await asyncio.sleep(0.05)
    
    @action("capture_biometrics", depends_on=["schedule_interview"])
    async def capture_biometrics(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Capture biometrics - stored in govt database."""
        app_id = ctx.get("application_id")
        logger.info(f"🔒 [{app_id}] PIVOT: Capturing biometrics...")
        await asyncio.sleep(0.3)
        return {
            "biometrics_captured": True,
            "fingerprints_stored": True,
            "photo_stored": True,
            "biometric_id": f"BIO-{uuid.uuid4().hex[:8].upper()}",
            "pivot_reached": True,
        }
    
    @action("background_check", depends_on=["capture_biometrics"])
    async def background_check(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"🔍 [{app_id}] Running background check...")
        await asyncio.sleep(0.4)
        return {"background_cleared": True, "no_flags": True}
    
    @action("render_decision", depends_on=["background_check"])
    async def render_decision(self, ctx: SagaContext) -> dict[str, Any]:
        app_id = ctx.get("application_id")
        logger.info(f"⚖️ [{app_id}] Rendering decision...")
        await asyncio.sleep(0.2)
        return {"decision": "APPROVED", "visa_class": "B1/B2", "validity_years": 10}


async def main():
    print("=" * 80)
    print("🛂 Visa Application Processing Saga Demo")
    print("=" * 80)
    
    saga = VisaApplicationSaga()
    result = await saga.run({
        "application_id": "VISA-2026-001",
        "applicant_name": "Jane Smith",
        "passport_number": "AB1234567",
        "nationality": "Canada",
        "visa_type": "B1/B2",
    })
    
    print(f"\n✅ Application Result:")
    print(f"   Decision: {result.get('decision', 'N/A')}")
    print(f"   Visa Class: {result.get('visa_class', 'N/A')}")
    print(f"   Biometric ID: {result.get('biometric_id', 'N/A')}")
    print(f"   Pivot Reached: {result.get('pivot_reached', False)}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
