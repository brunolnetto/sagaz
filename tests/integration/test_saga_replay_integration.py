"""
Integration tests for Saga Replay with actual saga execution.

Tests the complete replay flow: snapshot capture, resume from checkpoint, etc.
"""

from uuid import UUID, uuid4

import pytest

from sagaz.core.context import SagaContext
from sagaz.core.replay import ReplayConfig, SnapshotStrategy
from sagaz.core.saga import Saga
from sagaz.core.saga_replay import SagaReplay
from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage


# Sample saga for integration tests
class SimpleSagaForReplay(Saga):
    """Simple saga for testing replay functionality"""

    def __init__(self, fail_at_step: str | None = None, **kwargs):
        super().__init__(name="TestReplaySaga", **kwargs)
        self.fail_at_step = fail_at_step
        self.execution_log: list[str] = []

    async def build(self):
        await self.add_step("step1", self._step1_action, self._step1_compensation)
        await self.add_step("step2", self._step2_action, self._step2_compensation)
        await self.add_step("step3", self._step3_action, self._step3_compensation)

    async def _step1_action(self, ctx: SagaContext):
        self.execution_log.append("step1_executed")
        if self.fail_at_step == "step1":
            msg = "Simulated failure at step1"
            raise RuntimeError(msg)
        ctx.set("step1_result", "step1_done")
        return "step1_done"

    async def _step1_compensation(self, result, ctx: SagaContext):
        self.execution_log.append("step1_compensated")

    async def _step2_action(self, ctx: SagaContext):
        self.execution_log.append("step2_executed")
        if self.fail_at_step == "step2":
            msg = "Simulated failure at step2"
            raise RuntimeError(msg)
        ctx.set("step2_result", "step2_done")
        return "step2_done"

    async def _step2_compensation(self, result, ctx: SagaContext):
        self.execution_log.append("step2_compensated")

    async def _step3_action(self, ctx: SagaContext):
        self.execution_log.append("step3_executed")
        if self.fail_at_step == "step3":
            msg = "Simulated failure at step3"
            raise RuntimeError(msg)
        ctx.set("step3_result", "step3_done")
        return "step3_done"

    async def _step3_compensation(self, result, ctx: SagaContext):
        self.execution_log.append("step3_compensated")


class TestSagaSnapshotCapture:
    """Test snapshot capture during saga execution"""

    @pytest.mark.asyncio
    async def test_snapshot_capture_before_each_step(self):
        storage = InMemorySnapshotStorage()
        config = ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
            retention_days=30,
        )

        saga = SimpleSagaForReplay(replay_config=config, snapshot_storage=storage)
        await saga.build()
        result = await saga.execute()

        assert result.success is True

        # Should have 3 snapshots (one before each step)
        snapshots = await storage.list_snapshots(UUID(saga.saga_id))
        assert len(snapshots) >= 3

        # Verify snapshot content
        first_snapshot = snapshots[-1]  # Oldest (before step1)
        assert first_snapshot.step_name == "step1"
        assert first_snapshot.step_index == 0
        assert first_snapshot.completed_steps == []

    @pytest.mark.asyncio
    async def test_snapshot_capture_after_each_step(self):
        storage = InMemorySnapshotStorage()
        config = ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.AFTER_EACH_STEP,
            retention_days=30,
        )

        saga = SimpleSagaForReplay(replay_config=config, snapshot_storage=storage)
        await saga.build()
        result = await saga.execute()

        assert result.success is True

        # Should have snapshots after each step
        snapshots = await storage.list_snapshots(UUID(saga.saga_id))
        assert len(snapshots) >= 3

    @pytest.mark.asyncio
    async def test_snapshot_disabled_by_default(self):
        storage = InMemorySnapshotStorage()
        # No replay_config provided - snapshots disabled
        saga = SimpleSagaForReplay()
        await saga.build()
        result = await saga.execute()

        assert result.success is True

        # No snapshots should be captured
        snapshots = await storage.list_snapshots(UUID(saga.saga_id))
        assert len(snapshots) == 0


