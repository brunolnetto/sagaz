"""
3D Printing Job Saga Example

Demonstrates material commitment in additive manufacturing.
Once printing starts, material is being deposited and job is committed.

Pivot Step: start_print
    Once first layer is deposited, material is committed.
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


class ThreeDPrintingSaga(Saga):
    """3D printing job saga with material commitment pivot."""
    
    saga_name = "3d-printing-job"
    
    @action("validate_model")
    async def validate_model(self, ctx: SagaContext) -> dict[str, Any]:
        job_id = ctx.get("job_id")
        logger.info(f"📐 [{job_id}] Validating 3D model...")
        await asyncio.sleep(0.1)
        return {"model_valid": True, "estimated_layers": 2500, "estimated_time_hours": 8.5}
    
    @compensate("validate_model")
    async def release_model(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('job_id')}] Releasing model...")
        await asyncio.sleep(0.05)
    
    @action("check_material", depends_on=["validate_model"])
    async def check_material(self, ctx: SagaContext) -> dict[str, Any]:
        job_id = ctx.get("job_id")
        logger.info(f"🧵 [{job_id}] Checking material availability...")
        await asyncio.sleep(0.1)
        return {"material_available": True, "material_type": "PLA", "required_grams": 250}
    
    @compensate("check_material")
    async def release_material_reservation(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('job_id')}] Releasing material reservation...")
        await asyncio.sleep(0.05)
    
    @action("preheat_printer", depends_on=["check_material"])
    async def preheat_printer(self, ctx: SagaContext) -> dict[str, Any]:
        job_id = ctx.get("job_id")
        printer_id = ctx.get("printer_id", "PRINTER-01")
        logger.info(f"🌡️ [{job_id}] Preheating {printer_id}...")
        await asyncio.sleep(0.2)
        return {"printer_ready": True, "bed_temp": 60, "nozzle_temp": 210}
    
    @compensate("preheat_printer")
    async def cooldown_printer(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('job_id')}] Cooling down printer...")
        await asyncio.sleep(0.1)
    
    @action("start_print", depends_on=["preheat_printer"])
    async def start_print(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Begin 3D printing - material committed."""
        job_id = ctx.get("job_id")
        logger.info(f"🔒 [{job_id}] PIVOT: Starting print job...")
        await asyncio.sleep(0.3)
        return {
            "print_started": True,
            "start_time": datetime.now().isoformat(),
            "first_layer_complete": True,
            "pivot_reached": True,
        }
    
    @action("post_process", depends_on=["start_print"])
    async def post_process(self, ctx: SagaContext) -> dict[str, Any]:
        job_id = ctx.get("job_id")
        logger.info(f"🔧 [{job_id}] Post-processing (supports, smoothing)...")
        await asyncio.sleep(0.2)
        return {"post_processed": True}
    
    @action("quality_scan", depends_on=["post_process"])
    async def quality_scan(self, ctx: SagaContext) -> dict[str, Any]:
        job_id = ctx.get("job_id")
        logger.info(f"📏 [{job_id}] Quality scanning...")
        await asyncio.sleep(0.1)
        return {"quality_passed": True, "dimensional_accuracy": "99.5%"}


async def main():
    print("=" * 80)
    print("🖨️ 3D Printing Job Saga Demo")
    print("=" * 80)
    
    saga = ThreeDPrintingSaga()
    result = await saga.run({
        "job_id": "PRINT-2026-001",
        "model_file": "widget_v2.stl",
        "printer_id": "PRUSA-MK4-01",
        "material": "PLA",
    })
    
    print(f"\n✅ Print Result:")
    print(f"   Quality: {result.get('dimensional_accuracy', 'N/A')}")
    print(f"   Pivot Reached: {result.get('pivot_reached', False)}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
