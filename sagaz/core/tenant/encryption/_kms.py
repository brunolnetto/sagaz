"""AWS KMS key provider (requires ``sagaz[aws]``)."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

from sagaz.core.tenant._errors import TenantKeyError
from sagaz.core.tenant.encryption._keys import CachingKeyProvider, DataKey

#: KMS encryption context entry binding every data key to its tenant.
TENANT_CONTEXT_KEY = "sagaz:tenant"


class AwsKmsKeyProvider(CachingKeyProvider):
    """Data keys from AWS KMS ``GenerateDataKey`` (envelope encryption).

    Each tenant uses its own KMS key, named by ``key_id`` (a template such as
    ``"alias/sagaz-{tenant_id}"``, the default, or a callable). Data keys are
    generated and decrypted with the encryption context
    ``{"sagaz:tenant": <tenant>}``, so KMS refuses to unwrap one tenant's data
    key for another tenant and CloudTrail records the tenant on every call.

    ``client_kwargs`` go to ``aioboto3.Session().client("kms", ...)``
    (``region_name``, ``endpoint_url`` for LocalStack, credentials).
    """

    def __init__(
        self,
        key_id: str | Callable[[str], str] = "alias/sagaz-{tenant_id}",
        *,
        session: Any = None,
        client_kwargs: dict[str, Any] | None = None,
        **cache_options: Any,
    ) -> None:
        super().__init__(**cache_options)
        self._key_id = key_id
        self._session = session
        self._client_kwargs = client_kwargs or {}

    def key_id_for(self, tenant_id: str) -> str:
        if callable(self._key_id):
            return self._key_id(tenant_id)
        return self._key_id.format(tenant_id=tenant_id)

    def _client(self) -> Any:
        if self._session is None:
            try:
                import aioboto3
            except ImportError as exc:  # pragma: no cover - depends on extras
                msg = "AwsKmsKeyProvider needs aioboto3: pip install 'sagaz[aws]'"
                raise ImportError(msg) from exc
            self._session = aioboto3.Session()
        return self._session.client("kms", **self._client_kwargs)

    async def _generate(self, tenant_id: str) -> DataKey:
        key_id = self.key_id_for(tenant_id)
        try:
            async with self._client() as kms:
                response = await kms.generate_data_key(
                    KeyId=key_id,
                    KeySpec="AES_256",
                    EncryptionContext={TENANT_CONTEXT_KEY: tenant_id},
                )
        except Exception as exc:
            raise TenantKeyError(
                tenant_id, f"KMS GenerateDataKey on {key_id} failed: {exc}"
            ) from exc
        wrapped = base64.b64encode(response["CiphertextBlob"]).decode()
        return DataKey(response["Plaintext"], key_id, wrapped)

    async def _unwrap(self, tenant_id: str, key_ref: str, wrapped: str | None) -> bytes:
        if not wrapped:
            raise TenantKeyError(tenant_id, "KMS-encrypted data carries no wrapped data key")
        try:
            async with self._client() as kms:
                response = await kms.decrypt(
                    CiphertextBlob=base64.b64decode(wrapped),
                    KeyId=key_ref,
                    EncryptionContext={TENANT_CONTEXT_KEY: tenant_id},
                )
        except Exception as exc:
            raise TenantKeyError(tenant_id, f"KMS Decrypt with {key_ref} failed: {exc}") from exc
        key: bytes = response["Plaintext"]
        return key
