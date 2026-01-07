"""
Base storage class with common functionality.

All storage implementations inherit from BaseStorage,
which provides common patterns for:
- Connection management
- Health checks
- Context manager support
- Logging
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from .connection import ConnectionManager
from .health import HealthCheckResult, HealthCheckable, HealthStatus, StorageStatistics


class BaseStorage(HealthCheckable, ABC):
    """
    Base class for all storage implementations.
    
    Provides:
    - Connection manager integration
    - Async context manager support
    - Logging setup
    - Health check interface
    
    Subclasses must implement:
    - health_check()
    - get_statistics()
    - close()
    """
    
    def __init__(
        self,
        connection_manager: ConnectionManager | None = None,
        logger: logging.Logger | None = None,
    ):
        """
        Initialize base storage.
        
        Args:
            connection_manager: Optional connection manager for pooling
            logger: Optional logger instance
        """
        self._connection_manager = connection_manager
        self._logger = logger or logging.getLogger(self.__class__.__name__)
        self._closed = False
    
    @property
    def is_closed(self) -> bool:
        """Check if storage has been closed."""
        return self._closed
    
    @abstractmethod
    async def close(self) -> None:
        """
        Close the storage and release resources.
        
        After calling close(), the storage should not be used.
        """
        ...
    
    async def health_check(self) -> HealthCheckResult:
        """
        Perform a health check.
        
        Default implementation checks connection manager if available.
        Subclasses should override for storage-specific checks.
        """
        if self._closed:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=0,
                message="Storage is closed",
            )
        
        if self._connection_manager:
            return await self._connection_manager.health_check()
        
        return HealthCheckResult(
            status=HealthStatus.HEALTHY,
            latency_ms=0,
            message="No connection manager (in-memory mode)",
        )
    
    async def get_statistics(self) -> StorageStatistics:
        """
        Get storage statistics.
        
        Default implementation returns empty statistics.
        Subclasses should override.
        """
        return StorageStatistics()
    
    async def __aenter__(self) -> "BaseStorage":
        """Enter async context."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context, closing the storage."""
        await self.close()
    
    def _log_operation(
        self,
        operation: str,
        item_id: str | None = None,
        **kwargs,
    ) -> None:
        """Log a storage operation at debug level."""
        extra = {"operation": operation}
        if item_id:
            extra["item_id"] = item_id
        extra.update(kwargs)
        
        self._logger.debug(f"Storage operation: {operation}", extra=extra)


class TransferableStorage(BaseStorage):
    """
    Base class for storage that supports data transfer.
    
    Adds:
    - export_all(): Export all records
    - import_record(): Import a single record
    - count(): Get total record count
    """
    
    @abstractmethod
    async def export_all(self) -> AsyncIterator[dict[str, Any]]:
        """
        Export all records as dictionaries.
        
        Yields:
            Dict representation of each record
        """
        ...
    
    @abstractmethod
    async def import_record(self, record: dict[str, Any]) -> None:
        """
        Import a single record.
        
        Args:
            record: Dict representation of the record
        """
        ...
    
    @abstractmethod
    async def count(self) -> int:
        """
        Get total record count.
        
        Returns:
            Number of records in storage
        """
        ...
    
    async def clear(self) -> int:
        """
        Delete all records (optional).
        
        Returns:
            Number of records deleted
            
        Raises:
            NotImplementedError: If not supported by backend
        """
        raise NotImplementedError("clear() not implemented for this backend")
