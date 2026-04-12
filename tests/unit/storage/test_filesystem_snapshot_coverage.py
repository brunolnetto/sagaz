"""
Tests for missing paths in sagaz/storage/backends/filesystem_snapshot.py.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest


def make_snapshot(
    saga_id=None,
    step_name="step_one",
    context=None,
    snapshot_id=None,
):
    """Helper to create SagaSnapshot."""
    from sagaz.core.replay import SagaSnapshot

    return SagaSnapshot(
        snapshot_id=snapshot_id or uuid4(),
        saga_id=saga_id or uuid4(),
        saga_name="TestSaga",
        step_name=step_name,
        step_index=0,
        status="executing",
        context=context or {"key": "value"},
        completed_steps=[],
        created_at=datetime.now(UTC),
        retention_until=None,
    )


@pytest.fixture
def storage(tmp_path):
    from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

    return FilesystemSnapshotStorage(
        base_path=str(tmp_path / "snapshots"),
        enable_compression=False,
    )


@pytest.fixture
def compressed_storage(tmp_path):
    from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

    return FilesystemSnapshotStorage(
        base_path=str(tmp_path / "snapshots_gz"),
        enable_compression=True,  # Lines 133: compressed write path
    )


# =============================================================================
# Line 133: Compressed write path
# =============================================================================


class TestFilesystemCompression:
    """Line 133: _write_json with enable_compression=True uses gzip."""

    @pytest.mark.asyncio
    async def test_save_and_get_snapshot_compressed(self, compressed_storage):
        """Line 133: Compressed snapshot save/restore."""
        snapshot = make_snapshot()
        await compressed_storage.save_snapshot(snapshot)

        # Should retrieve successfully
        result = await compressed_storage.get_snapshot(snapshot.snapshot_id)
        assert result is not None
        assert result.saga_id == snapshot.saga_id

    @pytest.mark.asyncio
    async def test_read_json_detects_gz_extension(self, compressed_storage):
        """Line 133: Reading .json.gz file decompresses it."""
        snapshot = make_snapshot()
        await compressed_storage.save_snapshot(snapshot)

        path = compressed_storage._get_snapshot_path(snapshot.saga_id, snapshot.snapshot_id)
        assert path.suffix == ".gz"

        data = await compressed_storage._read_json(path)
        assert "saga_id" in data


# =============================================================================
# Line 202: get_snapshot() returns None when not found
# =============================================================================


class TestGetSnapshotNotFound:
    """Line 202: get_snapshot returns None if no file found."""

    @pytest.mark.asyncio
    async def test_get_snapshot_returns_none_for_missing(self, storage):
        """Line 202: Searching all saga dirs → returns None."""
        result = await storage.get_snapshot(uuid4())
        assert result is None


# =============================================================================
# Lines 211-212: get_snapshot() skips corrupted files
# =============================================================================


class TestGetSnapshotSkipsCorrupted:
    """Lines 211-212: get_snapshot swallows exceptions for unreadable files."""

    @pytest.mark.asyncio
    async def test_corrupted_snapshot_file_skipped(self, storage, tmp_path):
        """Lines 211-212: Exception reading snapshot → skips, returns None."""
        saga_id = uuid4()
        snap_id = uuid4()

        # Create a corrupted file
        saga_dir = storage.snapshots_dir / str(saga_id)
        saga_dir.mkdir(exist_ok=True)
        bad_file = saga_dir / f"{snap_id}.json"
        bad_file.write_text("not valid json {{{")

        result = await storage.get_snapshot(snap_id)
        assert result is None  # Corrupted file should be skipped


# =============================================================================
# Line 222: get_latest_snapshot() when index doesn't exist
# =============================================================================


class TestGetLatestSnapshotNoIndex:
    """Line 222: get_latest_snapshot when no index file → returns None."""

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_no_index(self, storage):
        """Line 222: No index file → None."""
        result = await storage.get_latest_snapshot(uuid4())
        assert result is None


# =============================================================================
# Line 232: get_latest_snapshot() iterates index entries
# =============================================================================


class TestGetLatestSnapshot:
    """Line 232: get_latest_snapshot with before_step filter."""

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_with_before_step(self, storage):
        """Line 232: before_step filter skips non-matching steps."""
        saga_id = uuid4()

        snap1 = make_snapshot(saga_id=saga_id, step_name="step_one")
        snap2 = make_snapshot(saga_id=saga_id, step_name="step_two")

        await storage.save_snapshot(snap1)
        await storage.save_snapshot(snap2)

        # Filter by step_one
        result = await storage.get_latest_snapshot(saga_id, before_step="step_one")
        assert result is not None
        assert result.step_name == "step_one"

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_none_matching_before_step(self, storage):
        """Line 232: No snapshot matches before_step → None."""
        saga_id = uuid4()
        snapshot = make_snapshot(saga_id=saga_id, step_name="step_one")
        await storage.save_snapshot(snapshot)

        result = await storage.get_latest_snapshot(saga_id, before_step="nonexistent_step")
        assert result is None


# =============================================================================
# Line 238: get_snapshot_at_time() when no index
# =============================================================================


class TestGetSnapshotAtTime:
    """Lines 238, 246: get_snapshot_at_time."""

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time_no_index(self, storage):
        """Line 238: No index → None."""
        result = await storage.get_snapshot_at_time(uuid4(), datetime.now(UTC))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time_finds_closest(self, storage):
        """Line 246: Returns snapshot created before the given timestamp."""
        saga_id = uuid4()
        snapshot = make_snapshot(saga_id=saga_id)
        await storage.save_snapshot(snapshot)

        # Query future time → should find it
        future_time = datetime(2099, 1, 1, tzinfo=UTC)
        result = await storage.get_snapshot_at_time(saga_id, future_time)
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time_past_time_returns_none(self, storage):
        """Line 246: Snapshot created after query time → None."""
        saga_id = uuid4()
        snapshot = make_snapshot(saga_id=saga_id)
        await storage.save_snapshot(snapshot)

        # Query very old time → nothing before it
        past_time = datetime(2000, 1, 1, tzinfo=UTC)
        result = await storage.get_snapshot_at_time(saga_id, past_time)
        assert result is None


# =============================================================================
# Line 284: list_snapshots() when no index
# =============================================================================


class TestListSnapshots:
    """Line 284: list_snapshots with no index → empty list."""

    @pytest.mark.asyncio
    async def test_list_snapshots_no_index_returns_empty(self, storage):
        """Line 284: No index → []."""
        result = await storage.list_snapshots(uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_list_snapshots_with_results(self, storage):
        """Line 284+: Multiple snapshots listed in desc order."""
        saga_id = uuid4()
        for _ in range(3):
            await storage.save_snapshot(make_snapshot(saga_id=saga_id))

        result = await storage.list_snapshots(saga_id)
        assert len(result) == 3


# =============================================================================
# Lines 301, 308: delete_snapshot()
# =============================================================================


class TestDeleteSnapshot:
    """Lines 301, 308: delete_snapshot() for .json and .json.gz files."""

    @pytest.mark.asyncio
    async def test_delete_snapshot_plain_json(self, storage):
        """Line 301: delete_snapshot removes plain JSON file."""
        snapshot = make_snapshot()
        await storage.save_snapshot(snapshot)

        result = await storage.delete_snapshot(snapshot.snapshot_id)
        assert result is True

        # Should no longer be retrievable
        assert await storage.get_snapshot(snapshot.snapshot_id) is None

    @pytest.mark.asyncio
    async def test_delete_snapshot_compressed(self, compressed_storage):
        """Line 308: delete_snapshot removes .json.gz file."""
        snapshot = make_snapshot()
        await compressed_storage.save_snapshot(snapshot)

        result = await compressed_storage.delete_snapshot(snapshot.snapshot_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_snapshot_not_found_returns_false(self, storage):
        """delete_snapshot returns False when snapshot doesn't exist."""
        result = await storage.delete_snapshot(uuid4())
        assert result is False


