"""
Smart Meter Deployment Saga Example

Demonstrates meter activation as pivot point. Once the smart meter
is activated, billing starts and customer usage is being tracked.

Pivot Step: activate_meter
    Meter goes live, billing starts.
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


class SmartMeterDeploymentSaga(Saga):
    """Smart meter deployment saga with activation pivot."""
    
    saga_name = "smart-meter-deployment"
    
    @action("schedule_install")
    async def schedule_install(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"📅 [{order_id}] Scheduling installation...")
        await asyncio.sleep(0.1)
        return {"install_date": "2026-01-15", "technician_assigned": True}
    
    @compensate("schedule_install")
    async def cancel_schedule(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Cancelling schedule...")
        await asyncio.sleep(0.05)
    
    @action("verify_location", depends_on=["schedule_install"])
    async def verify_location(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"📍 [{order_id}] Verifying service location...")
        await asyncio.sleep(0.1)
        return {"location_verified": True, "meter_access": "external"}
    
    @compensate("verify_location")
    async def release_location(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Releasing location...")
        await asyncio.sleep(0.05)
    
    @action("install_hardware", depends_on=["verify_location"])
    async def install_hardware(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"🔧 [{order_id}] Installing meter hardware...")
        await asyncio.sleep(0.3)
        return {"meter_id": f"MTR-{uuid.uuid4().hex[:8].upper()}", "installed": True}
    
    @compensate("install_hardware")
    async def remove_hardware(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Removing hardware...")
        await asyncio.sleep(0.1)
    
    @action("activate_meter", depends_on=["install_hardware"])
    async def activate_meter(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Activate meter - billing starts."""
        order_id = ctx.get("order_id")
        meter_id = ctx.get("meter_id")
        logger.info(f"🔒 [{order_id}] PIVOT: Activating meter {meter_id}...")
        await asyncio.sleep(0.3)
        return {
            "meter_active": True,
            "billing_started": True,
            "activation_time": datetime.now().isoformat(),
            "pivot_reached": True,
        }
    
    @action("verify_readings", depends_on=["activate_meter"])
    async def verify_readings(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"📊 [{order_id}] Verifying initial readings...")
        await asyncio.sleep(0.2)
        return {"readings_valid": True, "initial_kwh": 0}
    
    @action("notify_customer", depends_on=["verify_readings"])
    async def notify_customer(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"📧 [{order_id}] Notifying customer...")
        await asyncio.sleep(0.1)
        return {"customer_notified": True}


async def main():
    print("=" * 80)
    print("⚡ Smart Meter Deployment Saga Demo")
    print("=" * 80)
    
    saga = SmartMeterDeploymentSaga()
    result = await saga.run({
        "order_id": "METER-2026-001",
        "customer_id": "CUST-12345",
        "service_address": "123 Main St",
    })
    
    print(f"\n✅ Deployment Result:")
    print(f"   Meter ID: {result.get('meter_id', 'N/A')}")
    print(f"   Billing Started: {result.get('billing_started', False)}")
    print(f"   Readings Valid: {result.get('readings_valid', False)}")
    print(f"   Pivot Reached: {result.get('pivot_reached', False)}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
