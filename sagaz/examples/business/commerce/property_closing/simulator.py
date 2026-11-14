"""
Simulated real estate transaction systems for the property closing example.
"""

import asyncio
from datetime import datetime
from decimal import Decimal

from sagaz.core.exceptions import SagaStepError


class RealEstateSimulator:
    """Simulates real estate transaction systems."""

    @staticmethod
    async def run_title_search(property_id: str) -> dict:
        """Search title history for liens, encumbrances."""
        await asyncio.sleep(0.2)
        return {
            "title_id": f"TITLE-{property_id}",
            "status": "clear",
            "liens": [],
            "encumbrances": [],
            "owner_history": [
                {"name": "Previous Owner", "acquired": "2015-01-15"},
            ],
        }

    @staticmethod
    async def review_appraisal(property_id: str, purchase_price: Decimal) -> dict:
        """Review property appraisal against purchase price."""
        await asyncio.sleep(0.15)
        appraised_value = purchase_price * Decimal("1.02")  # 2% above purchase
        return {
            "appraisal_id": f"APPR-{property_id}",
            "appraised_value": str(appraised_value),
            "purchase_price": str(purchase_price),
            "loan_to_value": 0.80,
            "status": "approved",
        }

    @staticmethod
    async def clear_contingencies(transaction_id: str) -> dict:
        """Clear all contingencies (inspection, financing, etc.)."""
        await asyncio.sleep(0.1)
        return {
            "contingencies_cleared": [
                "inspection",
                "financing",
                "appraisal",
                "title",
            ],
            "cleared_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def final_walkthrough(property_id: str) -> dict:
        """Conduct final walkthrough of property."""
        await asyncio.sleep(0.1)
        return {
            "walkthrough_id": f"WALK-{property_id}",
            "condition": "acceptable",
            "issues_found": [],
            "completed_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def release_escrow(
        transaction_id: str,
        escrow_amount: Decimal,
        seller_account: str,
    ) -> dict:
        """Release escrow funds to seller - IRREVERSIBLE."""
        await asyncio.sleep(0.3)
        return {
            "escrow_release_id": f"ESC-{transaction_id}",
            "amount_released": str(escrow_amount),
            "recipient": seller_account,
            "wire_reference": f"WIRE-{datetime.now().strftime('%H%M%S')}",
            "released_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def record_deed(
        property_id: str,
        buyer_name: str,
        seller_name: str,
        county: str,
    ) -> dict:
        """Record deed with county recorder - LEGAL TRANSFER."""
        await asyncio.sleep(0.4)

        # Simulate occasional county office issues
        import random

        if random.random() < 0.05:  # 5% chance of recording delay
            msg = "County recorder system temporarily unavailable"
            raise SagaStepError(msg)

        return {
            "deed_id": f"DEED-{property_id}",
            "recording_number": f"2026-{random.randint(100000, 999999)}",
            "county": county,
            "grantor": seller_name,
            "grantee": buyer_name,
            "recorded_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def transfer_keys(property_id: str, buyer_id: str) -> dict:
        """Transfer keys and access to new owner."""
        await asyncio.sleep(0.1)
        return {
            "key_transfer_id": f"KEY-{property_id}",
            "keys_transferred": ["front_door", "garage", "mailbox"],
            "access_codes_updated": True,
            "transferred_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def notify_parties(transaction_id: str, parties: list[str]) -> dict:
        """Notify all parties of closing completion."""
        await asyncio.sleep(0.1)
        return {
            "notifications_sent": len(parties),
            "parties": parties,
            "sent_at": datetime.now().isoformat(),
        }
