"""
Unified error hierarchy for storage operations.

All storage-related exceptions inherit from StorageError,
providing consistent error handling across backends.
"""

from typing import Any


class StorageError(Exception):
    """
    Base exception for all storage operations.

    All storage backends raise subclasses of this exception,
    making it easy to catch storage-related errors.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} ({self.details})"
        return self.message


class ConnectionError(StorageError):
    """
    Failed to connect to storage backend.

    Raised when:
    - Initial connection fails
    - Connection pool exhausted
    - Network timeout
    - Authentication failure
    """

    def __init__(
        self,
        message: str = "Failed to connect to storage backend",
        backend: str | None = None,
        url: str | None = None,
        **details,
    ):
        super().__init__(
            message,
            details={"backend": backend, "url": self._mask_url(url), **details},
        )
        self.backend = backend
        self.url = url

    @staticmethod
    def _mask_url(url: str | None) -> str | None:
        """Mask sensitive parts of connection URL."""
        if not url:
            return None
        # Mask password in URL like postgresql://user:pass@host/db
        import re

        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


class NotFoundError(StorageError):
    """
    Requested item not found in storage.

    Raised when:
    - Saga state not found by ID
    - Outbox event not found
    - Record doesn't exist
    """

    def __init__(
        self,
        message: str = "Item not found",
        item_type: str | None = None,
        item_id: str | None = None,
        **details,
    ):
        super().__init__(
            message,
            details={"item_type": item_type, "item_id": item_id, **details},
        )
        self.item_type = item_type
        self.item_id = item_id


class SerializationError(StorageError):
    """
    Failed to serialize or deserialize data.

    Raised when:
    - JSON encoding/decoding fails
    - Data type conversion fails
    - Schema validation fails
    """

    def __init__(
        self,
        message: str = "Serialization failed",
        operation: str | None = None,  # "serialize" or "deserialize"
        data_type: str | None = None,
        **details,
    ):
        super().__init__(
            message,
            details={"operation": operation, "data_type": data_type, **details},
        )
        self.operation = operation
        self.data_type = data_type


class TransferError(StorageError):
    """
    Failed to transfer data between backends.

    Raised when:
    - Source/target incompatible
    - Transfer interrupted
    - Validation failed
    """

    def __init__(
        self,
        message: str = "Transfer failed",
        source: str | None = None,
        target: str | None = None,
        records_transferred: int = 0,
        records_failed: int = 0,
        **details,
    ):
        super().__init__(
            message,
            details={
                "source": source,
                "target": target,
                "records_transferred": records_transferred,
                "records_failed": records_failed,
                **details,
            },
        )
        self.source = source
        self.target = target
        self.records_transferred = records_transferred
        self.records_failed = records_failed


class TransactionError(StorageError):
    """
    Transaction operation failed.

    Raised when:
    - Transaction commit fails
    - Rollback fails
    - Deadlock detected
    """

    def __init__(
        self,
        message: str = "Transaction failed",
        operation: str | None = None,  # "commit", "rollback", "begin"
        **details,
    ):
        super().__init__(
            message,
            details={"operation": operation, **details},
        )
        self.operation = operation


class ConcurrencyError(StorageError):
    """
    Concurrent modification detected.

    Raised when:
    - Optimistic locking fails
    - Version mismatch
    - Row already modified
    """

    def __init__(
        self,
        message: str = "Concurrent modification detected",
        item_id: str | None = None,
        expected_version: int | None = None,
        actual_version: int | None = None,
        **details,
    ):
        super().__init__(
            message,
            details={
                "item_id": item_id,
                "expected_version": expected_version,
                "actual_version": actual_version,
                **details,
            },
        )
        self.item_id = item_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class CapacityError(StorageError):
    """
    Storage capacity exceeded.

    Raised when:
    - Memory limit reached
    - Disk space exhausted
    - Stream length exceeded
    """

    def __init__(
        self,
        message: str = "Storage capacity exceeded",
        limit: int | None = None,
        current: int | None = None,
        **details,
    ):
        super().__init__(
            message,
            details={"limit": limit, "current": current, **details},
        )
        self.limit = limit
        self.current = current
