"""
Saga storage interface.

Enhanced interface for saga state persistence with transfer
and health check support.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sagaz.storage.core import (
    HealthCheckResult,
    StorageStatistics,
)
from sagaz.types import SagaStatus, SagaStepStatus


@runtime_checkable
class Transferable(Protocol):
    """
    Protocol for storages that support data transfer.

    Implementations can transfer data between backends,
    enabling migrations and hybrid deployments.
    """

    async def export_all(self) -> AsyncIterator[dict[str, Any]]:
        """Export all records as dictionaries."""
        ...

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a single record."""
        ...

    async def count(self) -> int:
        """Get total record count."""
        ...


class SagaStorage(ABC):
    """
    Abstract base class for saga state persistence.

    Provides interface for storing and retrieving saga execution state,
    enabling saga recovery and state inspection across restarts.

    All implementations should support:
    - CRUD operations for saga state
    - Filtering and listing sagas
    - Step state updates
    - Health checks and statistics

    Optional (for transfer support):
    - export_all() for exporting records
    - import_record() for importing records
    - count() for getting total count
    """

    # ==========================================================================
    # Core CRUD Operations
    # ==========================================================================

    @abstractmethod
    async def save_saga_state(
        self,
        saga_id: str,
        saga_name: str,
        status: SagaStatus,
        steps: list[dict[str, Any]],
        context: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Save saga state to persistent storage.

        Args:
            saga_id: Unique saga identifier
            saga_name: Human-readable saga name
            status: Current saga status
            steps: List of step definitions and states
            context: Saga execution context
            metadata: Additional metadata (version, timestamps, etc.)
        """
        ...

    @abstractmethod
    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        """
        Load saga state from persistent storage.

        Args:
            saga_id: Unique saga identifier

        Returns:
            Saga state dictionary or None if not found
        """
        ...

    @abstractmethod
    async def delete_saga_state(self, saga_id: str) -> bool:
        """
        Delete saga state from persistent storage.

        Args:
            saga_id: Unique saga identifier

        Returns:
            True if deleted, False if not found
        """
        ...

    # ==========================================================================
    # Query Operations
    # ==========================================================================

    @abstractmethod
    async def list_sagas(
        self,
        status: SagaStatus | None = None,
        saga_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List sagas with optional filtering.

        Args:
            status: Filter by saga status
            saga_name: Filter by saga name pattern
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of saga state summaries
        """
        ...

    @abstractmethod
    async def update_step_state(
        self,
        saga_id: str,
        step_name: str,
        status: SagaStepStatus,
        result: Any = None,
        error: str | None = None,
        executed_at: datetime | None = None,
    ) -> None:
        """
        Update individual step state.

        Args:
            saga_id: Unique saga identifier
            step_name: Name of the step to update
            status: New step status
            result: Step execution result
            error: Error message if step failed
            executed_at: Timestamp of execution
        """
        ...

    # ==========================================================================
    # Statistics and Maintenance
    # ==========================================================================

    @abstractmethod
    async def get_saga_statistics(self) -> dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with storage statistics (counts by status, etc.)
        """
        ...

    @abstractmethod
    async def cleanup_completed_sagas(
        self,
        older_than: datetime,
        statuses: list[SagaStatus] | None = None,
    ) -> int:
        """
        Clean up old completed sagas.

        Args:
            older_than: Delete sagas completed before this timestamp
            statuses: Only delete sagas with these statuses
                      (default: COMPLETED, ROLLED_BACK)

        Returns:
            Number of sagas deleted
        """
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Check storage health.

        Returns:
            Health status information
        """
        ...

    # ==========================================================================
    # Transfer Support (Optional - Not Required)
    # ==========================================================================

    async def export_all(self) -> AsyncIterator[dict[str, Any]]:
        """
        Export all saga states as dictionaries.

        Override to enable data transfer from this backend.

        Yields:
            Dict representation of each saga state
        """
        msg = (
            f"{self.__class__.__name__} does not support export. "
            "Implement export_all() to enable data transfer."
        )
        raise NotImplementedError(
            msg
        )
        # Make it a generator
        if False:
            yield {}

    async def import_record(self, record: dict[str, Any]) -> None:
        """
        Import a single saga state record.

        Override to enable data transfer to this backend.

        Args:
            record: Dict representation of saga state
        """
        msg = (
            f"{self.__class__.__name__} does not support import. "
            "Implement import_record() to enable data transfer."
        )
        raise NotImplementedError(
            msg
        )

    async def count(self) -> int:
        """
        Get total saga count.

        Override for efficient counting (used for transfer progress).
        Default implementation uses list_sagas which may be slow.

        Returns:
            Number of sagas in storage
        """
        # Default: use list_sagas (may be slow for large datasets)
        sagas = await self.list_sagas(limit=1000000)
        return len(sagas)

    # ==========================================================================
    # Context Manager Support
    # ==========================================================================

    async def __aenter__(self) -> "SagaStorage":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""

    async def close(self) -> None:
        """
        Close the storage and release resources.

        Override if your backend needs cleanup.
        """


# ==========================================================================
# Helper Classes
# ==========================================================================

class SagaStepState:
    """Helper class for step state representation."""

    def __init__(
        self,
        name: str,
        status: SagaStepStatus,
        result: Any = None,
        error: str | None = None,
        executed_at: datetime | None = None,
        compensated_at: datetime | None = None,
        retry_count: int = 0,
    ):
        self.name = name
        self.status = status
        self.result = result
        self.error = error
        self.executed_at = executed_at
        self.compensated_at = compensated_at
        self.retry_count = retry_count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "compensated_at": self.compensated_at.isoformat() if self.compensated_at else None,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SagaStepState":
        """Create from dictionary representation."""
        executed_at = None
        if data.get("executed_at"):
            executed_at = datetime.fromisoformat(data["executed_at"])

        compensated_at = None
        if data.get("compensated_at"):
            compensated_at = datetime.fromisoformat(data["compensated_at"])

        return cls(
            name=data["name"],
            status=SagaStepStatus(data["status"]),
            result=data.get("result"),
            error=data.get("error"),
            executed_at=executed_at,
            compensated_at=compensated_at,
            retry_count=data.get("retry_count", 0),
        )
