"""
Tests for Saga Replay functionality.
"""

import pytest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sagaz.core.replay import (
    ReplayConfig,
    ReplayError,
    ReplayRequest,
    ReplayResult,
    ReplayStatus,
    SagaSnapshot,
    SnapshotNotFoundError,
    SnapshotStrategy,
)
from sagaz.core.saga_replay import SagaReplay
from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage


class TestReplayConfig:
    """Test replay configuration"""

    def test_default_config(self):
        config = ReplayConfig()
        assert config.enable_snapshots is False
        assert config.snapshot_strategy == SnapshotStrategy.ON_FAILURE
        assert config.retention_days == 30
        assert config.compression is None

    def test_custom_config(self):
        config = ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
            retention_days=365,
            compression="zstd",
        )
        assert config.enable_snapshots is True
        assert config.snapshot_strategy == SnapshotStrategy.BEFORE_EACH_STEP
        assert config.retention_days == 365
        assert config.compression == "zstd"

    def test_get_retention_until(self):
        config = ReplayConfig(retention_days=7)
        retention = config.get_retention_until()
        
        # Should be approximately 7 days from now
        expected = datetime.now(UTC) + timedelta(days=7)
        assert abs((retention - expected).total_seconds()) < 5  # Within 5 seconds


class TestSagaSnapshot:
    """Test snapshot data structure"""

    def test_create_snapshot(self):
        saga_id = uuid4()
        snapshot = SagaSnapshot.create(
            saga_id=saga_id,
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={"key": "value"},
            completed_steps=[],
        )

        assert snapshot.saga_id == saga_id
        assert snapshot.saga_name == "TestSaga"
        assert snapshot.step_name == "step1"
        assert snapshot.context == {"key": "value"}
        assert isinstance(snapshot.snapshot_id, type(saga_id))
        assert isinstance(snapshot.created_at, datetime)

    def test_snapshot_defensive_copy(self):
        """Ensure snapshot makes defensive copies"""
        original_context = {"key": "value"}
        original_steps = ["step1"]

        snapshot = SagaSnapshot.create(
            saga_id=uuid4(),
            saga_name="Test",
            step_name="step1",
            step_index=0,
            status="executing",
            context=original_context,
            completed_steps=original_steps,
        )

        # Modify originals
        original_context["key"] = "modified"
        original_steps.append("step2")

        # Snapshot should be unchanged
        assert snapshot.context["key"] == "value"
        assert snapshot.completed_steps == ["step1"]

    def test_snapshot_to_dict(self):
        snapshot = SagaSnapshot.create(
            saga_id=uuid4(),
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={"key": "value"},
            completed_steps=["step0"],
        )

        data = snapshot.to_dict()

        assert "snapshot_id" in data
        assert "saga_id" in data
        assert data["saga_name"] == "TestSaga"
        assert data["step_name"] == "step1"
        assert data["context"] == {"key": "value"}
        assert data["completed_steps"] == ["step0"]

    def test_snapshot_from_dict(self):
        original = SagaSnapshot.create(
            saga_id=uuid4(),
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={"key": "value"},
            completed_steps=[],
        )

        data = original.to_dict()
        restored = SagaSnapshot.from_dict(data)

        assert restored.saga_id == original.saga_id
        assert restored.saga_name == original.saga_name
        assert restored.step_name == original.step_name
        assert restored.context == original.context


class TestReplayRequest:
    """Test replay request"""

    def test_merge_context_no_override(self):
        request = ReplayRequest(
            original_saga_id=uuid4(),
            checkpoint_step="step1",
        )

        original = {"key1": "value1", "key2": "value2"}
        merged = request.merge_context(original)

        assert merged == original
        assert merged is not original  # Defensive copy

    def test_merge_context_with_override(self):
        request = ReplayRequest(
            original_saga_id=uuid4(),
            checkpoint_step="step1",
            context_override={"key2": "overridden", "key3": "new"},
        )

        original = {"key1": "value1", "key2": "value2"}
        merged = request.merge_context(original)

        assert merged == {
            "key1": "value1",
            "key2": "overridden",  # Overridden
            "key3": "new",  # Added
        }


class TestReplayResult:
    """Test replay result"""

    def test_mark_success(self):
        result = ReplayResult(
            replay_id=uuid4(),
            original_saga_id=uuid4(),
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.RUNNING,
        )

        result.mark_success()

        assert result.replay_status == ReplayStatus.SUCCESS
        assert result.completed_at is not None
        assert result.error_message is None

    def test_mark_failed(self):
        result = ReplayResult(
            replay_id=uuid4(),
            original_saga_id=uuid4(),
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.RUNNING,
        )

        result.mark_failed("Test error")

        assert result.replay_status == ReplayStatus.FAILED
        assert result.completed_at is not None
        assert result.error_message == "Test error"

    def test_to_dict(self):
        result = ReplayResult(
            replay_id=uuid4(),
            original_saga_id=uuid4(),
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.SUCCESS,
        )

        data = result.to_dict()

        assert "replay_id" in data
        assert "original_saga_id" in data
        assert "new_saga_id" in data
        assert data["checkpoint_step"] == "step1"
        assert data["replay_status"] == "success"


