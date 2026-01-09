"""
SIM Provisioning Saga Example

Demonstrates SIM activation as pivot point. Once the SIM is activated
on the network, the subscription is live and billing starts.

Pivot Step: activate_sim
    SIM activated, billing starts.
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


class SIMProvisioningSaga(Saga):
    """SIM provisioning saga with activation pivot."""

    saga_name = "sim-provisioning"

    @action("validate_order")
    async def validate_order(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"📋 [{order_id}] Validating SIM order...")
        await asyncio.sleep(0.1)
        return {"order_valid": True, "sim_type": "eSIM"}

    @compensate("validate_order")
    async def cancel_order(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Cancelling order...")
        await asyncio.sleep(0.05)

    @action("verify_identity", depends_on=["validate_order"])
    async def verify_identity(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"🪪 [{order_id}] Verifying customer identity...")
        await asyncio.sleep(0.15)
        return {"identity_verified": True, "kyc_passed": True}

    @compensate("verify_identity")
    async def void_identity_check(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Voiding identity check...")
        await asyncio.sleep(0.05)

    @action("assign_msisdn", depends_on=["verify_identity"])
    async def assign_msisdn(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"📱 [{order_id}] Assigning phone number...")
        await asyncio.sleep(0.1)
        import random
        msisdn = f"+1-555-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
        return {"msisdn": msisdn, "number_type": "new"}

    @compensate("assign_msisdn")
    async def release_msisdn(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Releasing phone number...")
        await asyncio.sleep(0.05)

    @action("provision_hlr", depends_on=["assign_msisdn"])
    async def provision_hlr(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"🏢 [{order_id}] Provisioning in HLR...")
        await asyncio.sleep(0.2)
        return {"hlr_provisioned": True, "imsi": f"310{uuid.uuid4().hex[:12]}"}

    @compensate("provision_hlr")
    async def deprovision_hlr(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Deprovisioning HLR...")
        await asyncio.sleep(0.1)

    @action("activate_sim", depends_on=["provision_hlr"], pivot=True)
    async def activate_sim(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Activate SIM - billing starts."""
        order_id = ctx.get("order_id")
        iccid = ctx.get("iccid", f"8901260{uuid.uuid4().hex[:13]}")
        logger.info(f"🔒 [{order_id}] PIVOT: Activating SIM {iccid[:12]}...")
        await asyncio.sleep(0.3)
        return {
            "sim_activated": True,
            "iccid": iccid,
            "activation_time": datetime.now().isoformat(),
            "billing_started": True,
            "pivot_reached": True,
        }

    @action("configure_services", depends_on=["activate_sim"])
    async def configure_services(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        plan = ctx.get("plan", "Unlimited")
        logger.info(f"⚙️ [{order_id}] Configuring services ({plan})...")
        await asyncio.sleep(0.15)
        return {"services_configured": True, "plan": plan, "data_cap_gb": "unlimited"}

    @forward_recovery("configure_services")
    async def handle_service_failure(self, ctx: SagaContext, error: Exception) -> RecoveryAction:
        """Forward recovery if service config fails after activation."""
        order_id = ctx.get("order_id")
        logger.warning(f"⚠️ [{order_id}] Service config failed: {error}")

        retry_count = ctx.get("_service_retries", 0)
        if retry_count < 3:
            ctx.set("_service_retries", retry_count + 1)
            await asyncio.sleep(0.5)
            return RecoveryAction.RETRY

        return RecoveryAction.MANUAL_INTERVENTION

    @action("send_welcome", depends_on=["configure_services"])
    async def send_welcome(self, ctx: SagaContext) -> dict[str, Any]:
        order_id = ctx.get("order_id")
        logger.info(f"📧 [{order_id}] Sending welcome message...")
        await asyncio.sleep(0.1)
        return {"welcome_sent": True}


async def main():

    saga = SIMProvisioningSaga()
    await saga.run({
        "order_id": "SIM-2026-001",
        "customer_id": "CUST-12345",
        "plan": "Unlimited Plus",
    })



if __name__ == "__main__":
    asyncio.run(main())
