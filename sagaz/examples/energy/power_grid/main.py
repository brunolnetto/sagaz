"""
Power Grid Switching Saga Example

Demonstrates grid connection as pivot point. Once power is flowing,
the connection cannot simply be "undone" - requires safe disconnect.

Pivot Step: close_breaker
    Grid breaker closed, power flowing.
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


class PowerGridSwitchingSaga(Saga):
    """Power grid switching saga with breaker close pivot."""

    saga_name = "power-grid-switching"

    @action("validate_switch_request")
    async def validate_switch_request(self, ctx: SagaContext) -> dict[str, Any]:
        switch_id = ctx.get("switch_id")
        logger.info(f"⚡ [{switch_id}] Validating switch request...")
        await asyncio.sleep(0.1)
        return {"request_valid": True, "safety_check": "passed"}

    @compensate("validate_switch_request")
    async def cancel_request(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('switch_id')}] Cancelling request...")
        await asyncio.sleep(0.05)

    @action("notify_operators", depends_on=["validate_switch_request"])
    async def notify_operators(self, ctx: SagaContext) -> dict[str, Any]:
        switch_id = ctx.get("switch_id")
        logger.info(f"📢 [{switch_id}] Notifying operators...")
        await asyncio.sleep(0.1)
        return {"operators_notified": ["Control Room", "Field Crew"]}

    @compensate("notify_operators")
    async def cancel_notifications(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('switch_id')}] Cancelling notifications...")
        await asyncio.sleep(0.05)

    @action("verify_isolation", depends_on=["notify_operators"])
    async def verify_isolation(self, ctx: SagaContext) -> dict[str, Any]:
        switch_id = ctx.get("switch_id")
        logger.info(f"🔒 [{switch_id}] Verifying circuit isolation...")
        await asyncio.sleep(0.2)
        return {"isolation_verified": True, "grounded": True}

    @compensate("verify_isolation")
    async def release_isolation(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('switch_id')}] Releasing isolation...")
        await asyncio.sleep(0.05)

    @action("close_breaker", depends_on=["verify_isolation"], pivot=True)
    async def close_breaker(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Close breaker - power flows."""
        switch_id = ctx.get("switch_id")
        breaker_id = ctx.get("breaker_id", "BR-001")
        logger.info(f"🔒 [{switch_id}] PIVOT: Closing breaker {breaker_id}...")
        await asyncio.sleep(0.3)
        return {
            "breaker_closed": True,
            "breaker_id": breaker_id,
            "power_flowing": True,
            "voltage_kv": 115.0,
            "pivot_reached": True,
        }

    @action("verify_load", depends_on=["close_breaker"])
    async def verify_load(self, ctx: SagaContext) -> dict[str, Any]:
        switch_id = ctx.get("switch_id")
        logger.info(f"📊 [{switch_id}] Verifying load transfer...")
        await asyncio.sleep(0.2)
        return {"load_verified": True, "load_mw": 45.5}

    @forward_recovery("verify_load")
    async def handle_load_failure(self, ctx: SagaContext, error: Exception) -> RecoveryAction:
        """Forward recovery if load verification fails."""
        logger.warning(f"⚠️ Load verification failed: {error}")
        logger.info("⚡ Initiating controlled load shedding...")
        ctx.set("load_shedding", True)
        return RecoveryAction.RETRY

    @action("update_scada", depends_on=["verify_load"])
    async def update_scada(self, ctx: SagaContext) -> dict[str, Any]:
        switch_id = ctx.get("switch_id")
        logger.info(f"💻 [{switch_id}] Updating SCADA system...")
        await asyncio.sleep(0.1)
        return {"scada_updated": True}


async def main():
    saga = PowerGridSwitchingSaga()
    await saga.run(
        {
            "switch_id": "SWITCH-2026-001",
            "breaker_id": "BR-115KV-001",
            "substation": "SUB-NORTH",
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