class TestSagaReplayIntegration:
    """Test complete replay flow with saga execution"""

    @pytest.fixture
    def storage(self):
        return InMemorySnapshotStorage()

    @pytest.fixture
    def replay_config(self):
        return ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
            retention_days=30,
        )

    def saga_factory(self, saga_name: str) -> Saga:
        """Factory to create saga instances for replay"""
        storage = InMemorySnapshotStorage()
        config = ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
        )
        return SimpleSagaForReplay(replay_config=config, snapshot_storage=storage)

    @pytest.mark.asyncio
    async def test_replay_from_step2_after_step1_failure(self, storage, replay_config):
        # Step 1: Execute saga that fails at step2
        saga = SimpleSagaForReplay(
            fail_at_step="step2", replay_config=replay_config, snapshot_storage=storage
        )
        await saga.build()
        result = await saga.execute()

        assert result.success is False
        assert "step1_executed" in saga.execution_log
        assert "step2_executed" in saga.execution_log
        assert "step3_executed" not in saga.execution_log

        original_saga_id = UUID(saga.saga_id)

        # Step 2: Create async saga factory that builds the saga
        async def async_saga_factory(name: str):
            saga = SimpleSagaForReplay(
                replay_config=replay_config, snapshot_storage=storage
            )
            await saga.build()
            return saga

        # Step 3: Replay from step2 with fixed saga
        replay = SagaReplay(
            saga_id=original_saga_id,
            snapshot_storage=storage,
            saga_factory=async_saga_factory,
        )

        # Get available checkpoints
        checkpoints = await replay.list_available_checkpoints()
        assert len(checkpoints) >= 1

        # Replay from step2 (step1 should be skipped)
        replay_result = await replay.from_checkpoint(step_name="step2")

        assert replay_result.replay_status.value == "success"
        assert replay_result.original_saga_id == original_saga_id
        assert replay_result.new_saga_id != original_saga_id

    @pytest.mark.asyncio
    async def test_resume_with_context_override(self, storage, replay_config):
        # Step 1: Execute first saga
        saga = SimpleSagaForReplay(replay_config=replay_config, snapshot_storage=storage)
        await saga.build()
        saga.context.set("payment_token", "old_token")
        result = await saga.execute()

        assert result.success is True
        original_saga_id = UUID(saga.saga_id)

        # Step 2: Create snapshot for replay simulation
        from sagaz.core.replay import SagaSnapshot

        snapshot = SagaSnapshot.create(
            saga_id=original_saga_id,
            saga_name="TestReplaySaga",
            step_name="step2",
            step_index=1,
            status="executing",
            context={
                "step1_result": "step1_done",
                "payment_token": "old_token",
            },
            completed_steps=["step1"],
        )
        await storage.save_snapshot(snapshot)

        # Step 3: Replay with context override
        async def async_saga_factory(name: str):
            saga = SimpleSagaForReplay(
                replay_config=replay_config, snapshot_storage=storage
            )
            await saga.build()
            return saga

        replay = SagaReplay(
            saga_id=original_saga_id,
            snapshot_storage=storage,
            saga_factory=async_saga_factory,
        )

        replay_result = await replay.from_checkpoint(
            step_name="step2",
            context_override={
                "payment_token": "new_corrected_token",
                "retry_count": 1,
            },
        )

        assert replay_result.replay_status.value == "success"

    @pytest.mark.asyncio
    async def test_replay_skips_completed_steps(self, storage, replay_config):
        # Create saga and execute normally
        saga = SimpleSagaForReplay(replay_config=replay_config, snapshot_storage=storage)
        await saga.build()
        result = await saga.execute()

        assert result.success is True
        assert "step1_executed" in saga.execution_log
        assert "step2_executed" in saga.execution_log
        assert "step3_executed" in saga.execution_log

        original_saga_id = UUID(saga.saga_id)

        # Create new saga instance for replay
        saga2 = SimpleSagaForReplay(replay_config=replay_config, snapshot_storage=storage)
        await saga2.build()

        # Get snapshot at step2 (step1 already completed)
        snapshots = await storage.list_snapshots(original_saga_id)
        step2_snapshot = next(s for s in snapshots if s.step_name == "step2")

        # Verify step1 is marked as completed in this snapshot
        assert "step1" in step2_snapshot.completed_steps

        # Execute from snapshot
        replay_result = await saga2.execute_from_snapshot(
            step2_snapshot, context_override=None
        )

        assert replay_result.success is True
        # step1 should be skipped (already completed in snapshot)
        assert "step1_executed" not in saga2.execution_log
        assert "step2_executed" in saga2.execution_log
        assert "step3_executed" in saga2.execution_log


class TestReplayErrorHandling:
    """Test error handling in replay scenarios"""

    @pytest.mark.asyncio
    async def test_replay_without_saga_factory_requires_dry_run(self):
        storage = InMemorySnapshotStorage()

        # Create a snapshot
        from sagaz.core.replay import SagaSnapshot
        saga_id = uuid4()
        snapshot = SagaSnapshot.create(
            saga_id=saga_id,
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={},
            completed_steps=[],
        )
        await storage.save_snapshot(snapshot)

        # Replay without saga_factory should require dry_run
        replay = SagaReplay(saga_id=saga_id, snapshot_storage=storage)

        # This should fail without dry_run
        from sagaz.core.replay import ReplayError
        with pytest.raises(ReplayError, match="no saga_factory provided"):
            await replay.from_checkpoint(step_name="step1", dry_run=False)

        # But should work with dry_run
        result = await replay.from_checkpoint(step_name="step1", dry_run=True)
        assert result.replay_status.value == "success"

    @pytest.mark.asyncio
    async def test_replay_marks_failure_when_saga_fails(self):
        storage = InMemorySnapshotStorage()
        config = ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
        )

        # Execute saga that fails
        saga = SimpleSagaForReplay(fail_at_step="step2", replay_config=config, snapshot_storage=storage)
        await saga.build()
        await saga.execute()

        original_saga_id = UUID(saga.saga_id)

        # Try to replay with same failure
        async def async_saga_factory(name: str):
            saga = SimpleSagaForReplay(
                fail_at_step="step2",  # Still fails
                replay_config=config,
                snapshot_storage=storage,
            )
            await saga.build()
            return saga

        replay = SagaReplay(
            saga_id=original_saga_id,
            snapshot_storage=storage,
            saga_factory=async_saga_factory,
        )

        replay_result = await replay.from_checkpoint(step_name="step2")

        # Replay should be marked as failed
        assert replay_result.replay_status.value == "failed"
        assert replay_result.error_message is not None
        assert "step2" in replay_result.error_message or "Simulated" in replay_result.error_message
