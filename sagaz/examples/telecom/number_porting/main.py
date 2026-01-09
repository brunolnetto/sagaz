"""
Mobile Number Porting Saga Example

Demonstrates regulatory action as a pivot point. Once a number port is
executed in the NPAC (Number Portability Administration Center), the
number is officially transferred and cannot be simply "undone".

Pivot Step: execute_port
    NPAC database updated with new carrier assignment.
    Regulatory action recorded in national database.
    Port-back requires new full port request.

Forward Recovery:
    - Activation failure: Retry provisioning, expedite SIM
    - Routing failure: Update carrier tables, escalate to NOC
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

class TelecomSimulator:
    """Simulates telecom carrier and regulatory systems."""

    @staticmethod
    async def submit_port_request(
        phone_number: str,
        new_carrier: str,
        account_number: str,
    ) -> dict:
        """Submit port request to carrier system."""
        await asyncio.sleep(0.1)
        return {
            "port_request_id": f"PORT-{phone_number[-4:]}",
            "phone_number": phone_number,
            "new_carrier": new_carrier,
            "status": "submitted",
            "submitted_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def validate_customer(
        phone_number: str,
        account_number: str,
        account_pin: str,
    ) -> dict:
        """Validate customer identity and account ownership."""
        await asyncio.sleep(0.1)
        return {
            "validated": True,
            "customer_name": "John Doe",
            "account_verified": True,
            "pin_verified": True,
        }

    @staticmethod
    async def verify_with_donor_carrier(
        phone_number: str,
        donor_carrier: str,
    ) -> dict:
        """Verify port request with donor (losing) carrier."""
        await asyncio.sleep(0.2)

        # Simulate occasional rejections
        import random
        if random.random() < 0.05:  # 5% rejection rate
            msg = "Donor carrier rejected: Account balance pending"
            raise SagaStepError(msg)

        return {
            "donor_verified": True,
            "donor_carrier": donor_carrier,
            "release_date": datetime.now().isoformat(),
            "porting_authorization_code": f"PAC-{random.randint(100000, 999999)}",
        }

    @staticmethod
    async def execute_port_in_npac(
        phone_number: str,
        new_carrier: str,
        donor_carrier: str,
    ) -> dict:
        """Execute port in NPAC database - REGULATORY ACTION."""
        await asyncio.sleep(0.3)

        import random
        return {
            "npac_transaction_id": f"NPAC-{random.randint(1000000, 9999999)}",
            "lrn": f"LRN-{new_carrier[:3].upper()}-{phone_number[-4:]}",
            "effective_date": datetime.now().isoformat(),
            "status": "ported",
            "old_carrier": donor_carrier,
            "new_carrier": new_carrier,
        }

    @staticmethod
    async def activate_on_new_carrier(
        phone_number: str,
        sim_iccid: str,
    ) -> dict:
        """Activate number on new carrier's network."""
        await asyncio.sleep(0.2)

        import random
        if random.random() < 0.08:  # 8% provisioning delay
            msg = "Provisioning delay: SIM not yet active"
            raise SagaStepError(msg)

        return {
            "activation_id": f"ACT-{phone_number[-4:]}",
            "sim_iccid": sim_iccid,
            "imsi": f"310{random.randint(100, 999)}{random.randint(1000000000, 9999999999)}",
            "status": "active",
            "activated_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def update_routing_tables(
        phone_number: str,
        lrn: str,
    ) -> dict:
        """Update SS7/routing tables for call routing."""
        await asyncio.sleep(0.1)
        return {
            "routing_updated": True,
            "lrn": lrn,
            "routing_regions": ["US-EAST", "US-WEST", "US-CENTRAL"],
            "updated_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def notify_customer(
        phone_number: str,
        customer_email: str,
    ) -> dict:
        """Send port completion notification to customer."""
        await asyncio.sleep(0.05)
        return {
            "notification_sent": True,
            "channel": "email",
            "recipient": customer_email,
            "sent_at": datetime.now().isoformat(),
        }


# =============================================================================
# Saga Definition
# =============================================================================

