#!/usr/bin/env python3
"""
Replay Compliance Demo — encryption, access control, and GDPR features

Demonstrates financial-grade compliance capabilities:
1. Execute a wire-transfer saga with sensitive PII data
2. Encrypt context fields (SSN, credit-card numbers)
3. Verify role-based access control for replay operations
4. Apply GDPR anonymisation (right to be forgotten)

Usage:
    sagaz demo run replay_compliance
    python -m sagaz.demonstrations.replay_compliance.main
"""

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from sagaz.core.compliance import (
    AccessLevel,
    ComplianceConfig,
    ComplianceManager,
)
from sagaz.core.context import SagaContext
from sagaz.core.replay import ReplayConfig, SnapshotStrategy
from sagaz.core.saga import Saga
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Saga definition
# ============================================================================


class WireTransferSaga(Saga):
    """
    International wire transfer saga with PII and financial data.

    Demonstrates compliance features for regulated industries.
    """

    def __init__(self, **kwargs):
        super().__init__(name="wire-transfer", **kwargs)

    async def build(self):
        await self.add_step("validate_sender", self._validate_sender, self._cancel_validation)
        await self.add_step("check_compliance", self._check_compliance, self._flag_compliance)
        await self.add_step("execute_transfer", self._execute_transfer, self._reverse_transfer)
        await self.add_step("notify_recipient", self._notify_recipient, None)

    async def _validate_sender(self, ctx: SagaContext) -> dict:
        transfer_id = ctx.get("transfer_id")
        # PII fields (SSN, account numbers) are never written to logs
        logger.info(f"[TRANSFER {transfer_id}] Validating sender identity")
        await asyncio.sleep(0.05)
        return {"sender_validated": True, "validation_time": datetime.now().isoformat()}

    async def _cancel_validation(self, result, ctx: SagaContext) -> None:
        transfer_id = ctx.get("transfer_id")
        logger.warning(f"[TRANSFER {transfer_id}] Invalidating sender")
        await asyncio.sleep(0.05)

    async def _check_compliance(self, ctx: SagaContext) -> dict:
        transfer_id = ctx.get("transfer_id")
        amount = ctx.get("amount", 0)
        logger.info(f"[TRANSFER {transfer_id}] Checking AML/KYC for ${amount:,.2f}")
        await asyncio.sleep(0.05)
        return {"compliance_check": "passed", "aml_score": 95, "kyc_verified": True}

    async def _flag_compliance(self, result, ctx: SagaContext) -> None:
        transfer_id = ctx.get("transfer_id")
        logger.warning(f"[TRANSFER {transfer_id}] Flagging compliance check")
        await asyncio.sleep(0.05)

    async def _execute_transfer(self, ctx: SagaContext) -> dict:
        transfer_id = ctx.get("transfer_id")
        amount = ctx.get("amount", 0)
        logger.info(f"[TRANSFER {transfer_id}] Executing ${amount:,.2f} transfer")
        await asyncio.sleep(0.05)
        return {
            "swift_code": f"SWIFT-{transfer_id}",
            "confirmation_number": f"CONF-{datetime.now().timestamp()}",
            "executed_at": datetime.now().isoformat(),
        }

    async def _reverse_transfer(self, result, ctx: SagaContext) -> None:
        transfer_id = ctx.get("transfer_id")
        swift_code = result.get("swift_code") if result else None
        if swift_code:
            logger.warning(f"[TRANSFER {transfer_id}] Reversing transfer {swift_code}")
            await asyncio.sleep(0.05)

    async def _notify_recipient(self, ctx: SagaContext) -> dict:
        transfer_id = ctx.get("transfer_id")
        logger.info(f"[TRANSFER {transfer_id}] Notifying parties")
        await asyncio.sleep(0.05)
        return {"notification_sent": True, "notified_at": datetime.now().isoformat()}


# ============================================================================
# Entry point
# ============================================================================


