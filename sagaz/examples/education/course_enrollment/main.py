"""
Course Enrollment Saga Example

Demonstrates seat confirmation as pivot point. Once enrollment
is confirmed, the seat is committed to the student.

Pivot Step: confirm_enrollment
    Seat reserved, financial aid applied.
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


class CourseEnrollmentSaga(Saga):
    """Course enrollment saga with confirmation pivot."""
    
    saga_name = "course-enrollment"
    
    @action("verify_prerequisites")
    async def verify_prerequisites(self, ctx: SagaContext) -> dict[str, Any]:
        enrollment_id = ctx.get("enrollment_id")
        logger.info(f"📚 [{enrollment_id}] Verifying prerequisites...")
        await asyncio.sleep(0.1)
        return {"prereqs_met": True, "gpa_requirement": "met"}
    
    @compensate("verify_prerequisites")
    async def release_prereq_check(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('enrollment_id')}] Releasing prereq check...")
        await asyncio.sleep(0.05)
    
    @action("check_availability", depends_on=["verify_prerequisites"])
    async def check_availability(self, ctx: SagaContext) -> dict[str, Any]:
        enrollment_id = ctx.get("enrollment_id")
        logger.info(f"🪑 [{enrollment_id}] Checking seat availability...")
        await asyncio.sleep(0.1)
        return {"seats_available": True, "remaining_seats": 5}
    
    @compensate("check_availability")
    async def release_seat_hold(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('enrollment_id')}] Releasing seat hold...")
        await asyncio.sleep(0.05)
    
    @action("apply_financial_aid", depends_on=["check_availability"])
    async def apply_financial_aid(self, ctx: SagaContext) -> dict[str, Any]:
        enrollment_id = ctx.get("enrollment_id")
        logger.info(f"💰 [{enrollment_id}] Applying financial aid...")
        await asyncio.sleep(0.2)
        return {"aid_applied": True, "amount": "2500.00"}
    
    @compensate("apply_financial_aid")
    async def reverse_aid(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('enrollment_id')}] Reversing aid application...")
        await asyncio.sleep(0.05)
    
    @action("confirm_enrollment", depends_on=["apply_financial_aid"])
    async def confirm_enrollment(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Confirm enrollment - seat committed."""
        enrollment_id = ctx.get("enrollment_id")
        logger.info(f"🔒 [{enrollment_id}] PIVOT: Confirming enrollment...")
        await asyncio.sleep(0.3)
        return {
            "enrollment_confirmed": True,
            "student_id": ctx.get("student_id"),
            "course_section": f"SEC-{uuid.uuid4().hex[:4].upper()}",
            "pivot_reached": True,
        }
    
    @action("send_confirmation", depends_on=["confirm_enrollment"])
    async def send_confirmation(self, ctx: SagaContext) -> dict[str, Any]:
        enrollment_id = ctx.get("enrollment_id")
        logger.info(f"📧 [{enrollment_id}] Sending confirmation...")
        await asyncio.sleep(0.1)
        return {"confirmation_sent": True}


async def main():
    print("=" * 80)
    print("🎓 Course Enrollment Saga Demo")
    print("=" * 80)
    
    saga = CourseEnrollmentSaga()
    result = await saga.run({
        "enrollment_id": "ENROLL-2026-001",
        "student_id": "STU-12345",
        "course_id": "CS-301",
        "semester": "Fall 2026",
    })
    
    print(f"\n✅ Enrollment Result:")
    print(f"   Section: {result.get('course_section', 'N/A')}")
    print(f"   Confirmed: {result.get('enrollment_confirmed', False)}")
    print(f"   Pivot Reached: {result.get('pivot_reached', False)}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
