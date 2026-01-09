"""
Base storage interface for saga persistence.

Defines the abstract interface for saga state persistence, enabling
pluggable storage backends (memory, Redis, PostgreSQL, etc.).

Note: The canonical interface is in sagaz.storage.interfaces.
This module provides a base implementation.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from sagaz.core.types import SagaStatus, SagaStepStatus


class SagaStorage(ABC):
    """
    Abstract base class for saga state persistence

    Provides interface for storing and retrieving saga execution state,
    enabling saga recovery and state inspection across restarts.
    """

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
        Save saga state to persistent storage

        Args:
            saga_id: Unique saga identifier
            saga_name: Human-readable saga name
            status: Current saga status
            steps: List of step definitions and states
            context: Saga execution context
            metadata: Additional metadata (version, timestamps, etc.)
        """

    @abstractmethod
    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        """
        Load saga state from persistent storage

        Args:
            saga_id: Unique saga identifier

        Returns:
            Saga state dictionary or None if not found
        """

    @abstractmethod
    async def delete_saga_state(self, saga_id: str) -> bool:
        """
        Delete saga state from persistent storage

        Args:
            saga_id: Unique saga identifier

        Returns:
            True if deleted, False if not found
        """

    @abstractmethod
    async def list_sagas(
        self,
        status: SagaStatus | None = None,
        saga_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List sagas with optional filtering

        Args:
            status: Filter by saga status
            saga_name: Filter by saga name pattern
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of saga state summaries
        """

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
        Update individual step state

        Args:
            saga_id: Unique saga identifier
            step_name: Name of the step to update
            status: New step status
            result: Step execution result
            error: Error message if step failed
            executed_at: Timestamp of execution
        """

    @abstractmethod
    async def get_saga_statistics(self) -> dict[str, Any]:
        """
        Get storage statistics

        Returns:
            Dictionary with storage statistics (counts by status, etc.)
        """

    @abstractmethod
    async def cleanup_completed_sagas(
        self, older_than: datetime, statuses: list[SagaStatus] | None = None
    ) -> int:
        """
        Clean up old completed sagas

        Args:
            older_than: Delete sagas completed before this timestamp
            statuses: Only delete sagas with these statuses (default: COMPLETED, ROLLED_BACK)

        Returns:
            Number of sagas deleted
        """

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Check storage health

        Returns:
            Health status information
        """

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""


class SagaStepState:
    """Helper class for step state representation"""

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
        """Convert to dictionary representation"""
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
        """Create from dictionary representation"""
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


class SagaStorageError(Exception):
    """Base exception for saga storage operations"""


class SagaNotFoundError(SagaStorageError):
    """Raised when saga is not found in storage"""


class SagaStorageConnectionError(SagaStorageError):
    """Raised when storage connection fails"""
