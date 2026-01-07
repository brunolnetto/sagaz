"""
Sagaz Storage Transfer Module.

Provides utilities for migrating data between storage backends.

Usage:
    >>> from sagaz.storage.transfer import TransferService, TransferConfig, transfer_data
    >>>
    >>> # Quick transfer
    >>> result = await transfer_data(source, target)
    >>>
    >>> # With configuration
    >>> config = TransferConfig(batch_size=100, validate=True)
    >>> service = TransferService(source, target, config)
    >>> result = await service.transfer_all()
"""

from .service import (
    TransferConfig,
    TransferErrorPolicy,
    TransferProgress,
    TransferResult,
    TransferService,
    transfer_data,
)

__all__ = [
    "TransferService",
    "TransferConfig",
    "TransferProgress",
    "TransferResult",
    "TransferErrorPolicy",
    "transfer_data",
]
