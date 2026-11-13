"""Replay audit-log persistence for :class:`PostgreSQLSnapshotStorage`."""

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sagaz.core.replay import ReplayResult


class _PostgreSQLReplayLogMixin:
    """Reads and writes rows of the ``saga_replay_log`` table."""

    if TYPE_CHECKING:

        async def _get_pool(self) -> Any: ...

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
                replay_result.replay_status.value
                if hasattr(replay_result.replay_status, "value")
                else replay_result.replay_status,
                replay_result.error_message,
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
