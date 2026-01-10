# ============================================
# FILE: sagaz/storage/backends/postgresql/snapshot.py
# ============================================

"""
PostgreSQL Snapshot Storage

PostgreSQL-based persistent storage for saga snapshots with ACID guarantees,
advanced querying, and referential integrity.

Requires: pip install asyncpg
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.replay import ReplayResult, SagaSnapshot, SnapshotNotFoundError
from sagaz.storage.interfaces.snapshot import SnapshotStorage

try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:  # pragma: no cover
    ASYNCPG_AVAILABLE = False  # pragma: no cover
    asyncpg = None  # pragma: no cover


class PostgreSQLSnapshotStorage(SnapshotStorage):
    """
    PostgreSQL implementation of snapshot storage

    Uses PostgreSQL for ACID-compliant snapshot storage with
    full SQL querying capabilities and referential integrity.

    Example:
        >>> async with PostgreSQLSnapshotStorage("postgresql://user:pass@localhost/db") as storage:
        ...     await storage.save_snapshot(snapshot)
    """

    # SQL schema for snapshot tables (from ADR-024)
    CREATE_TABLES_SQL = """
    -- Checkpoint snapshots for replay
    CREATE TABLE IF NOT EXISTS saga_snapshots (
        snapshot_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        saga_id          UUID NOT NULL,
        saga_name        VARCHAR(255) NOT NULL,
        step_name        VARCHAR(255) NOT NULL,
        step_index       INTEGER NOT NULL,

        -- State
        status           VARCHAR(50) NOT NULL,
        context          JSONB NOT NULL,
        completed_steps  JSONB NOT NULL,

        -- Metadata
        created_at       TIMESTAMPTZ DEFAULT NOW(),
        retention_until  TIMESTAMPTZ,

        -- Indexes
        CONSTRAINT idx_saga_snapshots_saga_id_step UNIQUE(saga_id, step_name, created_at)
    );

    CREATE INDEX IF NOT EXISTS idx_saga_snapshots_saga_id ON saga_snapshots(saga_id);
    CREATE INDEX IF NOT EXISTS idx_saga_snapshots_created_at ON saga_snapshots(created_at);
    CREATE INDEX IF NOT EXISTS idx_saga_snapshots_retention ON saga_snapshots(retention_until);

    -- Replay audit trail
    CREATE TABLE IF NOT EXISTS saga_replay_log (
        replay_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        original_saga_id UUID NOT NULL,
        new_saga_id      UUID NOT NULL,

        -- Replay parameters
        checkpoint_step  VARCHAR(255) NOT NULL,
        context_override JSONB,
        initiated_by     VARCHAR(255) NOT NULL,

        -- Results
        replay_status    VARCHAR(50) NOT NULL,
        error_message    TEXT,

        created_at       TIMESTAMPTZ DEFAULT NOW(),
        completed_at     TIMESTAMPTZ
    );

    CREATE INDEX IF NOT EXISTS idx_replay_log_original_saga ON saga_replay_log(original_saga_id);
    CREATE INDEX IF NOT EXISTS idx_replay_log_created_at ON saga_replay_log(created_at);
    """

    def __init__(
        self,
        connection_string: str,
        pool_min_size: int = 5,
        pool_max_size: int = 20,
        **pool_kwargs,
    ):
        if not ASYNCPG_AVAILABLE:
            msg = "asyncpg"
            raise MissingDependencyError(msg, "PostgreSQL snapshot storage backend")

        self.connection_string = connection_string
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self.pool_kwargs = pool_kwargs
        self._pool = None
        self._lock = asyncio.Lock()

    async def _get_pool(self):
        """Get connection pool, creating if necessary"""
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    self.connection_string,
                    min_size=self.pool_min_size,
                    max_size=self.pool_max_size,
                    **self.pool_kwargs,
                )
                # Create tables if they don't exist
                async with self._pool.acquire() as conn:
                    await conn.execute(self.CREATE_TABLES_SQL)
            except Exception as e:  # pragma: no cover
                msg = f"Failed to connect to PostgreSQL: {e}"  # pragma: no cover
                raise ConnectionError(msg)  # pragma: no cover

        return self._pool

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """Save snapshot to PostgreSQL"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO saga_snapshots (
                    snapshot_id, saga_id, saga_name, step_name, step_index,
                    status, context, completed_steps, created_at, retention_until
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (saga_id, step_name, created_at) DO UPDATE
                SET
                    snapshot_id = EXCLUDED.snapshot_id,
                    status = EXCLUDED.status,
                    context = EXCLUDED.context,
                    completed_steps = EXCLUDED.completed_steps,
                    retention_until = EXCLUDED.retention_until
                """,
                snapshot.snapshot_id,
                snapshot.saga_id,
                snapshot.saga_name,
                snapshot.step_name,
                snapshot.step_index,
                snapshot.status.value,
                json.dumps(snapshot.context),
                json.dumps(snapshot.completed_steps),
                snapshot.created_at,
                snapshot.retention_until,
            )

    async def get_snapshot(self, snapshot_id: UUID) -> SagaSnapshot | None:
        """Retrieve snapshot by ID"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT snapshot_id, saga_id, saga_name, step_name, step_index,
                       status, context, completed_steps, created_at, retention_until
                FROM saga_snapshots
                WHERE snapshot_id = $1
                """,
                snapshot_id,
            )

            if row is None:
                return None

            return self._row_to_snapshot(row)

    async def get_latest_snapshot(
        self, saga_id: UUID, before_step: str | None = None
    ) -> SagaSnapshot | None:
        """Get most recent snapshot for saga"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            if before_step:
                row = await conn.fetchrow(
                    """
                    SELECT snapshot_id, saga_id, saga_name, step_name, step_index,
                           status, context, completed_steps, created_at, retention_until
                    FROM saga_snapshots
                    WHERE saga_id = $1 AND step_name = $2
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    saga_id,
                    before_step,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT snapshot_id, saga_id, saga_name, step_name, step_index,
                           status, context, completed_steps, created_at, retention_until
                    FROM saga_snapshots
                    WHERE saga_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    saga_id,
                )

            if row is None:
                return None

            return self._row_to_snapshot(row)

    async def get_snapshot_at_time(self, saga_id: UUID, timestamp: datetime) -> SagaSnapshot | None:
        """Get snapshot at or before given timestamp"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT snapshot_id, saga_id, saga_name, step_name, step_index,
                       status, context, completed_steps, created_at, retention_until
                FROM saga_snapshots
                WHERE saga_id = $1 AND created_at <= $2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                saga_id,
                timestamp,
            )

            if row is None:
                return None

            return self._row_to_snapshot(row)

    async def list_snapshots(self, saga_id: UUID, limit: int = 100) -> list[SagaSnapshot]:
        """List all snapshots for saga"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT snapshot_id, saga_id, saga_name, step_name, step_index,
                       status, context, completed_steps, created_at, retention_until
                FROM saga_snapshots
                WHERE saga_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                saga_id,
                limit,
            )

            return [self._row_to_snapshot(row) for row in rows]

    async def delete_snapshot(self, snapshot_id: UUID) -> bool:
        """Delete snapshot"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM saga_snapshots
                WHERE snapshot_id = $1
                """,
                snapshot_id,
            )

            return result == "DELETE 1"

    async def delete_expired_snapshots(self) -> int:
        """Delete expired snapshots"""
        pool = await self._get_pool()
        now = datetime.now(UTC)

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM saga_snapshots
                WHERE retention_until IS NOT NULL
                  AND retention_until < $1
                """,
                now,
            )

            # Parse "DELETE N" result
            return int(result.split()[-1]) if result.startswith("DELETE") else 0

    async def save_replay_log(self, replay_result: ReplayResult) -> None:
        """Save replay log"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO saga_replay_log (
                    replay_id, original_saga_id, new_saga_id,
                    checkpoint_step, context_override, initiated_by,
                    replay_status, error_message, created_at, completed_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                replay_result.replay_id,
                replay_result.original_saga_id,
                replay_result.new_saga_id,
                replay_result.checkpoint_step,
                json.dumps(replay_result.context_override)
                if replay_result.context_override
                else None,
                replay_result.initiated_by,
                replay_result.status,
                replay_result.error,
                replay_result.created_at,
                replay_result.completed_at,
            )

    async def get_replay_log(self, replay_id: UUID) -> dict[str, Any] | None:
        """Get replay log entry"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT replay_id, original_saga_id, new_saga_id,
                       checkpoint_step, context_override, initiated_by,
                       replay_status, error_message, created_at, completed_at
                FROM saga_replay_log
                WHERE replay_id = $1
                """,
                replay_id,
            )

            if row is None:
                return None

            return {
                "replay_id": str(row["replay_id"]),
                "original_saga_id": str(row["original_saga_id"]),
                "new_saga_id": str(row["new_saga_id"]),
                "checkpoint_step": row["checkpoint_step"],
                "context_override": json.loads(row["context_override"])
                if row["context_override"]
                else None,
                "initiated_by": row["initiated_by"],
                "status": row["replay_status"],
                "error": row["error_message"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            }

    async def list_replays(self, original_saga_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
        """List replays for original saga"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT replay_id, original_saga_id, new_saga_id,
                       checkpoint_step, context_override, initiated_by,
                       replay_status, error_message, created_at, completed_at
                FROM saga_replay_log
                WHERE original_saga_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                original_saga_id,
                limit,
            )

            return [
                {
                    "replay_id": str(row["replay_id"]),
                    "original_saga_id": str(row["original_saga_id"]),
                    "new_saga_id": str(row["new_saga_id"]),
                    "checkpoint_step": row["checkpoint_step"],
                    "context_override": json.loads(row["context_override"])
                    if row["context_override"]
                    else None,
                    "initiated_by": row["initiated_by"],
                    "status": row["replay_status"],
                    "error": row["error_message"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "completed_at": row["completed_at"].isoformat()
                    if row["completed_at"]
                    else None,
                }
                for row in rows
            ]

    def _row_to_snapshot(self, row) -> SagaSnapshot:
        """Convert database row to SagaSnapshot"""
        from sagaz.core.types import SagaStatus

        return SagaSnapshot(
            snapshot_id=row["snapshot_id"],
            saga_id=row["saga_id"],
            saga_name=row["saga_name"],
            step_name=row["step_name"],
            step_index=row["step_index"],
            status=SagaStatus(row["status"]),
            context=json.loads(row["context"])
            if isinstance(row["context"], str)
            else row["context"],
            completed_steps=json.loads(row["completed_steps"])
            if isinstance(row["completed_steps"], str)
            else row["completed_steps"],
            created_at=row["created_at"],
            retention_until=row["retention_until"],
        )

    async def close(self) -> None:
        """Close connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def __aenter__(self):
        """Context manager entry"""
        await self._get_pool()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.close()
