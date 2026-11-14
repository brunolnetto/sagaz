"""HashiCorp Vault Transit key provider (uses ``httpx``)."""

from __future__ import annotations

import base64
import os
from collections.abc import Callable
from typing import Any

from sagaz.core.tenant._errors import TenantKeyError
from sagaz.core.tenant.encryption._keys import CachingKeyProvider, DataKey


class VaultTransitKeyProvider(CachingKeyProvider):
    """Data keys from Vault's Transit secrets engine (``transit/datakey``).

    Each tenant has its own Transit key, named by ``key_name`` (a template such
    as ``"sagaz-{tenant_id}"``, the default, or a callable); a token for one
    tenant's key cannot unwrap another's. The Transit keys must exist (create
    them with ``vault write -f transit/keys/sagaz-<tenant>``); sagaz never
    creates or rotates them.

    ``url`` and ``token`` default to ``VAULT_ADDR`` and ``VAULT_TOKEN``.
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        key_name: str | Callable[[str], str] = "sagaz-{tenant_id}",
        mount: str = "transit",
        namespace: str | None = None,
        timeout: float = 10.0,
        transport: Any = None,
        **cache_options: Any,
    ) -> None:
        super().__init__(**cache_options)
        self._url = (url or os.environ.get("VAULT_ADDR", "")).rstrip("/")
        self._token = token or os.environ.get("VAULT_TOKEN", "")
        self._key_name = key_name
        self._mount = mount.strip("/")
        self._namespace = namespace
        self._timeout = timeout
        self._transport = transport

    def key_name_for(self, tenant_id: str) -> str:
        if callable(self._key_name):
            return self._key_name(tenant_id)
        return self._key_name.format(tenant_id=tenant_id)

    async def _post(self, tenant_id: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        if not self._url or not self._token:
            raise TenantKeyError(tenant_id, "Vault url and token are not configured")
        headers = {"X-Vault-Token": self._token}
        if self._namespace:
            headers["X-Vault-Namespace"] = self._namespace
        url = f"{self._url}/v1/{self._mount}/{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as http:
                response = await http.post(url, json=body, headers=headers)
                response.raise_for_status()
                data: dict[str, Any] = response.json()["data"]
                return data
        except Exception as exc:
            raise TenantKeyError(tenant_id, f"Vault request to {path} failed: {exc}") from exc

    async def _generate(self, tenant_id: str) -> DataKey:
        name = self.key_name_for(tenant_id)
        data = await self._post(tenant_id, f"datakey/plaintext/{name}", {"bits": 256})
        return DataKey(base64.b64decode(data["plaintext"]), name, data["ciphertext"])

    async def _unwrap(self, tenant_id: str, key_ref: str, wrapped: str | None) -> bytes:
        if not wrapped:
            raise TenantKeyError(tenant_id, "Vault-encrypted data carries no wrapped data key")
        if key_ref != self.key_name_for(tenant_id):
            # The reference is stored next to the data; never let it pick
            # another tenant's Transit key.
            raise TenantKeyError(tenant_id, f"key '{key_ref}' does not belong to the tenant")
        data = await self._post(tenant_id, f"decrypt/{key_ref}", {"ciphertext": wrapped})
        return base64.b64decode(data["plaintext"])
