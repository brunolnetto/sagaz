"""
Connection management for storage backends.

Provides abstract connection pooling and lifecycle management
that can be implemented by each backend (PostgreSQL, Redis, etc.).
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .errors import ConnectionError
from .health import HealthCheckResult, HealthStatus

# Generic type for connection objects
T = TypeVar("T")


@dataclass
class ConnectionConfig:
    """
    Common configuration for connections.

    Attributes:
        url: Connection URL (e.g., postgresql://..., redis://...)
        min_size: Minimum pool size
        max_size: Maximum pool size
        timeout_seconds: Connection timeout
        retry_attempts: Number of retry attempts
        retry_delay_seconds: Delay between retries
    """

    url: str
    min_size: int = 1
    max_size: int = 10
    timeout_seconds: float = 30.0
    retry_attempts: int = 3
    retry_delay_seconds: float = 1.0

    # Additional connection-specific options
    options: dict[str, Any] | None = None

    def __post_init__(self):
        if self.options is None:
            self.options = {}


@dataclass
class PoolStatus:
    """
    Connection pool status.

    Attributes:
        size: Current pool size
        min_size: Minimum pool size
        max_size: Maximum pool size
        free: Number of free connections
        used: Number of connections in use
        waiting: Number of waiters for connections
    """

    size: int
    min_size: int
    max_size: int
    free: int
    used: int
    waiting: int = 0

    @property
    def utilization(self) -> float:
        """Pool utilization percentage."""
        if self.size == 0:
            return 0.0
        return (self.used / self.size) * 100


class ConnectionManager(ABC, Generic[T]):
    """
    Abstract connection/pool manager.

    Implementations should handle:
    - Connection pooling
    - Health checks
    - Graceful shutdown
    - Retry logic

    Usage:
        async with connection_manager.acquire() as conn:
            await conn.execute(...)
    """

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the connection pool.

        Should be called before using the manager.
        Idempotent - multiple calls have no effect.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Close all connections and cleanup.

        Should be called during shutdown.
        """
        ...

    @abstractmethod
    async def _acquire(self) -> T:
        """
        Acquire a connection from pool (internal).

        Returns:
            A connection object

        Raises:
            ConnectionError: If acquisition fails
        """
        ...

    @abstractmethod
    async def _release(self, connection: T) -> None:
        """
        Release connection back to pool (internal).

        Args:
            connection: The connection to release
        """
        ...

    @abstractmethod
    async def health_check(self) -> HealthCheckResult:
        """
        Check connection pool health.

        Returns:
            HealthCheckResult with pool status
        """
        ...

    @abstractmethod
    def get_pool_status(self) -> PoolStatus:
        """
        Get current pool status.

        Returns:
            PoolStatus with pool metrics
        """
        ...

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[T]:
        """
        Acquire a connection as a context manager.

        Usage:
            async with manager.acquire() as conn:
                await conn.execute(...)

        Yields:
            A connection object

        Raises:
            ConnectionError: If acquisition fails
        """
        if not self._initialized:
            await self.initialize()

        connection = await self._acquire()
        try:
            yield connection
        finally:
            await self._release(connection)

    async def __aenter__(self) -> "ConnectionManager[T]":
        await self.initialize()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()


class SingleConnectionManager(ConnectionManager[T]):
    """
    Simple connection manager for backends without pooling.

    Maintains a single connection that is reused.
    Useful for SQLite or simple Redis connections.
    """

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self._connection: T | None = None

    @abstractmethod
    async def _create_connection(self) -> T:
        """Create a new connection."""
        ...

    @abstractmethod
    async def _close_connection(self, connection: T) -> None:
        """Close an existing connection."""
        ...

    @abstractmethod
    async def _is_connection_valid(self, connection: T) -> bool:
        """Check if connection is still valid."""
        ...

    async def initialize(self) -> None:
        if self._initialized:
            return

        try:
            self._connection = await self._create_connection()
            self._initialized = True
        except Exception as e:  # pragma: no cover
            raise ConnectionError(
                message=f"Failed to create connection: {e}",
                url=self.config.url,
            ) from e  # pragma: no cover

    async def close(self) -> None:
        if self._connection is not None:
            await self._close_connection(self._connection)
            self._connection = None
        self._initialized = False

    async def _acquire(self) -> T:
        if self._connection is None:
            await self.initialize()

        # Check if connection is still valid
        if not await self._is_connection_valid(self._connection):
            await self.close()
            await self.initialize()

        return self._connection  # type: ignore

    async def _release(self, connection: T) -> None:
        # No-op for single connection
        pass

    def get_pool_status(self) -> PoolStatus:
        return PoolStatus(
            size=1 if self._connection else 0,
            min_size=1,
            max_size=1,
            free=1 if self._connection else 0,
            used=0,
        )

    async def health_check(self) -> HealthCheckResult:
        import time

        start = time.perf_counter()

        try:
            if self._connection is None:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=0,
                    message="No connection established",
                )

            if await self._is_connection_valid(self._connection):
                elapsed_ms = (time.perf_counter() - start) * 1000
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    latency_ms=elapsed_ms,
                    message="Connection is valid",
                )
            elapsed_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=elapsed_ms,
                message="Connection is invalid",
            )
        except Exception as e:  # pragma: no cover
            elapsed_ms = (time.perf_counter() - start) * 1000  # pragma: no cover
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=elapsed_ms,
                message=f"Health check failed: {e}",
            )  # pragma: no cover