class MobileNumberPortingSaga(Saga):
    """
    Mobile number porting saga with regulatory action pivot.

    This saga demonstrates FCC-regulated number porting where the
    NPAC database update represents a regulatory point of no return.
    Once the number is ported, it requires a new port request to reverse.

    Expected context:
        - port_request_id: str - Unique port request identifier
        - phone_number: str - Number being ported (e.g., "+1-555-123-4567")
        - customer_name: str - Customer's full name
        - account_number: str - Account number with donor carrier
        - account_pin: str - Account PIN for verification
        - donor_carrier: str - Current carrier (losing the number)
        - new_carrier: str - New carrier (gaining the number)
        - customer_email: str - Customer email for notifications
        - sim_iccid: str - New SIM card ICCID
    """

    saga_name = "mobile-number-porting"

    # === REVERSIBLE ZONE ===

    @action("submit_port_request")
    async def submit_port_request(self, ctx: SagaContext) -> dict[str, Any]:
        """Submit port request to carrier system."""
        port_id = ctx.get("port_request_id", "PORT-001")
        phone_number = ctx.get("phone_number")
        new_carrier = ctx.get("new_carrier")
        account_number = ctx.get("account_number")

        logger.info(f"📱 [{port_id}] Submitting port request for {phone_number}...")

        result = await TelecomSimulator.submit_port_request(
            phone_number,
            new_carrier,
            account_number,
        )

        logger.info(f"✅ [{port_id}] Port request submitted: {result['port_request_id']}")

        return {
            "port_request_id": result["port_request_id"],
            "submission_status": result["status"],
        }

    @compensate("submit_port_request")
    async def cancel_port_request(self, ctx: SagaContext) -> None:
        """Cancel pending port request."""
        port_id = ctx.get("port_request_id", "PORT-001")
        logger.warning(f"↩️ [{port_id}] Cancelling port request...")
        await asyncio.sleep(0.05)

    @action("validate_customer", depends_on=["submit_port_request"])
    async def validate_customer(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate customer identity and account ownership."""
        port_id = ctx.get("port_request_id", "PORT-001")
        phone_number = ctx.get("phone_number")
        account_number = ctx.get("account_number")
        account_pin = ctx.get("account_pin", "1234")

        logger.info(f"🔐 [{port_id}] Validating customer identity...")

        result = await TelecomSimulator.validate_customer(
            phone_number,
            account_number,
            account_pin,
        )

        if not result["validated"]:
            msg = "Customer validation failed"
            raise SagaStepError(msg)

        logger.info(f"✅ [{port_id}] Customer validated: {result['customer_name']}")

        return {
            "customer_validated": result["validated"],
            "customer_name": result["customer_name"],
        }

    @compensate("validate_customer")
    async def invalidate_customer(self, ctx: SagaContext) -> None:
        """Invalidate customer verification."""
        port_id = ctx.get("port_request_id", "PORT-001")
        logger.warning(f"↩️ [{port_id}] Invalidating customer verification...")
        await asyncio.sleep(0.05)

    @action("verify_with_donor", depends_on=["validate_customer"])
    async def verify_with_donor(self, ctx: SagaContext) -> dict[str, Any]:
        """Verify port request with donor (losing) carrier."""
        port_id = ctx.get("port_request_id", "PORT-001")
        phone_number = ctx.get("phone_number")
        donor_carrier = ctx.get("donor_carrier")

        logger.info(f"📞 [{port_id}] Verifying with donor carrier ({donor_carrier})...")

        result = await TelecomSimulator.verify_with_donor_carrier(
            phone_number,
            donor_carrier,
        )

        logger.info(
            f"✅ [{port_id}] Donor verified! "
            f"PAC: {result['porting_authorization_code']}"
        )

        return {
            "donor_verified": result["donor_verified"],
            "porting_authorization_code": result["porting_authorization_code"],
        }

    @compensate("verify_with_donor")
    async def cancel_donor_verification(self, ctx: SagaContext) -> None:
        """Cancel donor carrier verification."""
        port_id = ctx.get("port_request_id", "PORT-001")
        logger.warning(f"↩️ [{port_id}] Cancelling donor verification...")
        await asyncio.sleep(0.1)

    # === PIVOT STEP ===

    @action("execute_port", depends_on=["verify_with_donor"], pivot=True)
    async def execute_port(self, ctx: SagaContext) -> dict[str, Any]:
        """
        🔒 PIVOT STEP: Execute port in NPAC database.

        Once this step completes, the number is OFFICIALLY PORTED
        in the national number portability database. This is a
        regulatory action that cannot be simply "undone" - reversing
        requires a new full port request.
        """
        port_id = ctx.get("port_request_id", "PORT-001")
        phone_number = ctx.get("phone_number")
        new_carrier = ctx.get("new_carrier")
        donor_carrier = ctx.get("donor_carrier")

        logger.info(f"🔒 [{port_id}] PIVOT: Executing port in NPAC...")
        logger.info(f"   📱 {phone_number}: {donor_carrier} → {new_carrier}")

        result = await TelecomSimulator.execute_port_in_npac(
            phone_number,
            new_carrier,
            donor_carrier,
        )

        logger.info(
            f"✅ [{port_id}] PORT COMPLETE! "
            f"NPAC TX: {result['npac_transaction_id']}"
        )

        return {
            "npac_transaction_id": result["npac_transaction_id"],
            "lrn": result["lrn"],
            "port_effective_date": result["effective_date"],
            "pivot_reached": True,
        }

    # Note: No compensation for execute_port - it's a pivot step!
    # NPAC porting is official. Reversal requires new port request.

    # === COMMITTED ZONE (Forward Recovery Only) ===

    @action("activate_new_carrier", depends_on=["execute_port"])
    async def activate_new_carrier(self, ctx: SagaContext) -> dict[str, Any]:
        """Activate number on new carrier's network."""
        port_id = ctx.get("port_request_id", "PORT-001")
        phone_number = ctx.get("phone_number")
        sim_iccid = ctx.get("sim_iccid", "8901260123456789012")

        logger.info(f"📶 [{port_id}] Activating on new carrier...")

        result = await TelecomSimulator.activate_on_new_carrier(phone_number, sim_iccid)

        logger.info(f"✅ [{port_id}] Activated! IMSI: {result['imsi'][:10]}...")

        return {
            "activation_id": result["activation_id"],
            "imsi": result["imsi"],
            "activation_status": result["status"],
        }

    @forward_recovery("activate_new_carrier")
    async def handle_activation_failure(
        self, ctx: SagaContext, error: Exception
    ) -> RecoveryAction:
        """
        Forward recovery for activation failures.

        NOTE: Port already executed! Must complete activation.

        Strategies:
        1. RETRY - Provisioning system may just be slow
        2. RETRY_WITH_ALTERNATE - Expedite SIM or use eSIM
        3. MANUAL_INTERVENTION - Send to NOC for manual activation
        """
        retry_count = ctx.get("activation_retry_count", 0)

        if retry_count < 3:
            ctx.set("activation_retry_count", retry_count + 1)
            logger.info(f"⏳ Retrying activation (attempt {retry_count + 1}/3)...")
            return RecoveryAction.RETRY

        if ctx.get("sim_not_ready"):
            logger.info("📦 Expediting SIM shipment...")
            return RecoveryAction.RETRY_WITH_ALTERNATE

        logger.warning("❌ Escalating to NOC for manual activation")
        return RecoveryAction.MANUAL_INTERVENTION

    @action("update_routing", depends_on=["activate_new_carrier"])
    async def update_routing(self, ctx: SagaContext) -> dict[str, Any]:
        """Update SS7/routing tables for call routing."""
        port_id = ctx.get("port_request_id", "PORT-001")
        phone_number = ctx.get("phone_number")
        lrn = ctx.get("lrn")

        logger.info(f"🔀 [{port_id}] Updating routing tables...")

        result = await TelecomSimulator.update_routing_tables(phone_number, lrn)

        logger.info(
            f"✅ [{port_id}] Routing updated for: "
            f"{', '.join(result['routing_regions'])}"
        )

        return {
            "routing_updated": result["routing_updated"],
            "routing_regions": result["routing_regions"],
        }

    @action("notify_customer", depends_on=["update_routing"])
    async def notify_customer(self, ctx: SagaContext) -> dict[str, Any]:
        """Send port completion notification to customer."""
        port_id = ctx.get("port_request_id", "PORT-001")
        phone_number = ctx.get("phone_number")
        customer_email = ctx.get("customer_email", "customer@example.com")

        logger.info(f"📧 [{port_id}] Notifying customer...")

        result = await TelecomSimulator.notify_customer(phone_number, customer_email)

        logger.info(f"✅ [{port_id}] Customer notified at {customer_email}")

        return {
            "notification_sent": result["notification_sent"],
            "notification_channel": result["channel"],
        }


# =============================================================================
# Demo Scenarios
# =============================================================================

async def main():
    """Run the mobile number porting saga demo."""

    saga = MobileNumberPortingSaga()

    # Scenario 1: Successful port

    await saga.run({
        "port_request_id": "PORT-2026-001",
        "phone_number": "+1-555-123-4567",
        "customer_name": "John Doe",
        "account_number": "ACCT-987654",
        "account_pin": "1234",
        "donor_carrier": "OldMobile",
        "new_carrier": "NewTelco",
        "customer_email": "john.doe@email.com",
        "sim_iccid": "8901260123456789012",
    })


    # Scenario 2: Pre-pivot failure

    # Scenario 3: Post-pivot scenarios



if __name__ == "__main__":
    asyncio.run(main())
