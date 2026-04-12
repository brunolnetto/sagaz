"""Audit trail and anonymization utilities."""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def create_audit_log(
    operation: str,
    user_id: str,
    saga_id: UUID,
    enable_audit_trail: bool = True,
    log_all_operations: bool = True,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create audit log entry for compliance.

    In production, send to:
    - SIEM (Security Information and Event Management)
    - Log aggregation system (ELK, Splunk)
    - Compliance database
    """
    if not enable_audit_trail:
        return {}

    log_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "operation": operation,
        "user_id": user_id,
        "saga_id": str(saga_id),
        "details": details or {},
    }

    if log_all_operations:
        logger.info(f"Audit log: {log_entry}")

    return log_entry


def hash_value(value: str) -> str:
    """Create one-way hash of sensitive value"""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def is_sensitive(key: str) -> bool:
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


def anonymize_context(context: dict[str, Any]) -> dict[str, Any]:
    """
    Anonymize sensitive data in context (for GDPR/privacy).

    Replaces sensitive values with hashes or anonymized versions.
    """
    anonymized = {}

    for key, value in context.items():
        if is_sensitive(key):
            # Hash sensitive data (irreversible)
            anonymized[key] = hash_value(str(value))
        else:
            anonymized[key] = value

    return anonymized
