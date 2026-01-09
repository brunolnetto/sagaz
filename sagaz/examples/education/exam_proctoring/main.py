"""
Exam Proctoring Saga Example

Demonstrates exam start as pivot point. Once exam timer starts,
the student is committed to the exam session.

Pivot Step: start_exam
    Exam timer started, student committed.
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


class ExamProctoringSaga(Saga):
    """Exam proctoring saga with exam start pivot."""

    saga_name = "exam-proctoring"

    @action("verify_student")
    async def verify_student(self, ctx: SagaContext) -> dict[str, Any]:
        exam_id = ctx.get("exam_id")
        logger.info(f"🪪 [{exam_id}] Verifying student identity...")
        await asyncio.sleep(0.1)
        return {"identity_verified": True, "photo_match": True}

    @compensate("verify_student")
    async def release_verification(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('exam_id')}] Releasing verification...")
        await asyncio.sleep(0.05)

    @action("check_environment", depends_on=["verify_student"])
    async def check_environment(self, ctx: SagaContext) -> dict[str, Any]:
        exam_id = ctx.get("exam_id")
        logger.info(f"🖥️ [{exam_id}] Checking exam environment...")
        await asyncio.sleep(0.15)
        return {"environment_clear": True, "second_monitor": False, "browser_locked": True}

    @compensate("check_environment")
    async def release_environment(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('exam_id')}] Releasing environment lock...")
        await asyncio.sleep(0.05)

    @action("reserve_exam_slot", depends_on=["check_environment"])
    async def reserve_exam_slot(self, ctx: SagaContext) -> dict[str, Any]:
        exam_id = ctx.get("exam_id")
        logger.info(f"🎯 [{exam_id}] Reserving exam slot...")
        await asyncio.sleep(0.1)
        return {"slot_reserved": True, "proctor_assigned": "PROCTOR-001"}

    @compensate("reserve_exam_slot")
    async def release_slot(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('exam_id')}] Releasing exam slot...")
        await asyncio.sleep(0.05)

    @action("start_exam", depends_on=["reserve_exam_slot"], pivot=True)
    async def start_exam(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Start exam - student committed."""
        exam_id = ctx.get("exam_id")
        duration_mins = ctx.get("duration_minutes", 120)
        logger.info(f"🔒 [{exam_id}] PIVOT: Starting exam ({duration_mins} mins)...")
        await asyncio.sleep(0.3)
        return {
            "exam_started": True,
            "start_time": datetime.now().isoformat(),
            "duration_minutes": duration_mins,
            "session_id": f"SESSION-{uuid.uuid4().hex[:8].upper()}",
            "pivot_reached": True,
        }

    @action("monitor_session", depends_on=["start_exam"])
    async def monitor_session(self, ctx: SagaContext) -> dict[str, Any]:
        exam_id = ctx.get("exam_id")
        logger.info(f"👁️ [{exam_id}] Monitoring exam session...")
        await asyncio.sleep(0.2)
        return {"violations_detected": 0, "webcam_active": True}

    @forward_recovery("monitor_session")
    async def handle_monitoring_failure(self, ctx: SagaContext, error: Exception) -> RecoveryAction:
        """Forward recovery if monitoring fails during exam."""
        exam_id = ctx.get("exam_id")
        logger.warning(f"⚠️ [{exam_id}] Monitoring issue: {error}")

        # Pause exam but continue
        ctx.set("exam_paused_for_technical", True)
        logger.info(f"⏸️ [{exam_id}] Exam paused, notifying proctor...")
        return RecoveryAction.RETRY

    @action("submit_exam", depends_on=["monitor_session"])
    async def submit_exam(self, ctx: SagaContext) -> dict[str, Any]:
        exam_id = ctx.get("exam_id")
        logger.info(f"📝 [{exam_id}] Submitting exam...")
        await asyncio.sleep(0.1)
        return {"exam_submitted": True, "answers_recorded": 50}


async def main():

    saga = ExamProctoringSaga()
    await saga.run({
        "exam_id": "EXAM-2026-001",
        "student_id": "STU-12345",
        "course_id": "CS-301",
        "duration_minutes": 90,
    })



if __name__ == "__main__":
    asyncio.run(main())
