"""Abstract base class for the unified storage manager facade."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces import OutboxStorage, SagaStorage


class BaseStorageManager(ABC):
    """
    Abstract base class for unified storage management.

    Provides a single entry point for both saga state storage and
    outbox event storage, with optional shared connection pooling.

    Attributes:
        saga: Access to saga storage operations
        outbox: Access to outbox storage operations
    """

    @property
    @abstractmethod
    def saga(self) -> "SagaStorage":
        """Get saga storage instance."""
        ...

    @property
    @abstractmethod
    def outbox(self) -> "OutboxStorage":
        """Get outbox storage instance."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the storage manager.

        Creates connections and initializes database schemas.
        Must be called before using saga or outbox properties.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Close all connections and clean up resources.

        Should be called when the application shuts down.
        """
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Check health of all storage components.

        Returns:
            Health status dictionary with details for each component.
        """
        ...

    async def __aenter__(self) -> "BaseStorageManager":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
