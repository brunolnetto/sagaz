"""
Simulated manufacturing execution system (MES) for the production example.
"""

import asyncio
from datetime import datetime


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
