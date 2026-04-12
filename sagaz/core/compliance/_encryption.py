"""Encryption and decryption utilities for compliance."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


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


def simple_encrypt(text: str, encryption_key: str | None) -> str:
    """Simple encryption (demo only - use proper crypto in production)"""
    if not encryption_key:
        return text

    key_bytes = encryption_key.encode()
    text_bytes = text.encode()

    # XOR with key (cycled)
    encrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(text_bytes))

    # Return as hex string
    return encrypted.hex()


def simple_decrypt(encrypted_hex: str, encryption_key: str | None) -> str:
    """Simple decryption (demo only)"""
    if not encryption_key:
        return encrypted_hex

    try:
        key_bytes = encryption_key.encode()
        encrypted = bytes.fromhex(encrypted_hex)

        # XOR with key (cycled)
        decrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted))

        return decrypted.decode()
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return encrypted_hex


def encrypt_context(
    context: dict[str, Any], encryption_key: str | None
) -> dict[str, Any]:
    """
    Encrypt sensitive context data.

    Note: This is a simple implementation. In production, use:
    - Proper encryption libraries (cryptography, pycryptodome)
    - Key management systems (AWS KMS, Azure Key Vault, HashiCorp Vault)
    - Field-level encryption for specific keys
    """
    if not encryption_key:
        return context

    # Simple XOR encryption for demonstration
    # In production, use proper encryption (AES-256, etc.)
    encrypted = {}
    for key, value in context.items():
        if is_sensitive(key):
            encrypted[key] = {
                "_encrypted": True,
                "_value": simple_encrypt(str(value), encryption_key),
            }
        else:
            encrypted[key] = value

    return encrypted


def decrypt_context(context: dict[str, Any], encryption_key: str | None) -> dict[str, Any]:
    """Decrypt context data"""
    if not encryption_key:
        return context

    decrypted = {}
    for key, value in context.items():
        if isinstance(value, dict) and value.get("_encrypted"):
            decrypted[key] = simple_decrypt(value["_value"], encryption_key)
        else:
            decrypted[key] = value

    return decrypted