class TestInMemorySnapshotStorage:
    """Test in-memory snapshot storage"""

    @pytest.fixture
    def storage(self):
        return InMemorySnapshotStorage()

    @pytest.mark.asyncio
    async def test_save_and_get_snapshot(self, storage):
        snapshot = SagaSnapshot.create(
            saga_id=uuid4(),
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={"key": "value"},
            completed_steps=[],
        )

        await storage.save_snapshot(snapshot)
        retrieved = await storage.get_snapshot(snapshot.snapshot_id)

        assert retrieved is not None
        assert retrieved.snapshot_id == snapshot.snapshot_id
        assert retrieved.context == snapshot.context

    @pytest.mark.asyncio
    async def test_get_nonexistent_snapshot(self, storage):
        result = await storage.get_snapshot(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_snapshot(self, storage):
        saga_id = uuid4()

        # Create multiple snapshots
        snap1 = SagaSnapshot.create(
            saga_id=saga_id,
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={},
            completed_steps=[],
        )
        await storage.save_snapshot(snap1)

        snap2 = SagaSnapshot.create(
            saga_id=saga_id,
            saga_name="TestSaga",
            step_name="step2",
            step_index=1,
            status="executing",
            context={},
            completed_steps=["step1"],
        )
        await storage.save_snapshot(snap2)

        latest = await storage.get_latest_snapshot(saga_id)
        assert latest is not None
        assert latest.step_name == "step2"

    @pytest.mark.asyncio
    async def test_list_snapshots(self, storage):
        saga_id = uuid4()

        # Create 3 snapshots
        for i in range(3):
            snap = SagaSnapshot.create(
                saga_id=saga_id,
                saga_name="TestSaga",
                step_name=f"step{i}",
                step_index=i,
                status="executing",
                context={},
                completed_steps=[],
            )
            await storage.save_snapshot(snap)

        snapshots = await storage.list_snapshots(saga_id)
        assert len(snapshots) == 3
        # Should be ordered by created_at DESC
        assert snapshots[0].step_name == "step2"

    @pytest.mark.asyncio
    async def test_delete_snapshot(self, storage):
        snapshot = SagaSnapshot.create(
            saga_id=uuid4(),
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={},
            completed_steps=[],
        )

        await storage.save_snapshot(snapshot)
        deleted = await storage.delete_snapshot(snapshot.snapshot_id)
        assert deleted is True

        retrieved = await storage.get_snapshot(snapshot.snapshot_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots(self, storage):
        # Create expired snapshot
        expired_snapshot = SagaSnapshot.create(
            saga_id=uuid4(),
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={},
            completed_steps=[],
            retention_until=datetime.now(UTC) - timedelta(days=1),  # Expired
        )
        await storage.save_snapshot(expired_snapshot)

        # Create non-expired snapshot
        valid_snapshot = SagaSnapshot.create(
            saga_id=uuid4(),
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={},
            completed_steps=[],
            retention_until=datetime.now(UTC) + timedelta(days=1),  # Valid
        )
        await storage.save_snapshot(valid_snapshot)

        deleted_count = await storage.delete_expired_snapshots()
        assert deleted_count == 1

        # Expired should be gone
        assert await storage.get_snapshot(expired_snapshot.snapshot_id) is None
        # Valid should remain
        assert await storage.get_snapshot(valid_snapshot.snapshot_id) is not None


class TestSagaReplay:
    """Test saga replay engine"""

    @pytest.fixture
    def storage(self):
        return InMemorySnapshotStorage()

    @pytest.fixture
    def saga_id(self):
        return uuid4()

    @pytest.mark.asyncio
    async def test_replay_from_checkpoint_not_found(self, storage, saga_id):
        replay = SagaReplay(saga_id=saga_id, snapshot_storage=storage)

        with pytest.raises(SnapshotNotFoundError):
            await replay.from_checkpoint(step_name="nonexistent_step")

    @pytest.mark.asyncio
    async def test_replay_from_checkpoint_success(self, storage, saga_id):
        # Create a snapshot
        snapshot = SagaSnapshot.create(
            saga_id=saga_id,
            saga_name="TestSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={"original": "value"},
            completed_steps=[],
        )
        await storage.save_snapshot(snapshot)

        # Replay from checkpoint
        replay = SagaReplay(saga_id=saga_id, snapshot_storage=storage)
        result = await replay.from_checkpoint(
            step_name="step1",
            context_override={"new": "override"},
        )

        assert result.replay_status == ReplayStatus.SUCCESS
        assert result.original_saga_id == saga_id
        assert result.new_saga_id != saga_id  # New ID for replayed execution
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_replay_dry_run(self, storage, saga_id):
        # Create a snapshot
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

        # Dry run replay
        replay = SagaReplay(saga_id=saga_id, snapshot_storage=storage)
        result = await replay.from_checkpoint(step_name="step1", dry_run=True)

        assert result.replay_status == ReplayStatus.SUCCESS
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_list_available_checkpoints(self, storage, saga_id):
        # Create multiple snapshots
        for i in range(3):
            snapshot = SagaSnapshot.create(
                saga_id=saga_id,
                saga_name="TestSaga",
                step_name=f"step{i}",
                step_index=i,
                status="executing",
                context={},
                completed_steps=[],
            )
            await storage.save_snapshot(snapshot)

        replay = SagaReplay(saga_id=saga_id, snapshot_storage=storage)
        checkpoints = await replay.list_available_checkpoints()

        assert len(checkpoints) == 3
        assert all("step_name" in cp for cp in checkpoints)
        assert all("created_at" in cp for cp in checkpoints)

    @pytest.mark.asyncio
    async def test_get_replay_history(self, storage, saga_id):
        # Create a snapshot
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

        # Execute replay
        replay = SagaReplay(saga_id=saga_id, snapshot_storage=storage)
        await replay.from_checkpoint(step_name="step1")

        # Check history
        history = await replay.get_replay_history()
        assert len(history) == 1
        assert history[0]["original_saga_id"] == str(saga_id)
