"""Tenant key providers for envelope encryption (ADR-020, phase 2).

A provider hands out a *data key* (an AES-256 key) for a tenant to encrypt with,
and later resolves the key again from the reference stored next to the
ciphertext. Providers that wrap data keys with a key-management service
(:class:`AwsKmsKeyProvider`, :class:`VaultTransitKeyProvider`) cache them, so the
service is called once per data key rather than once per record.
"""

from __future__ import annotations

import base64
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from sagaz.core.tenant._errors import TenantKeyError

KEY_BYTES = 32  # AES-256


@dataclass(frozen=True)
class DataKey:
    """A plaintext AES-256 key plus what is needed to find it again.

    ``key_ref`` names the key (a key id or KMS key); ``wrapped`` is the data key
    encrypted by the key service, or ``None`` when the reference alone suffices.
    Both are stored, unencrypted, next to each ciphertext.
    """

    key: bytes
    key_ref: str
    wrapped: str | None = None

    def __post_init__(self) -> None:
        if len(self.key) != KEY_BYTES:
            msg = f"data keys must be {KEY_BYTES} bytes, got {len(self.key)}"
            raise ValueError(msg)


@runtime_checkable
class KeyProvider(Protocol):
    """Source of tenant data keys."""

    async def data_key(self, tenant_id: str) -> DataKey:
        """The key to encrypt new data of ``tenant_id`` with."""
        ...

    async def resolve(self, tenant_id: str, key_ref: str, wrapped: str | None) -> bytes:
        """The plaintext key that data of ``tenant_id`` was encrypted with."""
        ...


def _b64decode_key(tenant_id: str, value: str, source: str) -> bytes:
    try:
        key = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise TenantKeyError(tenant_id, f"{source} is not valid base64") from exc
    if len(key) != KEY_BYTES:
        raise TenantKeyError(tenant_id, f"{source} must decode to {KEY_BYTES} bytes")
    return key


def _env_suffix(tenant_id: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", tenant_id.upper())


class EnvKeyProvider:
    """Keys from environment variables.

    - ``SAGAZ_TENANT_KEY_<TENANT>``: the tenant's own keys, as
      ``<key-id>:<base64 key>`` entries separated by commas; the first entry
      encrypts new data and every entry can decrypt (key rotation). A bare
      base64 value is key id ``1``. ``<TENANT>`` is the tenant id upper-cased
      with every character other than ``A-Z0-9`` replaced by ``_``.
    - ``SAGAZ_TENANT_MASTER_KEY``: optional fallback (same format). A tenant
      without its own variable gets a key derived from it with HKDF-SHA256
      and the tenant id, so one secret serves any number of tenants and no two
      tenants share a key.

    A tenant with neither raises :class:`TenantKeyError`; nothing is ever
    stored unencrypted for lack of a key.
    """

    TENANT_VAR = "SAGAZ_TENANT_KEY_"
    MASTER_VAR = "SAGAZ_TENANT_MASTER_KEY"

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ

    def _parse(self, tenant_id: str, value: str, source: str) -> dict[str, bytes]:
        keys: dict[str, bytes] = {}
        for raw in filter(None, (part.strip() for part in value.split(","))):
            key_id, sep, encoded = raw.rpartition(":")
            keys[key_id if sep else "1"] = _b64decode_key(tenant_id, encoded, source)
        if not keys:
            raise TenantKeyError(tenant_id, f"{source} is empty")
        return keys

    def _keys(self, tenant_id: str) -> tuple[str, dict[str, bytes]]:
        own_var = self.TENANT_VAR + _env_suffix(tenant_id)
        if own := self._environ.get(own_var):
            return "env", self._parse(tenant_id, own, own_var)
        if master := self._environ.get(self.MASTER_VAR):
            masters = self._parse(tenant_id, master, self.MASTER_VAR)
            return "hkdf", {kid: _derive(key, tenant_id) for kid, key in masters.items()}
        raise TenantKeyError(tenant_id, f"set {own_var} or {self.MASTER_VAR}")

    async def data_key(self, tenant_id: str) -> DataKey:
        kind, keys = self._keys(tenant_id)
        key_id, key = next(iter(keys.items()))
        return DataKey(key, f"{kind}:{key_id}")

    async def resolve(self, tenant_id: str, key_ref: str, wrapped: str | None) -> bytes:
        kind, keys = self._keys(tenant_id)
        ref_kind, _, key_id = key_ref.partition(":")
        if ref_kind != kind or key_id not in keys:
            raise TenantKeyError(tenant_id, f"key '{key_ref}' is not configured")
        return keys[key_id]


def _derive(master: bytes, tenant_id: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=b"sagaz-tenant-key-v1",
        info=tenant_id.encode(),
    ).derive(master)


class CachingKeyProvider:
    """Base for providers whose data keys come from a remote key service.

    New data keys are reused for ``data_key_ttl`` seconds and at most
    ``max_key_uses`` encryptions, then replaced. Unwrapped keys are kept in an
    LRU cache of ``cache_size`` entries, so decrypting many records encrypted
    under the same data key calls the service once.
    """

    def __init__(
        self, *, data_key_ttl: float = 300.0, max_key_uses: int = 100_000, cache_size: int = 1024
    ) -> None:
        self._ttl = data_key_ttl
        self._max_uses = max_key_uses
        self._cache_size = cache_size
        self._current: dict[str, tuple[DataKey, float, int]] = {}
        self._unwrapped: OrderedDict[tuple[str, str, str | None], bytes] = OrderedDict()

    async def _generate(self, tenant_id: str) -> DataKey:  # pragma: no cover - abstract
        raise NotImplementedError

    async def _unwrap(self, tenant_id: str, key_ref: str, wrapped: str | None) -> bytes:
        raise NotImplementedError  # pragma: no cover - abstract

    async def data_key(self, tenant_id: str) -> DataKey:
        now = time.monotonic()
        cached = self._current.get(tenant_id)
        if cached and now - cached[1] < self._ttl and cached[2] < self._max_uses:
            self._current[tenant_id] = (cached[0], cached[1], cached[2] + 1)
            return cached[0]
        key = await self._generate(tenant_id)
        self._current[tenant_id] = (key, now, 1)
        self._remember((tenant_id, key.key_ref, key.wrapped), key.key)
        return key

    async def resolve(self, tenant_id: str, key_ref: str, wrapped: str | None) -> bytes:
        cache_key = (tenant_id, key_ref, wrapped)
        if (key := self._unwrapped.get(cache_key)) is not None:
            self._unwrapped.move_to_end(cache_key)
            return key
        key = await self._unwrap(tenant_id, key_ref, wrapped)
        self._remember(cache_key, key)
        return key

    def _remember(self, cache_key: tuple[str, str, str | None], key: bytes) -> None:
        self._unwrapped[cache_key] = key
        self._unwrapped.move_to_end(cache_key)
        while len(self._unwrapped) > self._cache_size:
            self._unwrapped.popitem(last=False)
