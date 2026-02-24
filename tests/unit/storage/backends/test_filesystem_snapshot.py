"""
Unit tests for Filesystem Snapshot Storage backend.

Tests basic functionality without requiring external dependencies.
"""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from sagaz.core.replay import ReplayResult, ReplayStatus, SagaSnapshot
from sagaz.core.types import SagaStatus
from sagaz.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage


class TestFilesystemSnapshotStorage:
    """Tests for FilesystemSnapshotStorage"""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests"""
        temp_path = tempfile.mkdtemp()
        yield temp_path
        shutil.rmtree(temp_path, ignore_errors=True)

    @pytest.fixture
    async def storage(self, temp_dir):
        """Create storage instance"""
        storage = FilesystemSnapshotStorage(
            base_path=temp_dir,
            enable_compression=False,
            pretty_json=True,
        )
        yield storage
        await storage.close()

    @pytest.mark.asyncio
    async def test_initialization(self, temp_dir):
        """Test storage initialization creates directory structure"""
        storage = FilesystemSnapshotStorage(base_path=temp_dir)

        assert (Path(temp_dir) / "snapshots").exists()
        assert (Path(temp_dir) / "indexes").exists()
        assert (Path(temp_dir) / "replays").exists()

    @pytest.mark.asyncio
    async def test_save_and_get_snapshot(self, storage):
        """Test saving and retrieving a snapshot"""
        saga_id = uuid4()
        snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="test_saga",
            step_name="step1",
            step_index=1,
            status=SagaStatus.EXECUTING,
            context={"key": "value", "amount": 100},
            completed_steps=["step0"],
            created_at=datetime.now(UTC),
        )

        # Save
        await storage.save_snapshot(snapshot)

        # Retrieve by ID
        retrieved = await storage.get_snapshot(snapshot.snapshot_id)
        assert retrieved is not None
        assert retrieved.snapshot_id == snapshot.snapshot_id
        assert retrieved.saga_id == saga_id
        assert retrieved.context["key"] == "value"
        assert retrieved.step_name == "step1"

    @pytest.mark.asyncio
    async def test_get_latest_snapshot(self, storage):
        """Test getting most recent snapshot"""
        saga_id = uuid4()

        # Create multiple snapshots
        for i in range(3):
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="test_saga",
                step_name=f"step{i}",
                step_index=i,
                status=SagaStatus.EXECUTING,
                context={"step": i},
                completed_steps=[],
                created_at=datetime.now(UTC),
            )
            await storage.save_snapshot(snapshot)

        # Get latest
        latest = await storage.get_latest_snapshot(saga_id)
        assert latest is not None
        assert latest.step_name == "step2"  # Most recent

    @pytest.mark.asyncio
    async def test_list_snapshots(self, storage):
        """Test listing all snapshots for a saga"""
        saga_id = uuid4()

        # Create snapshots
        snapshot_ids = []
        for i in range(5):
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="test_saga",
                step_name=f"step{i}",
                step_index=i,
                status=SagaStatus.EXECUTING,
                context={},
                completed_steps=[],
                created_at=datetime.now(UTC),
            )
            snapshot_ids.append(snapshot.snapshot_id)
            await storage.save_snapshot(snapshot)

        # List all
        snapshots = await storage.list_snapshots(saga_id)
        assert len(snapshots) == 5

        # List with limit
        limited = await storage.list_snapshots(saga_id, limit=2)
        assert len(limited) == 2

    @pytest.mark.asyncio
    async def test_delete_snapshot(self, storage):
        """Test deleting a snapshot"""
        saga_id = uuid4()
        snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="test_saga",
            step_name="step1",
            step_index=1,
            status=SagaStatus.EXECUTING,
            context={},
            completed_steps=[],
            created_at=datetime.now(UTC),
        )

        # Save
        await storage.save_snapshot(snapshot)

        # Delete
        deleted = await storage.delete_snapshot(snapshot.snapshot_id)
        assert deleted is True

        # Verify deleted
        retrieved = await storage.get_snapshot(snapshot.snapshot_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_compression(self, temp_dir):
        """Test with compression enabled"""
        storage = FilesystemSnapshotStorage(
            base_path=temp_dir, enable_compression=True
        )

        saga_id = uuid4()
        snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="test_saga",
            step_name="step1",
            step_index=1,
            status=SagaStatus.EXECUTING,
            context={"large_data": "x" * 10000},  # Large context
            completed_steps=[],
            created_at=datetime.now(UTC),
        )

        await storage.save_snapshot(snapshot)

        # Verify file is compressed (.gz extension)
        saga_dir = Path(temp_dir) / "snapshots" / str(saga_id)
        snapshot_file = saga_dir / f"{snapshot.snapshot_id}.json.gz"
        assert snapshot_file.exists()

        # Retrieve should work
        retrieved = await storage.get_snapshot(snapshot.snapshot_id)
        assert retrieved is not None
        assert retrieved.context["large_data"] == "x" * 10000

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time(self, storage):
        """Test time-travel query"""
        saga_id = uuid4()
        now = datetime.now(UTC)

        # Create snapshots at different times
        snapshot1 = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="test_saga",
            step_name="step1",
            step_index=1,
            status=SagaStatus.EXECUTING,
            context={"time": "past"},
            completed_steps=[],
            created_at=now - timedelta(hours=2),
        )
        await storage.save_snapshot(snapshot1)

        snapshot2 = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="test_saga",
            step_name="step2",
            step_index=2,
            status=SagaStatus.EXECUTING,
            context={"time": "recent"},
            completed_steps=[],
            created_at=now - timedelta(hours=1),
        )
        await storage.save_snapshot(snapshot2)

        # Query at time before snapshot2
        result = await storage.get_snapshot_at_time(
            saga_id, now - timedelta(hours=1, minutes=30)
        )
        assert result is not None
        assert result.context["time"] == "past"

        # Query at time after both snapshots
        result = await storage.get_snapshot_at_time(saga_id, now)
        assert result is not None
        assert result.context["time"] == "recent"

    @pytest.mark.asyncio
    async def test_save_and_get_replay_log(self, storage):
        """Test replay log storage"""
        replay_result = ReplayResult(
            replay_id=uuid4(),
            original_saga_id=uuid4(),
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.SUCCESS,
            initiated_by="test_user",
        )

        # Save
        await storage.save_replay_log(replay_result)

        # Retrieve
        retrieved = await storage.get_replay_log(replay_result.replay_id)
        assert retrieved is not None
        assert retrieved["checkpoint_step"] == "step1"
        assert retrieved["replay_status"] == "success"

    @pytest.mark.asyncio
    async def test_list_replays(self, storage):
        """Test listing replays for a saga"""
        original_saga_id = uuid4()

        # Create multiple replays
        for i in range(3):
            replay = ReplayResult(
                replay_id=uuid4(),
                original_saga_id=original_saga_id,
                new_saga_id=uuid4(),
                checkpoint_step=f"step{i}",
                replay_status=ReplayStatus.SUCCESS,
            )
            await storage.save_replay_log(replay)

        # List replays
        replays = await storage.list_replays(original_saga_id)
        assert len(replays) == 3

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots(self, storage):
        """Test cleanup of expired snapshots"""
        saga_id = uuid4()
        now = datetime.now(UTC)

        # Create expired snapshot
        expired_snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="test_saga",
            step_name="step1",
            step_index=1,
            status=SagaStatus.EXECUTING,
            context={},
            completed_steps=[],
            created_at=now - timedelta(days=40),
            retention_until=now - timedelta(days=10),  # Expired
        )
        await storage.save_snapshot(expired_snapshot)

        # Create non-expired snapshot
        active_snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="test_saga",
            step_name="step2",
            step_index=2,
            status=SagaStatus.EXECUTING,
            context={},
            completed_steps=[],
            created_at=now,
            retention_until=now + timedelta(days=30),  # Not expired
        )
        await storage.save_snapshot(active_snapshot)

        # Delete expired
        deleted_count = await storage.delete_expired_snapshots()
        assert deleted_count == 1

        # Verify only active remains
        snapshots = await storage.list_snapshots(saga_id)
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_id == active_snapshot.snapshot_id

    @pytest.mark.asyncio
    async def test_get_storage_info(self, storage):
        """Test storage statistics"""
        saga_id = uuid4()

        # Create some snapshots
        for i in range(3):
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="test_saga",
                step_name=f"step{i}",
                step_index=i,
                status=SagaStatus.EXECUTING,
                context={},
                completed_steps=[],
                created_at=datetime.now(UTC),
            )
            await storage.save_snapshot(snapshot)

        # Get info
        info = storage.get_storage_info()
        assert info["storage_type"] == "filesystem"
        assert info["total_sagas"] == 1
        assert info["total_snapshots"] == 3
        assert info["total_size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_cleanup_saga(self, storage):
        """Test cleaning up all snapshots for a saga"""
        saga_id = uuid4()

        # Create snapshots
        for i in range(3):
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="test_saga",
                step_name=f"step{i}",
                step_index=i,
                status=SagaStatus.EXECUTING,
                context={},
                completed_steps=[],
                created_at=datetime.now(UTC),
            )
            await storage.save_snapshot(snapshot)

        # Cleanup
        deleted = await storage.cleanup_saga(saga_id)
        assert deleted == 3

        # Verify all deleted
        snapshots = await storage.list_snapshots(saga_id)
        assert len(snapshots) == 0

    @pytest.mark.asyncio
    async def test_context_manager(self, temp_dir):
        """Test async context manager"""
        async with FilesystemSnapshotStorage(base_path=temp_dir) as storage:
            assert storage is not None

            saga_id = uuid4()
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="test_saga",
                step_name="step1",
                step_index=1,
                status=SagaStatus.EXECUTING,
                context={},
                completed_steps=[],
                created_at=datetime.now(UTC),
            )
            await storage.save_snapshot(snapshot)
