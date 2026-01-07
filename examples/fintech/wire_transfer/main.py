"""
Cross-Border Wire Transfer Saga Example

Demonstrates SWIFT messaging and FX commitment as pivot points.
Once a SWIFT message is sent and funds are debited, the transfer
is committed to the international banking network.

Pivot Steps:
    submit_swift_message: MT103 message sent to correspondent bank
    debit_source_account: Funds committed from sender's account

Forward Recovery:
    - SWIFT confirmation failure: Check gpi tracker, resend with new UETR
    - Notification failure: Retry, manual outreach
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
import uuid

from sagaz import Saga, SagaContext, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SWIFTSimulator:
    """Simulates SWIFT banking network interactions."""
    
    @staticmethod
    async def validate_transfer(
        sender_account: str,
        receiver_bic: str,
        amount: Decimal,
    ) -> dict:
        await asyncio.sleep(0.1)
        return {
            "valid": True,
            "sender_verified": True,
            "receiver_bic_valid": True,
            "sanctions_check": "passed",
        }
    
    @staticmethod
    async def run_compliance_check(
        sender_account: str,
        receiver_account: str,
        amount: Decimal,
    ) -> dict:
        await asyncio.sleep(0.15)
        return {
            "aml_check": "passed",
            "kyc_verified": True,
            "ofac_cleared": True,
            "compliance_id": f"COMP-{uuid.uuid4().hex[:8].upper()}",
        }
    
    @staticmethod
    async def reserve_fx_rate(
        from_currency: str,
        to_currency: str,
        amount: Decimal,
    ) -> dict:
        await asyncio.sleep(0.1)
        rate = Decimal("1.08") if from_currency == "USD" and to_currency == "EUR" else Decimal("1.0")
        return {
            "fx_rate": str(rate),
            "rate_id": f"FX-{uuid.uuid4().hex[:8].upper()}",
            "valid_until": "15 minutes",
            "converted_amount": str(amount / rate),
        }
    
    @staticmethod
    async def submit_swift_mt103(
        transfer_id: str,
        sender_bic: str,
        receiver_bic: str,
        amount: Decimal,
    ) -> dict:
        await asyncio.sleep(0.3)
        return {
            "uetr": str(uuid.uuid4()),
            "mt103_reference": f"MT103-{transfer_id}",
            "status": "sent",
            "sent_at": datetime.now().isoformat(),
        }
    
    @staticmethod
    async def debit_account(account: str, amount: Decimal) -> dict:
        await asyncio.sleep(0.2)
        return {
            "debit_id": f"DEB-{uuid.uuid4().hex[:8].upper()}",
            "amount_debited": str(amount),
            "new_balance": str(Decimal("100000") - amount),
            "debited_at": datetime.now().isoformat(),
        }
    
    @staticmethod
    async def notify_parties(parties: list[str]) -> dict:
        await asyncio.sleep(0.1)
        return {
            "notifications_sent": len(parties),
            "sent_at": datetime.now().isoformat(),
        }


class CrossBorderWireTransferSaga(Saga):
    """
    Cross-border wire transfer saga with SWIFT messaging pivot.
    
    Demonstrates international money transfer with multiple pivot points
    where the SWIFT message submission and account debit commit the
    transaction to the global banking network.
    """
    
    saga_name = "cross-border-wire-transfer"
    
    @action("validate_transfer")
    async def validate_transfer(self, ctx: SagaContext) -> dict[str, Any]:
        transfer_id = ctx.get("transfer_id")
        sender_account = ctx.get("sender_account")
        receiver_bic = ctx.get("receiver_bic")
        amount = Decimal(str(ctx.get("amount", 10000)))
        
        logger.info(f"🔍 [{transfer_id}] Validating transfer...")
        result = await SWIFTSimulator.validate_transfer(sender_account, receiver_bic, amount)
        logger.info(f"✅ [{transfer_id}] Transfer validated, sanctions check: {result['sanctions_check']}")
        return result
    
    @compensate("validate_transfer")
    async def cancel_validation(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('transfer_id')}] Cancelling validation...")
        await asyncio.sleep(0.05)
    
    @action("compliance_check", depends_on=["validate_transfer"])
    async def compliance_check(self, ctx: SagaContext) -> dict[str, Any]:
        transfer_id = ctx.get("transfer_id")
        logger.info(f"🛡️ [{transfer_id}] Running AML/KYC compliance check...")
        result = await SWIFTSimulator.run_compliance_check(
            ctx.get("sender_account"),
            ctx.get("receiver_account"),
            Decimal(str(ctx.get("amount", 10000))),
        )
        logger.info(f"✅ [{transfer_id}] Compliance passed: {result['compliance_id']}")
        return result
    
    @compensate("compliance_check")
    async def cancel_compliance(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('transfer_id')}] Cancelling compliance hold...")
        await asyncio.sleep(0.05)
    
    @action("reserve_fx_rate", depends_on=["compliance_check"])
    async def reserve_fx_rate(self, ctx: SagaContext) -> dict[str, Any]:
        transfer_id = ctx.get("transfer_id")
        logger.info(f"💱 [{transfer_id}] Reserving FX rate...")
        result = await SWIFTSimulator.reserve_fx_rate(
            ctx.get("from_currency", "USD"),
            ctx.get("to_currency", "EUR"),
            Decimal(str(ctx.get("amount", 10000))),
        )
        logger.info(f"✅ [{transfer_id}] FX rate locked: {result['fx_rate']}")
        return result
    
    @compensate("reserve_fx_rate")
    async def release_fx_rate(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('transfer_id')}] Releasing FX rate lock...")
        await asyncio.sleep(0.05)
    
    @action("submit_swift_message", depends_on=["reserve_fx_rate"])
    async def submit_swift_message(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP 1: Submit SWIFT MT103 message."""
        transfer_id = ctx.get("transfer_id")
        logger.info(f"🔒 [{transfer_id}] PIVOT: Submitting SWIFT MT103...")
        result = await SWIFTSimulator.submit_swift_mt103(
            transfer_id,
            ctx.get("sender_bic", "BOFA US"),
            ctx.get("receiver_bic"),
            Decimal(str(ctx.get("amount"))),
        )
        logger.info(f"✅ [{transfer_id}] SWIFT sent! UETR: {result['uetr'][:8]}...")
        return {"pivot_1_reached": True, **result}
    
    @action("debit_source_account", depends_on=["submit_swift_message"])
    async def debit_source_account(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP 2: Debit funds from sender."""
        transfer_id = ctx.get("transfer_id")
        logger.info(f"🔒 [{transfer_id}] PIVOT: Debiting source account...")
        result = await SWIFTSimulator.debit_account(
            ctx.get("sender_account"),
            Decimal(str(ctx.get("amount"))),
        )
        logger.info(f"✅ [{transfer_id}] Funds debited: {result['debit_id']}")
        return {"pivot_2_reached": True, **result}
    
    @action("notify_parties", depends_on=["debit_source_account"])
    async def notify_parties(self, ctx: SagaContext) -> dict[str, Any]:
        transfer_id = ctx.get("transfer_id")
        logger.info(f"📧 [{transfer_id}] Notifying parties...")
        result = await SWIFTSimulator.notify_parties(["sender", "receiver", "compliance"])
        logger.info(f"✅ [{transfer_id}] {result['notifications_sent']} parties notified")
        return result


async def main():
    print("=" * 80)
    print("🌍 Cross-Border Wire Transfer Saga Demo")
    print("=" * 80)
    
    saga = CrossBorderWireTransferSaga()
    
    result = await saga.run({
        "transfer_id": "WIRE-2026-001",
        "sender_account": "ACCT-SENDER-001",
        "receiver_account": "ACCT-RECEIVER-001",
        "sender_bic": "BOFAUS3N",
        "receiver_bic": "DEUTDEFF",
        "amount": Decimal("50000"),
        "from_currency": "USD",
        "to_currency": "EUR",
    })
    
    print(f"\n✅ Transfer Result:")
    print(f"   UETR: {result.get('uetr', 'N/A')}")
    print(f"   Pivot 1 (SWIFT): {result.get('pivot_1_reached', False)}")
    print(f"   Pivot 2 (Debit): {result.get('pivot_2_reached', False)}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
