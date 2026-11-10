"""Backward-compatible facade for cross-backend storage migration.

The implementation lives in :mod:`sagaz.core.storage.migration`; this module
keeps the historical public import path used by the CLI and library users.
"""

from sagaz.core.storage.migration import (
    MigrationResult,
    SagaStorageMigrator,
    VerificationResult,
)
from sagaz.core.storage.transfer.service import TransferResult, transfer_data

__all__ = [
    "MigrationResult",
    "SagaStorageMigrator",
    "TransferResult",
    "VerificationResult",
    "transfer_data",
]
