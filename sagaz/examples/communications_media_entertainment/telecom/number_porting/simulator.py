"""
Simulated telecom carrier systems for the number porting example.
"""

import asyncio
from datetime import datetime

from sagaz.core.exceptions import SagaStepError


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
