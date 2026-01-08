"""
Sagaz Storage Interfaces.

Enhanced abstract interfaces for saga and outbox storage
with support for transfer, health checks, and statistics.

Usage:
    from sagaz.storage.interfaces import (
        SagaStorage,
        OutboxStorage,
        Transferable,
        SagaStepState,
    )

Note: OutboxStorage can also be imported from sagaz.outbox for convenience.
"""

from .outbox import OutboxStorage, OutboxStorageError
from .saga import SagaStepState, SagaStorage, Transferable

__all__ = [
    # Outbox
    "OutboxStorage",
    "OutboxStorageError",
    "SagaStepState",
    # Saga
    "SagaStorage",
    "Transferable",
]
