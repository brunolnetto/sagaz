"""Per-tenant encryption of saga data at rest (ADR-020, phase 2).

Wrap any saga storage to encrypt each tenant's saga context and step results
with that tenant's own AES-256-GCM key::

    from sagaz.core.tenant.encryption import EncryptedSagaStorage, EnvKeyProvider

    storage = EncryptedSagaStorage(PostgreSQLSagaStorage(url), EnvKeyProvider())

Keys come from a :class:`KeyProvider`: environment variables
(:class:`EnvKeyProvider`), AWS KMS (:class:`AwsKmsKeyProvider`) or Vault Transit
(:class:`VaultTransitKeyProvider`), or your own implementation.
Requires the ``cryptography`` package (``pip install 'sagaz[encryption]'``).
"""

from sagaz.core.tenant._errors import TenantDecryptionError, TenantKeyError
from sagaz.core.tenant.encryption._cipher import (
    ENVELOPE_FIELD,
    TenantCipher,
    associated_data,
    is_encrypted,
)
from sagaz.core.tenant.encryption._keys import (
    CachingKeyProvider,
    DataKey,
    EnvKeyProvider,
    KeyProvider,
)
from sagaz.core.tenant.encryption._kms import AwsKmsKeyProvider
from sagaz.core.tenant.encryption._storage import EncryptedSagaStorage
from sagaz.core.tenant.encryption._vault import VaultTransitKeyProvider

__all__ = [
    "ENVELOPE_FIELD",
    "AwsKmsKeyProvider",
    "CachingKeyProvider",
    "DataKey",
    "EncryptedSagaStorage",
    "EnvKeyProvider",
    "KeyProvider",
    "TenantCipher",
    "TenantDecryptionError",
    "TenantKeyError",
    "VaultTransitKeyProvider",
    "associated_data",
    "is_encrypted",
]
