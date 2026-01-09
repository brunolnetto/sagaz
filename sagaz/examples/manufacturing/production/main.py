"""
Manufacturing Production Saga Example

Demonstrates physical action as a pivot point. Once production starts
(machines running, materials in process), the operation cannot be reversed
without creating scrap/waste.

Pivot Step: start_production
    Once CNC machines start cutting, materials are committed.
    Physical transformation is irreversible.
    Stopping mid-production creates scrap.

Forward Recovery:
    - Quality check fails: Rework, use secondary materials, or scrap
    - Packaging fails: Repackage, hold for manual handling
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate, forward_recovery
from sagaz.exceptions import SagaStepError
from sagaz.pivot import RecoveryAction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Simulation Helpers
# =============================================================================

class MESSimulator:
    """Manufacturing Execution System (MES) simulator."""

    @staticmethod
    async def validate_work_order(work_order_id: str, product_sku: str) -> dict:
        """Validate work order against production schedule."""
        await asyncio.sleep(0.05)
        return {
            "valid": True,
            "priority": "high",
            "due_date": "2026-01-10",
        }

    @staticmethod
    async def reserve_materials(materials: list, lot_number: str) -> dict:
        """Reserve raw materials from inventory."""
        await asyncio.sleep(0.1)
        return {
            "reservation_id": f"MAT-{lot_number}",
            "materials_reserved": materials,
            "location": "Warehouse A, Bin 12",
        }

    @staticmethod
    async def schedule_machine(machine_id: str, duration_hours: float) -> dict:
        """Schedule machine time in production queue."""
        await asyncio.sleep(0.05)
        return {
            "schedule_id": f"SCHED-{machine_id}",
            "start_time": datetime.now().isoformat(),
            "estimated_duration": duration_hours,
        }

    @staticmethod
    async def start_production_run(
        machine_id: str,
        product_sku: str,
        quantity: int,
    ) -> dict:
        """Start the production run - IRREVERSIBLE once started."""
        await asyncio.sleep(0.3)  # Production takes time
        return {
            "production_run_id": f"PROD-{machine_id}-{datetime.now().strftime('%H%M%S')}",
            "status": "in_progress",
            "machine_id": machine_id,
            "start_time": datetime.now().isoformat(),
        }

    @staticmethod
    async def run_quality_check(production_run_id: str, specs: dict) -> dict:
        """Run quality inspection on produced items."""
        await asyncio.sleep(0.2)

        # Simulate quality results
        import random
        passed = random.random() > 0.15  # 15% failure rate

        return {
            "qc_id": f"QC-{production_run_id}",
            "passed": passed,
            "dimensions_ok": True,
            "surface_finish_ok": passed,
            "tolerance_ok": True,
            "inspector": "QC-BOT-01",
        }

    @staticmethod
    async def package_items(production_run_id: str, quantity: int) -> dict:
        """Package completed items for shipping."""
        await asyncio.sleep(0.1)
        return {
            "package_id": f"PKG-{production_run_id}",
            "units_packaged": quantity,
            "package_type": "standard_crate",
        }

    @staticmethod
    async def ship_to_warehouse(package_id: str) -> dict:
        """Transfer packaged items to warehouse."""
        await asyncio.sleep(0.1)
        return {
            "shipment_id": f"SHIP-{package_id}",
            "destination": "Warehouse B",
            "arrival_time": datetime.now().isoformat(),
        }


# =============================================================================
# Saga Definition
# =============================================================================

class ManufacturingProductionSaga(Saga):
    """
    Manufacturing production saga with physical action pivot.

    This saga demonstrates the irreversibility of physical manufacturing.
    Once production starts, materials are being transformed and cannot
    be restored to their original state.

    Expected context:
        - work_order_id: str - Production work order ID
        - product_sku: str - SKU of product to manufacture
        - quantity: int - Number of units to produce
        - materials: list[dict] - Materials needed [{sku, quantity, lot}]
        - machine_id: str - CNC machine to use
        - operator_id: str - Operator running the job
        - quality_specs: dict - Quality specifications
    """

    saga_name = "manufacturing-production"

    # === REVERSIBLE ZONE ===

    @action("validate_work_order")
    async def validate_work_order(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate work order and production schedule."""
        work_order_id = ctx.get("work_order_id")
        product_sku = ctx.get("product_sku")

        logger.info(f"📋 [{work_order_id}] Validating work order for {product_sku}...")

        result = await MESSimulator.validate_work_order(work_order_id, product_sku)

        if not result["valid"]:
            msg = f"Invalid work order: {work_order_id}"
            raise SagaStepError(msg)

        logger.info(f"✅ [{work_order_id}] Work order validated, priority: {result['priority']}")

        return {
            "validation_status": "valid",
            "priority": result["priority"],
            "due_date": result["due_date"],
        }

    @compensate("validate_work_order")
    async def cancel_work_order(self, ctx: SagaContext) -> None:
        """Cancel work order validation."""
        work_order_id = ctx.get("work_order_id")
        logger.warning(f"↩️ [{work_order_id}] Cancelling work order validation...")
        await asyncio.sleep(0.05)

    @action("reserve_materials", depends_on=["validate_work_order"])
    async def reserve_materials(self, ctx: SagaContext) -> dict[str, Any]:
        """Reserve raw materials from inventory."""
        work_order_id = ctx.get("work_order_id")
        materials = ctx.get("materials", [])

        logger.info(f"📦 [{work_order_id}] Reserving {len(materials)} material types...")

        lot_number = f"{work_order_id}-LOT"
        result = await MESSimulator.reserve_materials(materials, lot_number)

        logger.info(f"✅ [{work_order_id}] Materials reserved: {result['reservation_id']}")

        return {
            "material_reservation_id": result["reservation_id"],
            "material_location": result["location"],
        }

    @compensate("reserve_materials")
    async def release_materials(self, ctx: SagaContext) -> None:
        """Release reserved materials back to inventory."""
        work_order_id = ctx.get("work_order_id")
        reservation_id = ctx.get("material_reservation_id")

        logger.warning(f"↩️ [{work_order_id}] Releasing materials {reservation_id}...")
        await asyncio.sleep(0.1)
        logger.info(f"✅ [{work_order_id}] Materials returned to inventory")

    @action("schedule_machine", depends_on=["reserve_materials"])
    async def schedule_machine(self, ctx: SagaContext) -> dict[str, Any]:
        """Schedule machine time in production queue."""
        work_order_id = ctx.get("work_order_id")
        machine_id = ctx.get("machine_id", "CNC-01")
        quantity = ctx.get("quantity", 1)

        # Estimate duration based on quantity
        estimated_hours = quantity * 0.5  # 30 min per unit

        logger.info(f"🏭 [{work_order_id}] Scheduling machine {machine_id}...")

        result = await MESSimulator.schedule_machine(machine_id, estimated_hours)

        logger.info(
            f"✅ [{work_order_id}] Machine scheduled: {result['schedule_id']} "
            f"(~{estimated_hours}h)"
        )

        return {
            "schedule_id": result["schedule_id"],
            "estimated_duration_hours": estimated_hours,
            "scheduled_start": result["start_time"],
        }

    @compensate("schedule_machine")
    async def cancel_machine_schedule(self, ctx: SagaContext) -> None:
        """Cancel machine schedule."""
        work_order_id = ctx.get("work_order_id")
        schedule_id = ctx.get("schedule_id")

        logger.warning(f"↩️ [{work_order_id}] Cancelling machine schedule {schedule_id}...")
        await asyncio.sleep(0.05)
        logger.info(f"✅ [{work_order_id}] Machine schedule cancelled")

    # === PIVOT STEP ===

    @action("start_production", depends_on=["schedule_machine"], pivot=True)
    async def start_production(self, ctx: SagaContext) -> dict[str, Any]:
        """
        🔒 PIVOT STEP: Start the production run.

        Once this step completes, machines are running and materials
        are being physically transformed. Cannot be "undone" - stopping
        mid-production wastes materials (scrap).
        """
        work_order_id = ctx.get("work_order_id")
        machine_id = ctx.get("machine_id", "CNC-01")
        product_sku = ctx.get("product_sku")
        quantity = ctx.get("quantity", 1)

        logger.info(f"🔒 [{work_order_id}] PIVOT: Starting production on {machine_id}...")
        logger.info(f"   Producing {quantity}x {product_sku}")

        result = await MESSimulator.start_production_run(machine_id, product_sku, quantity)

        logger.info(
            f"✅ [{work_order_id}] Production started! "
            f"Run ID: {result['production_run_id']}"
        )

        return {
            "production_run_id": result["production_run_id"],
            "production_start_time": result["start_time"],
            "pivot_reached": True,  # Mark point of no return
        }

    # Note: No compensation for start_production - it's a pivot step!
    # Once production starts, materials are transformed. Cannot undo.

    # === COMMITTED ZONE (Forward Recovery Only) ===

    @action("run_quality_check", depends_on=["start_production"])
    async def run_quality_check(self, ctx: SagaContext) -> dict[str, Any]:
        """Run quality inspection on produced items."""
        work_order_id = ctx.get("work_order_id")
        production_run_id = ctx.get("production_run_id")
        quality_specs = ctx.get("quality_specs", {})

        logger.info(f"🔍 [{work_order_id}] Running quality inspection...")

        result = await MESSimulator.run_quality_check(production_run_id, quality_specs)

        if result["passed"]:
            logger.info(f"✅ [{work_order_id}] Quality check PASSED!")
        else:
            logger.warning(f"⚠️ [{work_order_id}] Quality check FAILED - needs rework")
            # In a real implementation, forward recovery would handle this
            # For now, we continue to demonstrate the flow

        return {
            "qc_id": result["qc_id"],
            "qc_passed": result["passed"],
            "qc_details": {
                "dimensions": result["dimensions_ok"],
                "surface_finish": result["surface_finish_ok"],
                "tolerance": result["tolerance_ok"],
            },
        }

    @forward_recovery("run_quality_check")
    async def handle_quality_failure(
        self, ctx: SagaContext, error: Exception
    ) -> RecoveryAction:
        """
        Forward recovery for quality check failures.

        Strategies:
        1. RETRY - Rework the item (minor defects)
        2. RETRY_WITH_ALTERNATE - Use secondary materials
        3. MANUAL_INTERVENTION - Scrap decision needed
        """
        rework_attempts = ctx.get("rework_attempts", 0)

        if rework_attempts < 2:
            ctx.set("rework_attempts", rework_attempts + 1)
            logger.info("🔧 Attempting rework...")
            return RecoveryAction.RETRY

        # Check for secondary materials
        if ctx.get("secondary_materials_available"):
            logger.info("📦 Using secondary materials...")
            return RecoveryAction.RETRY_WITH_ALTERNATE

        logger.error("❌ Scrap decision required")
        return RecoveryAction.MANUAL_INTERVENTION

    @action("package_product", depends_on=["run_quality_check"])
    async def package_product(self, ctx: SagaContext) -> dict[str, Any]:
        """Package completed products for shipping."""
        work_order_id = ctx.get("work_order_id")
        production_run_id = ctx.get("production_run_id")
        quantity = ctx.get("quantity", 1)

        logger.info(f"📦 [{work_order_id}] Packaging {quantity} units...")

        result = await MESSimulator.package_items(production_run_id, quantity)

        logger.info(f"✅ [{work_order_id}] Packaging complete: {result['package_id']}")

        return {
            "package_id": result["package_id"],
            "units_packaged": result["units_packaged"],
        }

    @action("ship_to_warehouse", depends_on=["package_product"])
    async def ship_to_warehouse(self, ctx: SagaContext) -> dict[str, Any]:
        """Transfer packaged items to finished goods warehouse."""
        work_order_id = ctx.get("work_order_id")
        package_id = ctx.get("package_id")

        logger.info(f"🚚 [{work_order_id}] Shipping to warehouse...")

        result = await MESSimulator.ship_to_warehouse(package_id)

        logger.info(
            f"✅ [{work_order_id}] Shipped! "
            f"Destination: {result['destination']}"
        )

        return {
            "shipment_id": result["shipment_id"],
            "warehouse_destination": result["destination"],
            "completion_time": result["arrival_time"],
        }


# =============================================================================
# Demo Scenarios
# =============================================================================

async def main():
    """Run the manufacturing production saga demo."""

    saga = ManufacturingProductionSaga()

    # Scenario 1: Successful production run

    await saga.run({
        "work_order_id": "WO-2026-001",
        "product_sku": "WIDGET-PRO-X1",
        "quantity": 10,
        "materials": [
            {"sku": "STEEL-304", "quantity": 5, "lot": "LOT-A1"},
            {"sku": "BEARING-6205", "quantity": 10, "lot": "LOT-B2"},
        ],
        "machine_id": "CNC-MILL-01",
        "operator_id": "OP-123",
        "quality_specs": {
            "tolerance_mm": 0.05,
            "surface_finish": "Ra 0.8",
        },
    })


    # Scenario 2: Pre-pivot failure

    # This would be simulated by making the MES return an error

    # Scenario 3: Post-pivot forward recovery



if __name__ == "__main__":
    asyncio.run(main())
