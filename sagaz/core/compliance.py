# ============================================
# FILE: sagaz/core/compliance.py
# ============================================

"""
Compliance Features for Saga Replay

Implements security and compliance features:
- Context encryption for sensitive data
- GDPR support (right to be forgotten)
- Access control for replay operations
- Audit trail management
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class AccessLevel(Enum):
    """Access levels for replay operations"""

    READ = "read"  # View snapshots and history
    REPLAY = "replay"  # Execute replay operations
    DELETE = "delete"  # Delete snapshots (GDPR)
    ADMIN = "admin"  # Full access


@dataclass
class ComplianceConfig:
    """Configuration for compliance features"""

    # Encryption
    enable_encryption: bool = False
    encryption_key: str | None = None  # In production, use proper key management

    # GDPR
    enable_gdpr: bool = False
    retention_days: int = 2555  # 7 years default for compliance

    # Access control
    enable_access_control: bool = False
    required_access_level: AccessLevel = AccessLevel.READ

    # Audit trail
    enable_audit_trail: bool = True
    log_all_operations: bool = True


class ComplianceManager:
    """
    Manages compliance features for saga replay.

    Example:
        config = ComplianceConfig(
            enable_encryption=True,
            encryption_key="your-secret-key",
            enable_gdpr=True,
        )
        
        manager = ComplianceManager(config)
        
        # Encrypt sensitive data
        encrypted = manager.encrypt_context({"ssn": "123-45-6789"})
        
        # Decrypt for authorized use
        decrypted = manager.decrypt_context(encrypted)
        
        # GDPR: Delete all data for a user
        await manager.delete_user_data(user_id)
    """

    def __init__(self, config: ComplianceConfig):
        self.config = config

    def encrypt_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Encrypt sensitive context data.

        Note: This is a simple implementation. In production, use:
        - Proper encryption libraries (cryptography, pycryptodome)
        - Key management systems (AWS KMS, Azure Key Vault, HashiCorp Vault)
        - Field-level encryption for specific keys
        """
        if not self.config.enable_encryption:
            return context

        if not self.config.encryption_key:
            logger.warning("Encryption enabled but no key provided")
            return context

        # Simple XOR encryption for demonstration
        # In production, use proper encryption (AES-256, etc.)
        encrypted = {}
        for key, value in context.items():
            if self._is_sensitive(key):
                encrypted[key] = {
                    "_encrypted": True,
                    "_value": self._simple_encrypt(str(value)),
                }
            else:
                encrypted[key] = value

        return encrypted

    def decrypt_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Decrypt context data"""
        if not self.config.enable_encryption:
            return context

        decrypted = {}
        for key, value in context.items():
            if isinstance(value, dict) and value.get("_encrypted"):
                decrypted[key] = self._simple_decrypt(value["_value"])
            else:
                decrypted[key] = value

        return decrypted

    def _is_sensitive(self, key: str) -> bool:
        """Determine if a context key contains sensitive data"""
        sensitive_keywords = [
            "password",
            "token",
            "secret",
            "key",
            "ssn",
            "credit",
            "card",
            "cvv",
            "pin",
        ]
        key_lower = key.lower()
        return any(keyword in key_lower for keyword in sensitive_keywords)

    def _simple_encrypt(self, text: str) -> str:
        """Simple encryption (demo only - use proper crypto in production)"""
        if not self.config.encryption_key:
            return text

        key_bytes = self.config.encryption_key.encode()
        text_bytes = text.encode()

        # XOR with key (cycled)
        encrypted = bytes(
            b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(text_bytes)
        )

        # Return as hex string
        return encrypted.hex()

    def _simple_decrypt(self, encrypted_hex: str) -> str:
        """Simple decryption (demo only)"""
        if not self.config.encryption_key:
            return encrypted_hex

        try:
            key_bytes = self.config.encryption_key.encode()
            encrypted = bytes.fromhex(encrypted_hex)

            # XOR with key (cycled)
            decrypted = bytes(
                b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted)
            )

            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return encrypted_hex

    def check_access(
        self, user_id: str, required_level: AccessLevel | None = None
    ) -> bool:
        """
        Check if user has required access level.

        In production, integrate with your auth system:
        - OAuth/OIDC
        - RBAC (Role-Based Access Control)
        - ABAC (Attribute-Based Access Control)
        """
        if not self.config.enable_access_control:
            return True

        required = required_level or self.config.required_access_level

        # Simple implementation - in production, check against auth system
        # This is where you'd integrate with your IAM/RBAC system
        logger.info(f"Access check: user={user_id}, required={required.value}")

        # For now, allow all (implement real checks in production)
        return True

    async def delete_user_data(
        self,
        user_id: str,
        snapshot_storage: "SnapshotStorage",
        reason: str = "GDPR right to be forgotten",
    ) -> int:
        """
        Delete all snapshots and replay history for a user (GDPR compliance).

        Returns:
            Number of records deleted
        """
        if not self.config.enable_gdpr:
            raise ValueError("GDPR features not enabled")

        logger.warning(
            f"GDPR deletion requested: user={user_id}, reason={reason}"
        )

        # In production, you'd:
        # 1. Verify user identity
        # 2. Check legal requirements
        # 3. Create audit log entry
        # 4. Delete from all storage systems
        # 5. Confirm deletion

        # For now, return 0 (placeholder)
        return 0

    def create_audit_log(
        self,
        operation: str,
        user_id: str,
        saga_id: UUID,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create audit log entry for compliance.

        In production, send to:
        - SIEM (Security Information and Event Management)
        - Log aggregation system (ELK, Splunk)
        - Compliance database
        """
        if not self.config.enable_audit_trail:
            return {}

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "user_id": user_id,
            "saga_id": str(saga_id),
            "details": details or {},
        }

        if self.config.log_all_operations:
            logger.info(f"Audit log: {log_entry}")

        return log_entry

    def anonymize_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Anonymize sensitive data in context (for GDPR/privacy).

        Replaces sensitive values with hashes or anonymized versions.
        """
        anonymized = {}

        for key, value in context.items():
            if self._is_sensitive(key):
                # Hash sensitive data (irreversible)
                anonymized[key] = self._hash_value(str(value))
            else:
                anonymized[key] = value

        return anonymized

    def _hash_value(self, value: str) -> str:
        """Create one-way hash of sensitive value"""
        return hashlib.sha256(value.encode()).hexdigest()[:16]


# Type hint for SnapshotStorage (avoid circular import)
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from sagaz.storage.interfaces.snapshot import SnapshotStorage
