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
from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage
from sagaz.core.types import SagaStatus


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
        FilesystemSnapshotStorage(base_path=temp_dir)

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
        storage = FilesystemSnapshotStorage(base_path=temp_dir, enable_compression=True)

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
        result = await storage.get_snapshot_at_time(saga_id, now - timedelta(hours=1, minutes=30))
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


class TestFilesystemSnapshotMissingBranches:
    """Cover lines 133, 202, 232, 274->271, 284, 286->282, 308, 330, 334,
    345->332, 347-349, 375, 379->373, 410, 414->413, 452->455."""

    @pytest.fixture
    def temp_dir(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d, ignore_errors=True)

    @pytest.fixture
    def storage(self, temp_dir):
        return FilesystemSnapshotStorage(base_path=temp_dir)

    def _make_snapshot(self, saga_id=None):
        from uuid import uuid4

        return SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id or uuid4(),
            saga_name="MySaga",
            step_name="step1",
            step_index=1,
            status=SagaStatus.EXECUTING,
            context={},
            completed_steps=[],
            created_at=datetime.now(UTC),
        )

    @pytest.mark.asyncio
    async def test_read_json_file_not_found(self, storage):
        """Line 133: _read_json raises FileNotFoundError for missing file."""
        from pathlib import Path

        with pytest.raises(FileNotFoundError):
            await storage._read_json(Path("/nonexistent/path/file.json"))

    @pytest.mark.asyncio
    async def test_find_latest_snapshot_skips_non_directories(self, storage):
        """Line 202: non-directory files in snapshots_dir are skipped."""
        saga_id = uuid4()
        # Place a plain file inside snapshots_dir
        (storage.snapshots_dir / "not_a_dir.txt").write_text("x")
        # Should return None (no valid snapshots)
        result = await storage.get_latest_snapshot(saga_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_returns_none_for_missing_file(self, storage):
        """Lines 232, 274->271: snapshot listed in index but file deleted → None."""
        saga_id = uuid4()
        snapshot = self._make_snapshot(saga_id)
        await storage.save_snapshot(snapshot)
        # Now delete the actual snapshot file but leave the index
        saga_dir = storage.snapshots_dir / str(saga_id)
        for f in saga_dir.iterdir():
            if not f.name.endswith("index.json"):
                f.unlink()
        result = await storage.get_latest_snapshot(saga_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_snapshot_skips_non_directories(self, storage):
        """Line 284: non-directory files in snapshots_dir are skipped when deleting."""
        (storage.snapshots_dir / "not_a_dir.txt").write_text("x")
        result = await storage.delete_snapshot(uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_from_index_no_index_file(self, storage):
        """Line 308: _remove_from_index returns early when no index file exists."""
        saga_id = uuid4()
        snapshot_id = uuid4()
        # Should not raise even if there's no index
        await storage._remove_from_index(saga_id, snapshot_id)

    @pytest.mark.asyncio
    async def test_delete_expired_skips_non_directories(self, storage):
        """Line 330: non-directory file in snapshots_dir skipped in expiry scan."""
        (storage.snapshots_dir / "file.txt").write_text("x")
        count = await storage.delete_expired_snapshots()
        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_expired_skips_non_file_items(self, storage):
        """Line 334: non-file items in saga_dir are skipped."""
        saga_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir(parents=True)
        subdir = saga_dir / "subdir"
        subdir.mkdir()
        count = await storage.delete_expired_snapshots()
        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_expired_skips_non_expired(self, storage):
        """Lines 345->332: snapshot with future retention_until is NOT deleted."""
        saga_id = uuid4()
        snapshot = self._make_snapshot(saga_id)
        snapshot = SagaSnapshot(
            snapshot_id=snapshot.snapshot_id,
            saga_id=snapshot.saga_id,
            saga_name=snapshot.saga_name,
            step_name=snapshot.step_name,
            step_index=snapshot.step_index,
            status=snapshot.status,
            context=snapshot.context,
            completed_steps=snapshot.completed_steps,
            created_at=snapshot.created_at,
            retention_until=datetime.now(UTC) + timedelta(days=1),
        )
        await storage.save_snapshot(snapshot)
        count = await storage.delete_expired_snapshots()
        assert count == 0  # Nothing deleted

    @pytest.mark.asyncio
    async def test_delete_expired_skips_corrupted_files(self, storage):
        """Lines 347-349: corrupted snapshot file skipped with except Exception."""
        saga_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir(parents=True)
        # Write a non-JSON file
        bad_file = saga_dir / "bad.json"
        bad_file.write_text("NOT JSON {{{")
        count = await storage.delete_expired_snapshots()
        assert count == 0

    @pytest.mark.asyncio
    async def test_list_replays_skips_non_files(self, storage):
        """Line 375: non-file items in replays_dir are skipped."""
        subdir = storage.replays_dir / "subdir"
        subdir.mkdir()
        result = await storage.list_replays(uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_list_replays_skips_non_matching_saga_id(self, storage):
        """Lines 379->373: replay with different saga_id is skipped."""
        saga1_id = uuid4()
        saga2_id = uuid4()
        replay = ReplayResult(
            replay_id=uuid4(),
            original_saga_id=saga1_id,
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.SUCCESS,
        )
        await storage.save_replay_log(replay)
        # Request replays for a different saga_id
        result = await storage.list_replays(saga2_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_storage_info_skips_non_directories(self, storage):
        """Line 410: non-directory in snapshots_dir is skipped in get_storage_info."""
        (storage.snapshots_dir / "not_a_dir.txt").write_text("x")
        info = storage.get_storage_info()
        assert info["total_sagas"] == 0

    @pytest.mark.asyncio
    async def test_get_storage_info_counts_only_files(self, storage):
        """Lines 414->413: non-file in saga_dir is skipped in get_storage_info."""
        saga_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir(parents=True)
        subdir = saga_dir / "subdir"
        subdir.mkdir()
        info = storage.get_storage_info()
        assert info["total_snapshots"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_saga_no_index_file(self, storage):
        """Lines 452->455: cleanup_saga runs when index file doesn't exist."""
        saga_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir(parents=True)
        # indexes_dir does NOT have an index for this saga_id
        result = await storage.cleanup_saga(saga_id)
        assert result >= 0  # Runs without error, index unlink skipped


class TestFilesystemSnapshotBranches:
    async def test_get_snapshot_skips_non_directory(self, tmp_path):
        """202: continue when iterdir entry is not a directory."""
        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        # base_path/snapshots/ is created by __init__; put a FILE in it
        (storage.snapshots_dir / "not_a_dir.txt").write_text("hello")

        # Should iterate and skip files
        result = await storage.get_snapshot(uuid4())
        assert result is None

    async def test_list_snapshots_skips_missing_snapshot(self, tmp_path):
        """274->271: snapshot returned None → skip."""
        import json

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        snap_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        # Write index pointing to a snapshot that doesn't exist on disk
        index = {"snapshots": [{"snapshot_id": str(snap_id), "step_name": "step1"}]}
        (storage.indexes_dir / f"{saga_id}.json").write_text(json.dumps(index))

        result = await storage.list_snapshots(saga_id=saga_id, limit=10)
        assert result == []

    async def test_delete_snapshot_extension_not_found(self, tmp_path):
        """286->282: first extension not found, try next extension."""
        import json

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        snap_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        # Write snapshot as .json (not .json.gz)
        snapshot_data = {
            "snapshot_id": str(snap_id),
            "saga_id": str(saga_id),
            "step_name": "step1",
            "status": "completed",
        }
        (saga_dir / f"{snap_id}.json").write_text(json.dumps(snapshot_data))

        # Should try .json.gz first (not found), then .json (found)
        result = await storage.delete_snapshot(snap_id)
        assert result is True

    async def test_delete_expired_snapshots(self, tmp_path):
        """345->332: delete_expired_snapshots actually deletes one."""
        import json

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        snap_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        # Write expired snapshot
        snapshot_data = {
            "snapshot_id": str(snap_id),
            "saga_id": str(saga_id),
            "step_name": "step1",
            "status": "completed",
            "retention_until": "2000-01-01T00:00:00+00:00",  # Past date
        }
        (saga_dir / f"{snap_id}.json").write_text(json.dumps(snapshot_data))

        count = await storage.delete_expired_snapshots()
        assert count >= 1

    async def test_get_snapshot_from_dict_exception(self, tmp_path):
        """211-212: SagaSnapshot.from_dict raises Exception → continue."""
        import json
        from unittest.mock import patch

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        snap_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        snapshot_data = {
            "snapshot_id": str(snap_id),
            "saga_id": str(saga_id),
            "step_name": "step1",
            "status": "completed",
        }
        (saga_dir / f"{snap_id}.json").write_text(json.dumps(snapshot_data))

        # Patch from_dict to raise → 211-212: except Exception → continue
        with patch(
            "sagaz.core.storage.backends.filesystem_snapshot.SagaSnapshot.from_dict",
            side_effect=ValueError("bad data"),
        ):
            result = await storage.get_snapshot(snap_id)
        assert result is None

    async def test_get_latest_snapshot_skips_none_then_finds(self, tmp_path):
        """235->227: snapshot is None → continue → finds next."""
        import json

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        missing_id = uuid4()
        real_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        # Index: first entry points to missing_id (get_snapshot returns None)
        # second entry points to real_id (exists)
        real_data = {
            "snapshot_id": str(real_id),
            "saga_id": str(saga_id),
            "saga_name": "TestSaga",
            "step_name": "step1",
            "step_index": 0,
            "status": "completed",
            "context": {},
            "completed_steps": [],
            "created_at": "2024-01-15T10:00:00+00:00",
        }
        (saga_dir / f"{real_id}.json").write_text(json.dumps(real_data))

        index = {
            "snapshots": [
                {"snapshot_id": str(missing_id)},  # doesn't exist on disk → None
                {"snapshot_id": str(real_id)},
            ]
        }
        (storage.indexes_dir / f"{saga_id}.json").write_text(json.dumps(index))

        result = await storage.get_latest_snapshot(saga_id=saga_id)
        assert result is not None
        assert str(result.snapshot_id) == str(real_id)

    async def test_get_latest_snapshot_before_step_match(self, tmp_path):
        """246: return snapshot when step_name matches before_step."""
        import json

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        snap_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        snap_data = {
            "snapshot_id": str(snap_id),
            "saga_id": str(saga_id),
            "saga_name": "TestSaga",
            "step_name": "target_step",
            "step_index": 0,
            "status": "completed",
            "context": {},
            "completed_steps": [],
            "created_at": "2024-01-15T10:00:00+00:00",
        }
        (saga_dir / f"{snap_id}.json").write_text(json.dumps(snap_data))
        index = {"snapshots": [{"snapshot_id": str(snap_id)}]}
        (storage.indexes_dir / f"{saga_id}.json").write_text(json.dumps(index))

        result = await storage.get_latest_snapshot(saga_id=saga_id, before_step="target_step")
        assert result is not None

    async def test_get_snapshot_at_time_match(self, tmp_path):
        """252->259: entry_time <= timestamp → target_snapshot set → break → return."""
        import json
        from datetime import timezone

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        snap_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        snap_data = {
            "snapshot_id": str(snap_id),
            "saga_id": str(saga_id),
            "saga_name": "TestSaga",
            "step_name": "step1",
            "step_index": 0,
            "status": "completed",
            "context": {},
            "completed_steps": [],
            "created_at": "2024-01-15T10:00:00+00:00",
        }
        (saga_dir / f"{snap_id}.json").write_text(json.dumps(snap_data))

        from datetime import datetime

        index = {
            "snapshots": [{"snapshot_id": str(snap_id), "created_at": "2024-01-15T10:00:00+00:00"}]
        }
        (storage.indexes_dir / f"{saga_id}.json").write_text(json.dumps(index))

        result = await storage.get_snapshot_at_time(
            saga_id=saga_id,
            timestamp=datetime(2024, 6, 1, tzinfo=UTC),
        )
        assert result is not None

    async def test_delete_expired_no_retention(self, tmp_path):
        """340->332: no retention_until in snapshot → skip (for loop continues)."""
        import json

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        snap_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        # No retention_until → 340: if retention_until: FALSE → continues for loop
        snap_data = {
            "snapshot_id": str(snap_id),
            "saga_id": str(saga_id),
            "step_name": "step1",
            "status": "completed",
        }
        (saga_dir / f"{snap_id}.json").write_text(json.dumps(snap_data))

        count = await storage.delete_expired_snapshots()
        assert count == 0

    async def test_delete_expired_snapshots_delete_returns_false(self, tmp_path):
        """345->332: delete_snapshot returns False → loop continues."""
        import json
        from unittest.mock import AsyncMock, patch

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        snap_id = uuid4()
        snap_id2 = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        for sid in [snap_id, snap_id2]:
            snap_data = {
                "snapshot_id": str(sid),
                "saga_id": str(saga_id),
                "step_name": "step1",
                "status": "completed",
                "retention_until": "2000-01-01T00:00:00+00:00",  # Expired
            }
            (saga_dir / f"{sid}.json").write_text(json.dumps(snap_data))

        # Patch delete_snapshot to return False (345->332 FALSE branch)
        with patch.object(storage, "delete_snapshot", return_value=False):
            count = await storage.delete_expired_snapshots()
        assert count == 0  # No increments since delete_snapshot returned False

    async def test_list_replays_exception_skips(self, tmp_path):
        """381-382: exception reading replay file → continue."""
        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        # Write a corrupted (non-JSON) replay file
        bad_replay = storage.replays_dir / "bad_replay.json"
        bad_replay.write_text("NOT JSON {{{{")

        result = await storage.list_replays(original_saga_id=uuid4())
        assert result == []

    async def test_get_replay_log_exists(self, tmp_path):
        """362: get_replay_log returns data when file exists."""
        import json

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        replay_id = uuid4()
        replay_data = {"replay_id": str(replay_id), "original_saga_id": str(uuid4())}
        replay_path = storage._get_replay_path(replay_id)
        replay_path.write_text(json.dumps(replay_data))

        result = await storage.get_replay_log(replay_id)
        assert result is not None

    async def test_delete_snapshot_both_suffixes_missing(self, tmp_path):
        """286->282: inner for-suffix loop exhausted (no match) → outer saga_dir loop continues."""
        import json

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        snap_id = uuid4()

        # Create a saga_dir with an unrelated file (not the target snap_id)
        other_snap_id = uuid4()
        saga_dir = storage.snapshots_dir / str(uuid4())
        saga_dir.mkdir()
        (saga_dir / f"{other_snap_id}.json").write_text(json.dumps({"other": "data"}))

        # snap_id is not in any saga_dir → both suffixes tried (286->282 taken) → returns False
        result = await storage.delete_snapshot(snap_id)
        assert result is False

    async def test_list_snapshots_skips_none_snapshot(self, tmp_path):
        """274->271: list_snapshots has entry but get_snapshot returns None → skip."""
        import json

        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=str(tmp_path))
        saga_id = uuid4()
        snap_id = uuid4()
        real_snap_id = uuid4()
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir()

        # real snapshot
        real_data = {
            "snapshot_id": str(real_snap_id),
            "saga_id": str(saga_id),
            "saga_name": "TestSaga",
            "step_name": "step1",
            "step_index": 0,
            "status": "completed",
            "context": {},
            "completed_steps": [],
            "created_at": "2024-01-15T10:00:00+00:00",
        }
        (saga_dir / f"{real_snap_id}.json").write_text(json.dumps(real_data))

        # Index: first entry points to missing, second to real
        index = {
            "snapshots": [
                {"snapshot_id": str(snap_id)},  # no file → None (274->FALSE)
                {"snapshot_id": str(real_snap_id)},
            ]
        }
        (storage.indexes_dir / f"{saga_id}.json").write_text(json.dumps(index))

        result = await storage.list_snapshots(saga_id=saga_id, limit=10)
        assert len(result) == 1