async def _run():
    """Run the compliance demonstration."""
    print("\n" + "=" * 70)
    print("SAGA REPLAY COMPLIANCE DEMO - Financial Transaction Protection")
    print("=" * 70 + "\n")

    snapshot_storage = InMemorySnapshotStorage()

    compliance_config = ComplianceConfig(
        enable_encryption=True,
        encryption_key="demo-secret-key-123",
        enable_gdpr=True,
        enable_access_control=True,
        enable_audit_trail=True,
    )
    compliance_mgr = ComplianceManager(compliance_config)

    replay_config = ReplayConfig(
        enable_snapshots=True,
        snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
        retention_days=2555,  # 7 years for financial compliance
    )

    transfer_context = {
        "transfer_id": "TXN-87654",
        "sender_name": "John Smith",
        "sender_ssn": "123-45-6789",
        "sender_account": "****1234",
        "receiver_name": "Jane Doe",
        "receiver_account": "****5678",
        "amount": 50000.00,
        "currency": "USD",
        "purpose": "Business payment",
    }

    # PHASE 1: Execute saga
    print("💳 PHASE 1: Wire Transfer Execution")
    print("-" * 70)

    saga = WireTransferSaga(replay_config=replay_config, snapshot_storage=snapshot_storage)
    for key, value in transfer_context.items():
        saga.context.set(key, value)
    await saga.build()
    await saga.execute()

    print("✓ Transfer completed")
    print(f"  Saga ID:       {saga.saga_id}")
    print(f"  Transfer ID:   {transfer_context['transfer_id']}")
    print(f"  Amount:        ${transfer_context['amount']:,.2f} {transfer_context['currency']}")
    print()

    saga_id = saga.saga_id

    # PHASE 2: Encrypt sensitive fields
    print("🔐 PHASE 2: Context Encryption (PII Protection)")
    print("-" * 70)

    sensitive_fields = {
        "sender_ssn": "123-45-6789",
        "credit_card": "4532-1234-5678-9010",
        "routing_number": "021000021",
    }

    print("Original sensitive data:")
    for field, value in sensitive_fields.items():
        print(f"   {field}: {value}")

    print("\nEncrypted data:")
    encrypted_data = {}
    for field, value in sensitive_fields.items():
        encrypted = compliance_mgr.encrypt_context({field: value})[field]
        if isinstance(encrypted, dict) and encrypted.get("_encrypted"):
            encrypted_str = encrypted["_value"]
        else:
            encrypted_str = str(encrypted)
        encrypted_data[field] = encrypted_str
        preview = encrypted_str[:32] + "..." if len(encrypted_str) > 32 else encrypted_str
        print(f"   {field}: {preview}")

    print("\nDecrypted data (authorized access):")
    for field, encrypted_str in encrypted_data.items():
        decrypted_context = compliance_mgr.decrypt_context(
            {field: {"_encrypted": True, "_value": encrypted_str}}
        )
        print(f"   {field}: {decrypted_context[field]}")

    print()

    # PHASE 3: Access control
    print("👮 PHASE 3: Access Control")
    print("-" * 70)

    users = [
        ("alice@bank.com", AccessLevel.ADMIN),
        ("bob@bank.com", AccessLevel.REPLAY),
        ("charlie@bank.com", AccessLevel.READ),
    ]

    print("Checking replay permissions:\n")
    for user, level in users:
        has_access = compliance_mgr.check_access(user, level)
        status = "✓ ALLOWED" if has_access else "✗ DENIED"
        print(f"   {user:<25} Level: {level.value:<10} → {status}")
        compliance_mgr.create_audit_log(
            operation="check_access",
            user_id=user,
            saga_id=UUID(saga_id),
            details={"level": level.value, "allowed": has_access},
        )

    print()

    # PHASE 4: GDPR anonymisation
    print("🔒 PHASE 4: GDPR Data Anonymization")
    print("-" * 70)

    print("Original context with PII:")
    print(f"   sender_ssn: {transfer_context['sender_ssn']}")
    print(f"   sender_name: {transfer_context['sender_name']}")

    anonymized = compliance_mgr.anonymize_context(transfer_context)
    print("\nAnonymized context (irreversible):")
    print(f"   sender_ssn: {anonymized['sender_ssn']}")
    print(f"   sender_name: {anonymized['sender_name']}")
    print("\n   (i) Sensitive fields are hashed for privacy compliance")
    print()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("✓ Demonstrated context encryption for PII protection")
    print("✓ Implemented access control for replay operations")
    print("✓ Showed GDPR-compliant data anonymization")
    print("✓ Created audit trail for all compliance operations")
    print("=" * 70 + "\n")


def main():
    """Main entry point for sagaz demo run replay_compliance."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
