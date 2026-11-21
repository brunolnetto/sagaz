"""Saga storage base class, under its original import path.

``SagaStorage`` and ``SagaStepState`` are defined once, in
:mod:`sagaz.core.storage.interfaces.saga`. This module used to define its own copies,
which the built-in backends inherited while ``sagaz.core.storage`` exported the other
one, so ``isinstance(InMemorySagaStorage(), sagaz.core.storage.SagaStorage)`` was false
(#599). It now re-exports the single classes and keeps the storage exceptions.
"""

from sagaz.core.storage.interfaces.saga import SagaStepState, SagaStorage

__all__ = [
    "SagaNotFoundError",
    "SagaStepState",
    "SagaStorage",
    "SagaStorageConnectionError",
    "SagaStorageError",
]


class SagaStorageError(Exception):
    """Base exception for saga storage operations"""


class SagaNotFoundError(SagaStorageError):
    """Raised when saga is not found in storage"""


class SagaStorageConnectionError(SagaStorageError):
    """Raised when storage connection fails"""
