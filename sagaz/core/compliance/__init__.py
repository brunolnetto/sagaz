"""
Compliance Features for Saga Replay

Implements security and compliance features:
- Context encryption for sensitive data
- GDPR support (right to be forgotten)
- Access control for replay operations
- Audit trail management

Example:
    >>> from sagaz.core.compliance import ComplianceManager, ComplianceConfig, AccessLevel
    >>> config = ComplianceConfig(
    ...     enable_encryption=True,
    ...     encryption_key="your-secret-key",
    ...     enable_gdpr=True,
    ... )
    >>> manager = ComplianceManager(config)
    >>> encrypted = manager.encrypt_context({"ssn": "123-45-6789"})
    >>> decrypted = manager.decrypt_context(encrypted)
"""

from dataclasses import dataclass

from sagaz.core.compliance._access import AccessLevel
from sagaz.core.compliance._access import check_access
from sagaz.core.compliance._access import delete_user_data
from sagaz.core.compliance._audit import anonymize_context
from sagaz.core.compliance._audit import create_audit_log
from sagaz.core.compliance._encryption import decrypt_context
from sagaz.core.compliance._encryption import encrypt_context
from sagaz.core.compliance._encryption import is_sensitive
from sagaz.core.compliance._encryption import simple_decrypt
from sagaz.core.compliance._encryption import simple_encrypt


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

    def encrypt_context(self, context: dict) -> dict:
        """Encrypt sensitive context data."""
        if not self.config.enable_encryption:
            return context
        return encrypt_context(context, self.config.encryption_key)

    def decrypt_context(self, context: dict) -> dict:
        """Decrypt context data"""
        if not self.config.enable_encryption:
            return context
        return decrypt_context(context, self.config.encryption_key)

    def check_access(self, user_id: str, required_level: AccessLevel | None = None) -> bool:
        """Check if user has required access level."""
        return check_access(
            user_id,
            self.config.enable_access_control,
            required_level,
            self.config.required_access_level,
        )

    async def delete_user_data(
        self, user_id: str, snapshot_storage, reason: str = "GDPR right to be forgotten"
    ) -> int:
        """Delete all snapshots and replay history for a user (GDPR compliance)."""
        return await delete_user_data(user_id, snapshot_storage, self.config.enable_gdpr, reason)

    def create_audit_log(
        self, operation: str, user_id: str, saga_id, details: dict | None = None
    ) -> dict:
        """Create audit log entry for compliance."""
        return create_audit_log(
            operation,
            user_id,
            saga_id,
            self.config.enable_audit_trail,
            self.config.log_all_operations,
            details,
        )

    def anonymize_context(self, context: dict) -> dict:
        """Anonymize sensitive data in context (for GDPR/privacy)."""
        return anonymize_context(context)

    # Backward compatibility: expose private methods as is_sensitive, simple_encrypt, simple_decrypt
    def _is_sensitive(self, key: str) -> bool:
        """Backward compatible: determine if a context key contains sensitive data"""
        return is_sensitive(key)

    def _simple_encrypt(self, text: str) -> str:
        """Backward compatible: simple encryption"""
        return simple_encrypt(text, self.config.encryption_key)

    def _simple_decrypt(self, encrypted_hex: str) -> str:
        """Backward compatible: simple decryption"""
        return simple_decrypt(encrypted_hex, self.config.encryption_key)


__all__ = [
    "AccessLevel",
    "ComplianceConfig",
    "ComplianceManager",
    "anonymize_context",
    "check_access",
    "create_audit_log",
    "decrypt_context",
    "delete_user_data",
    "encrypt_context",
    "is_sensitive",
    "simple_decrypt",
    "simple_encrypt",
]
