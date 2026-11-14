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

from sagaz.core.compliance._access import AccessLevel, check_access, delete_user_data
from sagaz.core.compliance._audit import anonymize_context, create_audit_log
from sagaz.core.compliance._encryption import (
    decrypt_context,
    encrypt_context,
    is_sensitive,
    simple_decrypt,
    simple_encrypt,
)
from sagaz.core.compliance._manager import ComplianceConfig, ComplianceManager

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
