"""
Property Closing Saga Example

Demonstrates legal commitment as a pivot point. Real estate transactions
have multiple pivot points: escrow release (funds committed) and deed
recording (ownership legally transferred).

Pivot Steps:
    release_escrow: Funds are disbursed to seller
    record_deed: Ownership is legally transferred in county records

Forward Recovery:
    - Recording failure: Retry with county, next business day
    - Key transfer failure: Coordinate with title company
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
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


# =============================================================================
# Saga Definition
# =============================================================================

class PropertyClosingSaga(Saga):
    """
    Real estate property closing saga with legal commitment pivots.

    This saga demonstrates multiple pivot points in a single transaction.
    Both escrow release (funds) and deed recording (ownership) represent
    points of no return that require forward recovery if issues occur.

    Expected context:
        - transaction_id: str - Unique closing transaction ID
        - property_id: str - Property identifier
        - buyer_name: str - Buyer's legal name
        - seller_name: str - Seller's legal name
        - purchase_price: Decimal - Purchase price
        - escrow_amount: Decimal - Total escrow amount
        - seller_account: str - Seller's bank account
        - county: str - County for deed recording
    """

    saga_name = "property-closing"

    # === REVERSIBLE ZONE ===

    @action("title_search")
    async def title_search(self, ctx: SagaContext) -> dict[str, Any]:
        """Search title history for liens and encumbrances."""
        transaction_id = ctx.get("transaction_id")
        property_id = ctx.get("property_id")

        logger.info(f"📜 [{transaction_id}] Running title search for {property_id}...")

        result = await RealEstateSimulator.run_title_search(property_id)

        if result["liens"]:
            msg = f"Title has liens: {result['liens']}"
            raise SagaStepError(msg)

        logger.info(f"✅ [{transaction_id}] Title is CLEAR!")

        return {
            "title_id": result["title_id"],
            "title_status": result["status"],
        }

    @compensate("title_search")
    async def cancel_title_search(self, ctx: SagaContext) -> None:
        """Cancel title search (mark as void)."""
        transaction_id = ctx.get("transaction_id")
        logger.warning(f"↩️ [{transaction_id}] Voiding title search...")
        await asyncio.sleep(0.05)

    @action("appraisal_review", depends_on=["title_search"])
    async def appraisal_review(self, ctx: SagaContext) -> dict[str, Any]:
        """Review property appraisal against purchase price."""
        transaction_id = ctx.get("transaction_id")
        property_id = ctx.get("property_id")
        purchase_price = Decimal(str(ctx.get("purchase_price", 500000)))

        logger.info(f"🏠 [{transaction_id}] Reviewing appraisal...")

        result = await RealEstateSimulator.review_appraisal(property_id, purchase_price)

        if result["status"] != "approved":
            msg = "Appraisal did not meet requirements"
            raise SagaStepError(msg)

        logger.info(
            f"✅ [{transaction_id}] Appraisal approved: "
            f"${Decimal(result['appraised_value']):,.2f}"
        )

        return {
            "appraisal_id": result["appraisal_id"],
            "appraised_value": result["appraised_value"],
            "loan_to_value": result["loan_to_value"],
        }

    @compensate("appraisal_review")
    async def cancel_appraisal(self, ctx: SagaContext) -> None:
        """Cancel appraisal (may incur fee)."""
        transaction_id = ctx.get("transaction_id")
        logger.warning(f"↩️ [{transaction_id}] Cancelling appraisal...")
        await asyncio.sleep(0.05)

    @action("clear_contingencies", depends_on=["appraisal_review"])
    async def clear_contingencies(self, ctx: SagaContext) -> dict[str, Any]:
        """Clear all contingencies (inspection, financing, etc.)."""
        transaction_id = ctx.get("transaction_id")

        logger.info(f"✔️ [{transaction_id}] Clearing contingencies...")

        result = await RealEstateSimulator.clear_contingencies(transaction_id)

        logger.info(
            f"✅ [{transaction_id}] Contingencies cleared: "
            f"{', '.join(result['contingencies_cleared'])}"
        )

        return {
            "contingencies_cleared": result["contingencies_cleared"],
            "contingencies_cleared_at": result["cleared_at"],
        }

    @compensate("clear_contingencies")
    async def reinstate_contingencies(self, ctx: SagaContext) -> None:
        """Reinstate contingency period."""
        transaction_id = ctx.get("transaction_id")
        logger.warning(f"↩️ [{transaction_id}] Reinstating contingencies...")
        await asyncio.sleep(0.05)

    @action("final_walkthrough", depends_on=["clear_contingencies"])
    async def final_walkthrough(self, ctx: SagaContext) -> dict[str, Any]:
        """Conduct final walkthrough of property."""
        transaction_id = ctx.get("transaction_id")
        property_id = ctx.get("property_id")

        logger.info(f"🚶 [{transaction_id}] Conducting final walkthrough...")

        result = await RealEstateSimulator.final_walkthrough(property_id)

        if result["issues_found"]:
            msg = f"Walkthrough issues: {result['issues_found']}"
            raise SagaStepError(msg)

        logger.info(f"✅ [{transaction_id}] Walkthrough complete, property acceptable")

        return {
            "walkthrough_id": result["walkthrough_id"],
            "walkthrough_condition": result["condition"],
        }

    @compensate("final_walkthrough")
    async def void_walkthrough(self, ctx: SagaContext) -> None:
        """Void walkthrough confirmation."""
        transaction_id = ctx.get("transaction_id")
        logger.warning(f"↩️ [{transaction_id}] Voiding walkthrough...")
        await asyncio.sleep(0.05)

    # === PIVOT STEP 1: ESCROW RELEASE ===

    @action("release_escrow", depends_on=["final_walkthrough"], pivot=True)
    async def release_escrow(self, ctx: SagaContext) -> dict[str, Any]:
        """
        🔒 PIVOT STEP 1: Release escrow funds to seller.

        Once escrow is released, funds are transferred to the seller.
        This is a financial point of no return. Reversing requires
        legal action or new transaction.
        """
        transaction_id = ctx.get("transaction_id")
        escrow_amount = Decimal(str(ctx.get("escrow_amount", 500000)))
        seller_account = ctx.get("seller_account", "SELLER-ACCT")

        logger.info(f"🔒 [{transaction_id}] PIVOT 1: Releasing escrow...")
        logger.info(f"   💰 Amount: ${escrow_amount:,.2f}")

        result = await RealEstateSimulator.release_escrow(
            transaction_id,
            escrow_amount,
            seller_account,
        )

        logger.info(
            f"✅ [{transaction_id}] Escrow released! "
            f"Wire ref: {result['wire_reference']}"
        )

        return {
            "escrow_release_id": result["escrow_release_id"],
            "wire_reference": result["wire_reference"],
            "funds_released_at": result["released_at"],
            "pivot_1_reached": True,
        }

    # Note: No compensation for release_escrow - it's a pivot step!
    # Funds are legally the seller's now.

    # === PIVOT STEP 2: DEED RECORDING ===

    @action("record_deed", depends_on=["release_escrow"])
    async def record_deed(self, ctx: SagaContext) -> dict[str, Any]:
        """
        🔒 PIVOT STEP 2: Record deed with county recorder.

        Once the deed is recorded, ownership is LEGALLY transferred.
        This is the definitive ownership change in public records.
        Reversing requires a new sale transaction or legal action.
        """
        transaction_id = ctx.get("transaction_id")
        property_id = ctx.get("property_id")
        buyer_name = ctx.get("buyer_name", "Buyer")
        seller_name = ctx.get("seller_name", "Seller")
        county = ctx.get("county", "Example County")

        logger.info(f"🔒 [{transaction_id}] PIVOT 2: Recording deed in {county}...")

        result = await RealEstateSimulator.record_deed(
            property_id,
            buyer_name,
            seller_name,
            county,
        )

        logger.info(
            f"✅ [{transaction_id}] Deed RECORDED! "
            f"Recording #: {result['recording_number']}"
        )
        logger.info(
            f"   🏡 {seller_name} → {buyer_name}"
        )

        return {
            "deed_id": result["deed_id"],
            "recording_number": result["recording_number"],
            "recorded_at": result["recorded_at"],
            "pivot_2_reached": True,
        }

    @forward_recovery("record_deed")
    async def handle_recording_failure(
        self, ctx: SagaContext, error: Exception
    ) -> RecoveryAction:
        """
        Forward recovery for deed recording failures.

        NOTE: Escrow already released! Must complete recording.

        Strategies:
        1. RETRY - County system back up, try again
        2. RETRY_WITH_ALTERNATE - Correct document issue
        3. MANUAL_INTERVENTION - Title company follows up
        """
        error_type = str(error)

        if "temporarily unavailable" in error_type:
            logger.info("⏳ County system down, scheduling retry...")
            return RecoveryAction.RETRY

        if "document_rejection" in error_type:
            logger.info("📝 Preparing corrected deed...")
            return RecoveryAction.RETRY_WITH_ALTERNATE

        logger.warning("❌ Need title company intervention")
        return RecoveryAction.MANUAL_INTERVENTION

    # === COMMITTED ZONE ===

    @action("transfer_keys", depends_on=["record_deed"])
    async def transfer_keys(self, ctx: SagaContext) -> dict[str, Any]:
        """Transfer keys and access to new owner."""
        transaction_id = ctx.get("transaction_id")
        property_id = ctx.get("property_id")
        buyer_name = ctx.get("buyer_name", "Buyer")

        logger.info(f"🔑 [{transaction_id}] Transferring keys to {buyer_name}...")

        result = await RealEstateSimulator.transfer_keys(property_id, buyer_name)

        logger.info(
            f"✅ [{transaction_id}] Keys transferred! "
            f"{', '.join(result['keys_transferred'])}"
        )

        return {
            "key_transfer_id": result["key_transfer_id"],
            "keys_transferred": result["keys_transferred"],
            "access_updated": result["access_codes_updated"],
        }

    @action("notify_parties", depends_on=["transfer_keys"])
    async def notify_parties(self, ctx: SagaContext) -> dict[str, Any]:
        """Notify all parties of closing completion."""
        transaction_id = ctx.get("transaction_id")
        buyer_name = ctx.get("buyer_name", "Buyer")
        seller_name = ctx.get("seller_name", "Seller")

        parties = [
            buyer_name,
            seller_name,
            "Buyer's Agent",
            "Seller's Agent",
            "Title Company",
            "Mortgage Lender",
        ]

        logger.info(f"📧 [{transaction_id}] Notifying {len(parties)} parties...")

        result = await RealEstateSimulator.notify_parties(transaction_id, parties)

        logger.info(f"✅ [{transaction_id}] All parties notified!")

        return {
            "parties_notified": result["parties"],
            "notifications_sent_at": result["sent_at"],
        }


# =============================================================================
# Demo Scenarios
# =============================================================================

async def main():
    """Run the property closing saga demo."""

    saga = PropertyClosingSaga()

    # Scenario 1: Successful closing

    await saga.run({
        "transaction_id": "CLOSE-2026-001",
        "property_id": "PROP-123456",
        "buyer_name": "Alice Johnson",
        "seller_name": "Bob Smith",
        "purchase_price": Decimal("550000"),
        "escrow_amount": Decimal("550000"),
        "seller_account": "ACCT-SELLER-001",
        "county": "San Francisco County",
    })


    # Scenario 2: Pre-pivot failure

    # Scenario 3: Between pivots



if __name__ == "__main__":
    asyncio.run(main())
