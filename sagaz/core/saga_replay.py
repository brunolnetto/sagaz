# ============================================
# FILE: sagaz/core/saga_replay.py
# ============================================

"""
Saga Replay Engine

Implements replay-from-checkpoint functionality with context override.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:  # pragma: no cover
    from sagaz.core.saga import Saga

from sagaz.core.replay import (
    ReplayError,
    ReplayRequest,
    ReplayResult,
    ReplayStatus,
    SnapshotNotFoundError,
)
from sagaz.storage.interfaces.snapshot import SnapshotStorage

logger = logging.getLogger(__name__)


class SagaReplay:
    """
    Replay a saga from a checkpoint with optional context override.

    Example:
        replay = SagaReplay(
            saga_id=UUID("abc-123"),
            snapshot_storage=storage,
            saga_factory=my_saga_factory  # Function that creates saga instance
        )
        result = await replay.from_checkpoint(
            step_name="charge_payment",
            context_override={"payment_token": "new_token"}
        )
    """

    def __init__(
        self,
        saga_id: UUID,
        snapshot_storage: SnapshotStorage,
        initiated_by: str = "system",
        saga_factory: "Callable[[str], Saga] | None" = None,
    ):
        self.saga_id = saga_id
        self.snapshot_storage = snapshot_storage
        self.initiated_by = initiated_by
        self.saga_factory = saga_factory

    async def from_checkpoint(
        self,
        step_name: str,
        context_override: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> ReplayResult:
        """
        Replay saga from a checkpoint step.

        Args:
            step_name: Name of step to resume from
            context_override: Optional context modifications
            dry_run: If True, validate but don't execute

        Returns:
            ReplayResult with outcome

        Raises:
            SnapshotNotFoundError: If no snapshot found at checkpoint
            ReplayError: If replay fails
        """
        logger.info(
            f"Replay request: saga_id={self.saga_id}, "
            f"checkpoint={step_name}, dry_run={dry_run}"
        )

        # Create request
        request = ReplayRequest(
            original_saga_id=self.saga_id,
            checkpoint_step=step_name,
            context_override=context_override,
            initiated_by=self.initiated_by,
            dry_run=dry_run,
        )

        # Initialize result
        result = ReplayResult(
            replay_id=uuid4(),
            original_saga_id=self.saga_id,
            new_saga_id=uuid4(),  # New saga ID for replayed execution
            checkpoint_step=step_name,
            replay_status=ReplayStatus.PENDING,
        )

        try:
            # 1. Load snapshot at checkpoint
            snapshot = await self.snapshot_storage.get_latest_snapshot(
                saga_id=self.saga_id, before_step=step_name
            )

            if not snapshot:
                raise SnapshotNotFoundError(
                    f"No snapshot found for saga {self.saga_id} at step '{step_name}'"
                )

            logger.info(
                f"Loaded snapshot: {snapshot.snapshot_id} "
                f"(created at {snapshot.created_at})"
            )

            # 2. Merge context
            merged_context = request.merge_context(snapshot.context)

            logger.info(
                f"Context merged: {len(snapshot.context)} original keys, "
                f"{len(context_override or {})} overrides"
            )

            # 3. Validate if dry run
            if dry_run:
                logger.info("Dry run mode: Validation passed, not executing")
                result.replay_status = ReplayStatus.SUCCESS
                result.completed_at = result.created_at
                await self.snapshot_storage.save_replay_log(result)
                return result

            # 4. Execute replay - create saga instance and resume
            if not self.saga_factory:
                raise ReplayError(
                    "Cannot execute replay: no saga_factory provided. "
                    "Use dry_run=True for validation only."
                )

            result.replay_status = ReplayStatus.RUNNING

            # Create saga instance (handle both sync and async factories)
            import inspect
            if inspect.iscoroutinefunction(self.saga_factory):
                saga_instance = await self.saga_factory(snapshot.saga_name)
            else:
                saga_instance = self.saga_factory(snapshot.saga_name)
            
            saga_instance.saga_id = str(result.new_saga_id)

            # Execute from snapshot
            saga_result = await saga_instance.execute_from_snapshot(
                snapshot, context_override
            )

            if saga_result.success:
                result.mark_success()
                logger.info(
                    f"Replay successful: new_saga_id={result.new_saga_id}, "
                    f"original_saga_id={result.original_saga_id}"
                )
            else:
                result.mark_failed(str(saga_result.error))
                logger.error(
                    f"Replay failed: {saga_result.error}"
                )

            # 5. Log replay
            await self.snapshot_storage.save_replay_log(result)

            return result

        except SnapshotNotFoundError as e:
            logger.error(f"Snapshot not found: {e}")
            result.mark_failed(str(e))
            await self.snapshot_storage.save_replay_log(result)
            raise

        except Exception as e:
            logger.error(f"Replay failed: {e}", exc_info=True)
            result.mark_failed(str(e))
            await self.snapshot_storage.save_replay_log(result)
            raise ReplayError(f"Replay failed: {e}") from e

    async def list_available_checkpoints(self) -> list[dict[str, Any]]:
        """
        List all available checkpoints for this saga.

        Returns:
            List of checkpoint information
        """
        snapshots = await self.snapshot_storage.list_snapshots(self.saga_id)

        return [
            {
                "step_name": s.step_name,
                "step_index": s.step_index,
                "status": s.status,
                "created_at": s.created_at.isoformat(),
                "snapshot_id": str(s.snapshot_id),
            }
            for s in snapshots
        ]

    async def get_replay_history(self) -> list[dict[str, Any]]:
        """
        Get history of all replay operations for this saga.

        Returns:
            List of replay log entries
        """
        return await self.snapshot_storage.list_replays(self.saga_id)