# =============================================================================
# Lines 330, 334: delete_expired_snapshots()
# =============================================================================


class TestDeleteExpiredSnapshots:
    """Lines 330, 334: delete_expired_snapshots handles expired + non-expired."""

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots_no_expired(self, storage):
        """Line 330: No expired snapshots → 0 deleted."""
        saga_id = uuid4()
        snapshot = make_snapshot(saga_id=saga_id)
        await storage.save_snapshot(snapshot)

        count = await storage.delete_expired_snapshots()
        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots_with_expired(self, storage):
        """Line 334: Expired snapshot deleted."""
        from sagaz.core.replay import SagaSnapshot

        saga_id = uuid4()
        # Create snapshot with past retention_until (expired)
        expired_snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="Test",
            step_name="step1",
            step_index=0,
            status="executing",
            context={"key": "val"},
            completed_steps=[],
            created_at=datetime.now(UTC),
            retention_until=datetime(2020, 1, 1, tzinfo=UTC),  # In the past
        )
        await storage.save_snapshot(expired_snapshot)

        count = await storage.delete_expired_snapshots()
        assert count == 1


# =============================================================================
# Lines 347, 349: save_replay_log / get_replay_log
# =============================================================================


class TestReplayLog:
    """Lines 347, 349, 362, 375: replay log operations."""

    @pytest.mark.asyncio
    async def test_save_and_get_replay_log(self, storage):
        """Lines 347, 349: save and retrieve replay log."""
        from sagaz.core.replay import ReplayResult, ReplayStatus

        result = ReplayResult(
            replay_id=uuid4(),
            original_saga_id=uuid4(),
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.SUCCESS,
        )
        await storage.save_replay_log(result)  # covers line 347

        log = await storage.get_replay_log(result.replay_id)  # covers line 349
        assert log is not None
        assert log["replay_id"] == str(result.replay_id)

    @pytest.mark.asyncio
    async def test_get_replay_log_not_found(self, storage):
        """Line 362: get_replay_log returns None when file doesn't exist."""
        result = await storage.get_replay_log(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_replays(self, storage):
        """Line 375: list_replays returns matching replays."""
        from sagaz.core.replay import ReplayResult, ReplayStatus

        saga_id = uuid4()

        # Save two replays for the same original saga
        for _ in range(2):
            result = ReplayResult(
                replay_id=uuid4(),
                original_saga_id=saga_id,
                new_saga_id=uuid4(),
                checkpoint_step="step1",
                replay_status=ReplayStatus.SUCCESS,
            )
            await storage.save_replay_log(result)

        replays = await storage.list_replays(saga_id)
        assert len(replays) == 2


# =============================================================================
# Lines 381-382: list_replays skips corrupted replay files
# =============================================================================


class TestListReplayCorrupted:
    """Lines 381-382: list_replays skips corrupted files."""

    @pytest.mark.asyncio
    async def test_list_replays_skips_corrupted(self, storage, tmp_path):
        """Lines 381-382: Exception reading file → continue."""
        # Write a corrupted replay file
        bad_file = storage.replays_dir / "bad-file.json"
        bad_file.write_text("{not valid json}")

        original_saga_id = uuid4()
        # Should not raise
        replays = await storage.list_replays(original_saga_id)
        assert isinstance(replays, list)  # May be empty, but shouldn't raise


# =============================================================================
# Line 410: get_storage_info()
# =============================================================================


class TestGetStorageInfo:
    """Line 410: get_storage_info returns statistics."""

    @pytest.mark.asyncio
    async def test_get_storage_info_empty(self, storage):
        """Line 410: No snapshots → zeros."""
        info = storage.get_storage_info()
        assert info["total_snapshots"] == 0
        assert info["total_sagas"] == 0
        assert info["storage_type"] == "filesystem"

    @pytest.mark.asyncio
    async def test_get_storage_info_with_data(self, storage):
        """Line 410: With snapshots, counts are non-zero."""
        saga_id = uuid4()
        await storage.save_snapshot(make_snapshot(saga_id=saga_id))

        info = storage.get_storage_info()
        assert info["total_sagas"] >= 1
        assert info["total_snapshots"] >= 1


# =============================================================================
# Line 443: cleanup_saga()
# =============================================================================


class TestCleanupSaga:
    """Line 443: cleanup_saga deletes all saga snapshots."""

    @pytest.mark.asyncio
    async def test_cleanup_saga_removes_all_snapshots(self, storage):
        """Line 443: cleanup_saga deletes saga dir and index."""
        saga_id = uuid4()

        # Save 3 snapshots
        for _ in range(3):
            await storage.save_snapshot(make_snapshot(saga_id=saga_id))

        count = await storage.cleanup_saga(saga_id)
        assert count == 3

        # No more snapshots
        assert await storage.list_snapshots(saga_id) == []

    @pytest.mark.asyncio
    async def test_cleanup_saga_returns_zero_for_nonexistent(self, storage):
        """Line 443 precheck: Non-existent saga returns 0."""
        count = await storage.cleanup_saga(uuid4())
        assert count == 0
