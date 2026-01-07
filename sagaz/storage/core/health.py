"""
Health check infrastructure for storage backends.

Provides consistent health monitoring across all storage types
with support for Prometheus metrics and Kubernetes probes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class HealthStatus(Enum):
    """Storage health status."""
    
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # Working but with issues
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """
    Result of a health check operation.
    
    Attributes:
        status: Overall health status
        latency_ms: Time taken for health check in milliseconds
        message: Human-readable status message
        details: Additional backend-specific details
        checked_at: Timestamp of the check
    """
    
    status: HealthStatus
    latency_ms: float
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def is_healthy(self) -> bool:
        """Check if status is healthy or degraded (still operational)."""
        return self.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "status": self.status.value,
            "is_healthy": self.is_healthy,
            "latency_ms": round(self.latency_ms, 2),
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
class StorageStatistics:
    """
    Storage usage statistics.
    
    Attributes:
        total_records: Total number of records
        pending_records: Records in pending/processing state
        completed_records: Successfully completed records
        failed_records: Failed records
        storage_bytes: Estimated storage usage in bytes
        oldest_record: Timestamp of oldest record
        newest_record: Timestamp of newest record
    """
    
    total_records: int = 0
    pending_records: int = 0
    completed_records: int = 0
    failed_records: int = 0
    storage_bytes: int | None = None
    oldest_record: datetime | None = None
    newest_record: datetime | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "total_records": self.total_records,
            "pending_records": self.pending_records,
            "completed_records": self.completed_records,
            "failed_records": self.failed_records,
            "storage_bytes": self.storage_bytes,
            "oldest_record": self.oldest_record.isoformat() if self.oldest_record else None,
            "newest_record": self.newest_record.isoformat() if self.newest_record else None,
        }


class HealthCheckable(ABC):
    """
    Mixin for health-checkable storage backends.
    
    All storage implementations should implement this interface
    to provide consistent health monitoring.
    """
    
    @abstractmethod
    async def health_check(self) -> HealthCheckResult:
        """
        Perform a health check on the storage backend.
        
        Should check:
        - Connection is alive
        - Can read/write
        - Resource usage is acceptable
        
        Returns:
            HealthCheckResult with status and details
        """
        ...
    
    @abstractmethod
    async def get_statistics(self) -> StorageStatistics:
        """
        Get current storage statistics.
        
        Returns:
            StorageStatistics with usage information
        """
        ...


async def check_health_with_timeout(
    checker: HealthCheckable,
    timeout_seconds: float = 5.0,
) -> HealthCheckResult:
    """
    Perform health check with timeout protection.
    
    Args:
        checker: The health checkable instance
        timeout_seconds: Maximum time to wait
        
    Returns:
        HealthCheckResult (UNHEALTHY if timeout)
    """
    import asyncio
    import time
    
    start = time.perf_counter()
    
    try:
        result = await asyncio.wait_for(
            checker.health_check(),
            timeout=timeout_seconds,
        )
        return result
    except asyncio.TimeoutError:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return HealthCheckResult(
            status=HealthStatus.UNHEALTHY,
            latency_ms=elapsed_ms,
            message=f"Health check timed out after {timeout_seconds}s",
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return HealthCheckResult(
            status=HealthStatus.UNHEALTHY,
            latency_ms=elapsed_ms,
            message=f"Health check failed: {e}",
            details={"error": str(e), "error_type": type(e).__name__},
        )
