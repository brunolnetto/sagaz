"""Backend initialisation for :class:`~sagaz.core.storage.manager.StorageManager`.

Contains the unified (shared connection) and hybrid (separate backends)
initialisation paths, kept apart from the manager facade itself.
"""

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces import OutboxStorage, SagaStorage


class _StorageBackendInitMixin:
    """Creates and wires saga/outbox storage instances for each backend type."""

    _saga_url: str | None
    _outbox_url: str | None
    _kwargs: dict[str, Any]
    _saga_storage: "SagaStorage | None"
    _outbox_storage: "OutboxStorage | None"
    _shared_pool: Any | None

    async def _initialize_unified(self, backend_type: str) -> None:
        """Initialize with same backend for both (shared connection)."""
        if backend_type == "memory":
            from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage
            from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage

            self._saga_storage = cast("SagaStorage", InMemorySagaStorage())
            self._outbox_storage = cast("OutboxStorage", InMemoryOutboxStorage())

        elif backend_type == "postgresql":
            await self._initialize_postgresql_unified()

        elif backend_type == "redis":
            await self._initialize_redis_unified()

        elif backend_type == "sqlite":
            await self._initialize_sqlite_unified()

        else:
            msg = f"Unknown backend type: {backend_type}"
            raise ValueError(msg)

    async def _initialize_postgresql_unified(self) -> None:
        """Initialize PostgreSQL with shared connection pool."""
        from sagaz.core.exceptions import MissingDependencyError

        try:
            import asyncpg
        except ImportError as exc:
            msg = "asyncpg"
            raise MissingDependencyError(msg, "PostgreSQL storage backend") from exc

        pool_min = self._kwargs.get("pool_min_size", 5)
        pool_max = self._kwargs.get("pool_max_size", 20)

        self._shared_pool = await asyncpg.create_pool(
            self._saga_url,
            min_size=pool_min,
            max_size=pool_max,
        )

        from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
        from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

        # Use local variables for typing
        assert self._saga_url is not None
        saga_storage = PostgreSQLSagaStorage(self._saga_url)
        saga_storage._pool = self._shared_pool
        self._saga_storage = cast("SagaStorage", saga_storage)

        outbox_storage = PostgreSQLOutboxStorage(self._saga_url)
        outbox_storage._pool = self._shared_pool
        self._outbox_storage = outbox_storage

        # Initialize schemas
        assert self._shared_pool is not None
        async with self._shared_pool.acquire() as conn:
            await conn.execute(PostgreSQLSagaStorage.CREATE_TABLES_SQL)
            from sagaz.core.storage.backends.postgresql.outbox import OUTBOX_SCHEMA

            await conn.execute(OUTBOX_SCHEMA)

    async def _initialize_redis_unified(self) -> None:
        """Initialize Redis with shared connection."""
        from sagaz.core.exceptions import MissingDependencyError

        try:
            import redis.asyncio as redis
        except ImportError as exc:
            msg = "redis"
            raise MissingDependencyError(msg, "Redis storage backend") from exc

        assert self._saga_url is not None
        self._shared_pool = redis.from_url(self._saga_url)

        from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage
        from sagaz.core.storage.backends.redis.saga import RedisSagaStorage

        saga_storage = RedisSagaStorage(self._saga_url)
        saga_storage._redis = self._shared_pool
        # Note: RedisSagaStorage uses _has_initialized, not _initialized
        self._saga_storage = cast("SagaStorage", saga_storage)

        assert self._saga_url is not None
        outbox_storage = RedisOutboxStorage(self._saga_url)
        outbox_storage._redis = self._shared_pool
        outbox_storage._initialized = True
        self._outbox_storage = outbox_storage

    async def _initialize_sqlite_unified(self) -> None:
        """Initialize SQLite (each storage gets own connection to same file)."""
        from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage

        db_path = self._saga_url
        if db_path and db_path.startswith("sqlite://"):
            db_path = db_path[9:] or ":memory:"

        # Use local variables
        saga_storage = SQLiteSagaStorage(db_path or ":memory:")
        outbox_storage = SQLiteOutboxStorage(db_path or ":memory:")

        # Initialize directly
        await saga_storage.initialize()
        await outbox_storage.initialize()

        self._saga_storage = cast("SagaStorage", saga_storage)
        self._outbox_storage = cast("OutboxStorage", outbox_storage)

    async def _initialize_hybrid(self, saga_type: str, outbox_type: str) -> None:
        """Initialize with different backends (no shared connection)."""
        # Initialize saga storage
        self._saga_storage = await self._create_saga_storage(saga_type, self._saga_url)

        # Initialize outbox storage
        self._outbox_storage = await self._create_outbox_storage(outbox_type, self._outbox_url)

    async def _create_saga_storage(self, backend_type: str, url: str | None) -> "SagaStorage":
        """Create and initialize saga storage for a backend type."""
        if backend_type == "memory":
            from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage

            return cast("SagaStorage", InMemorySagaStorage())

        if backend_type == "postgresql":
            return self._create_postgresql_saga(url)

        if backend_type == "redis":
            return self._create_redis_saga(url)

        if backend_type == "sqlite":
            return await self._create_sqlite_saga(url)

        msg = f"Unknown saga backend: {backend_type}"
        raise ValueError(msg)

    def _create_postgresql_saga(self, url: str | None) -> "SagaStorage":
        """Create PostgreSQL saga storage."""
        from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

        assert url is not None
        storage = PostgreSQLSagaStorage(url)
        # PostgreSQLSagaStorage doesn't have initialize(), it uses _get_pool() on demand
        return cast("SagaStorage", storage)

    def _create_redis_saga(self, url: str | None) -> "SagaStorage":
        """Create Redis saga storage."""
        from sagaz.core.storage.backends.redis.saga import RedisSagaStorage

        assert url is not None
        r_storage = RedisSagaStorage(url)
        # RedisSagaStorage doesn't have initialize(), uses different initialization
        return cast("SagaStorage", r_storage)

    async def _create_sqlite_saga(self, url: str | None) -> "SagaStorage":
        """Create and initialize SQLite saga storage."""
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage

        db_path = url[9:] if url and url.startswith("sqlite://") else (url or ":memory:")
        s_storage = SQLiteSagaStorage(db_path)
        await s_storage.initialize()
        return cast("SagaStorage", s_storage)

    async def _create_outbox_storage(self, backend_type: str, url: str | None) -> "OutboxStorage":
        """Create and initialize outbox storage for a backend type."""
        if backend_type == "memory":
            from sagaz.core.storage.backends.memory.outbox import (
                InMemoryOutboxStorage,
            )

            return cast("OutboxStorage", InMemoryOutboxStorage())

        if backend_type == "postgresql":
            return await self._create_postgresql_outbox(url)

        if backend_type == "redis":
            return await self._create_redis_outbox(url)

        if backend_type == "sqlite":
            return await self._create_sqlite_outbox(url)

        msg = f"Unknown outbox backend: {backend_type}"
        raise ValueError(msg)

    async def _create_postgresql_outbox(self, url: str | None) -> "OutboxStorage":
        """Create and initialize PostgreSQL outbox storage."""
        from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

        assert url is not None
        storage = PostgreSQLOutboxStorage(url)
        await storage.initialize()
        return cast("OutboxStorage", storage)

    async def _create_redis_outbox(self, url: str | None) -> "OutboxStorage":
        """Create and initialize Redis outbox storage."""
        from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage

        assert url is not None
        r_storage = RedisOutboxStorage(url)
        await r_storage.initialize()
        return cast("OutboxStorage", r_storage)

    async def _create_sqlite_outbox(self, url: str | None) -> "OutboxStorage":
        """Create and initialize SQLite outbox storage."""
        from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        db_path = url[9:] if url and url.startswith("sqlite://") else (url or ":memory:")
        s_storage = SQLiteOutboxStorage(db_path)
        await s_storage.initialize()
        return cast("OutboxStorage", s_storage)
