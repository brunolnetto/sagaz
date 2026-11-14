"""AES-256-GCM encryption of tenant values (ADR-020, phase 2)."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from sagaz.core.tenant._errors import TenantDecryptionError
from sagaz.core.tenant.encryption._keys import KeyProvider

#: Key of the single-entry dict that replaces an encrypted value in storage.
ENVELOPE_FIELD = "__sagaz_encrypted__"
ALGORITHM = "A256GCM"
VERSION = 1
NONCE_BYTES = 12


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def is_encrypted(value: Any) -> bool:
    """Whether ``value`` is an envelope written by :class:`TenantCipher`."""
    return isinstance(value, dict) and len(value) == 1 and ENVELOPE_FIELD in value


def associated_data(tenant_id: str, saga_id: str, field: str) -> bytes:
    """Authenticated data binding a ciphertext to its tenant, saga and field."""
    return json.dumps(["sagaz", VERSION, tenant_id, saga_id, field]).encode()


class TenantCipher:
    """Encrypts JSON values with a tenant's key from a :class:`KeyProvider`.

    A value becomes ``{"__sagaz_encrypted__": {...}}`` holding the algorithm,
    the key reference (and wrapped data key, for KMS/Vault), a random 96-bit
    nonce and the ciphertext. The value's JSON is the plaintext; the tenant,
    saga id and field name are authenticated data, so a ciphertext moved to
    another tenant, saga or field fails to decrypt.
    """

    def __init__(self, provider: KeyProvider) -> None:
        self.provider = provider

    async def encrypt(self, tenant_id: str, value: Any, aad: bytes) -> dict[str, Any]:
        plaintext = json.dumps(value).encode()
        data_key = await self.provider.data_key(tenant_id)
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(data_key.key).encrypt(nonce, plaintext, aad)
        envelope: dict[str, Any] = {
            "v": VERSION,
            "alg": ALGORITHM,
            "key": data_key.key_ref,
            "nonce": _b64(nonce),
            "ct": _b64(ciphertext),
        }
        if data_key.wrapped is not None:
            envelope["edk"] = data_key.wrapped
        return {ENVELOPE_FIELD: envelope}

    async def decrypt(self, tenant_id: str, value: Any, aad: bytes) -> Any:
        """Decrypt an envelope; any other value is returned unchanged.

        Plain values are data written before encryption was enabled, which
        stays readable so encryption can be turned on without a migration.
        """
        if not is_encrypted(value):
            return value
        envelope = value[ENVELOPE_FIELD]
        if envelope.get("v") != VERSION or envelope.get("alg") != ALGORITHM:
            raise TenantDecryptionError(tenant_id, "unsupported envelope version or algorithm")
        key = await self.provider.resolve(tenant_id, envelope["key"], envelope.get("edk"))
        try:
            nonce = base64.b64decode(envelope["nonce"])
            plaintext = AESGCM(key).decrypt(nonce, base64.b64decode(envelope["ct"]), aad)
        except (InvalidTag, ValueError, KeyError) as exc:
            raise TenantDecryptionError(
                tenant_id, "authentication failed (wrong key, tenant, saga or field)"
            ) from exc
        return json.loads(plaintext)
