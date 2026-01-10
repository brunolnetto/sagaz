"""
Unit tests for snapshot storage backend implementations.

Focuses on improving coverage for:
- InMemorySnapshotStorage
- RedisSnapshotStorage (mocked)
- PostgreSQLSnapshotStorage (mocked)
- S3SnapshotStorage (mocked)
"""

import json
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from sagaz.core.replay import SagaSnapshot
from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage


def create_test_snapshot(
    saga_id: str | None = None, step_name: str = "test_step", retention_days: int | None = 30
) -> SagaSnapshot:
    """Create test snapshot."""
    created_at = datetime.now(UTC)
    return SagaSnapshot(
        snapshot_id=str(uuid4()),
        saga_id=saga_id or str(uuid4()),
        saga_name="TestSaga",
        step_name=step_name,
        step_index=0,
        status="executing",
        context={"test": "data"},
        completed_steps=[],
        created_at=created_at,
        retention_until=(created_at + timedelta(days=retention_days) if retention_days else None),
    )


# ============================================================================
# InMemorySnapshotStorage Tests
# ============================================================================


@pytest.mark.asyncio
class TestInMemorySnapshotStorage:
    """Comprehensive tests for in-memory snapshot storage."""

    async def test_save_and_get(self):
        """Test basic save and get operations."""
        storage = InMemorySnapshotStorage()
        snapshot = create_test_snapshot()

        await storage.save_snapshot(snapshot)
        retrieved = await storage.get_snapshot(snapshot.snapshot_id)

        assert retrieved is not None
        assert retrieved.snapshot_id == snapshot.snapshot_id
        assert retrieved.saga_id == snapshot.saga_id

    async def test_get_nonexistent(self):
        """Test getting nonexistent snapshot."""
        storage = InMemorySnapshotStorage()
        result = await storage.get_snapshot("nonexistent")
        assert result is None

    async def test_get_latest(self):
        """Test getting latest snapshot."""
        storage = InMemorySnapshotStorage()
        saga_id = str(uuid4())

        snap1 = create_test_snapshot(saga_id=saga_id, step_name="step1")
        await storage.save_snapshot(snap1)

        # Ensure different timestamp
        import asyncio

        await asyncio.sleep(0.01)

        snap2 = create_test_snapshot(saga_id=saga_id, step_name="step2")
        await storage.save_snapshot(snap2)

        latest = await storage.get_latest_snapshot(saga_id)
        assert latest is not None
        assert latest.step_name == "step2"

    async def test_get_latest_no_snapshots(self):
        """Test getting latest when no snapshots exist."""
        storage = InMemorySnapshotStorage()
        result = await storage.get_latest_snapshot(str(uuid4()))
        assert result is None

    async def test_list_snapshots(self):
        """Test listing snapshots."""
        storage = InMemorySnapshotStorage()
        saga_id = str(uuid4())

        for i in range(3):
            snap = create_test_snapshot(saga_id=saga_id, step_name=f"step{i}")
            await storage.save_snapshot(snap)

        snapshots = await storage.list_snapshots(saga_id)
        assert len(snapshots) == 3

    async def test_list_empty(self):
        """Test listing snapshots for saga with none."""
        storage = InMemorySnapshotStorage()
        snapshots = await storage.list_snapshots(str(uuid4()))
        assert len(snapshots) == 0

    async def test_delete_snapshot(self):
        """Test deleting a snapshot."""
        storage = InMemorySnapshotStorage()
        snapshot = create_test_snapshot()

        await storage.save_snapshot(snapshot)
        deleted = await storage.delete_snapshot(snapshot.snapshot_id)

        assert deleted is True
        assert await storage.get_snapshot(snapshot.snapshot_id) is None

    async def test_delete_nonexistent(self):
        """Test deleting nonexistent snapshot."""
        storage = InMemorySnapshotStorage()
        deleted = await storage.delete_snapshot("nonexistent")
        assert deleted is False

    async def test_delete_expired(self):
        """Test deleting expired snapshots."""
        storage = InMemorySnapshotStorage()

        # Expired snapshot
        expired = create_test_snapshot(retention_days=-1)
        await storage.save_snapshot(expired)

        # Valid snapshot
        valid = create_test_snapshot(retention_days=30)
        await storage.save_snapshot(valid)

        count = await storage.delete_expired_snapshots()
        assert count == 1

        assert await storage.get_snapshot(expired.snapshot_id) is None
        assert await storage.get_snapshot(valid.snapshot_id) is not None

    async def test_pagination(self):
        """Test pagination with limit."""
        storage = InMemorySnapshotStorage()
        saga_id = str(uuid4())

        for i in range(10):
            snap = create_test_snapshot(saga_id=saga_id, step_name=f"step{i}")
            await storage.save_snapshot(snap)

        # Test limit parameter
        limited = await storage.list_snapshots(saga_id, limit=3)
        assert len(limited) == 3

        # Test no limit gets all
        all_snaps = await storage.list_snapshots(saga_id)
        assert len(all_snaps) == 10

    async def test_large_context(self):
        """Test storing large context."""
        storage = InMemorySnapshotStorage()
        large_context = {f"key_{i}": f"value_{i}" * 100 for i in range(50)}

        snapshot = SagaSnapshot(
            snapshot_id=str(uuid4()),
            saga_id=str(uuid4()),
            saga_name="TestSaga",
            step_name="large_step",
            step_index=0,
            status="executing",
            context=large_context,
            completed_steps=[],
            created_at=datetime.now(UTC),
            retention_until=None,
        )

        await storage.save_snapshot(snapshot)
        retrieved = await storage.get_snapshot(snapshot.snapshot_id)

        assert retrieved is not None
        assert len(retrieved.context) == 50

    async def test_get_latest_with_before_step_filter(self):
        """Test getting latest snapshot with before_step filter."""
        storage = InMemorySnapshotStorage()
        saga_id = str(uuid4())

        snap1 = create_test_snapshot(saga_id=saga_id, step_name="step1")
        await storage.save_snapshot(snap1)

        import asyncio

        await asyncio.sleep(0.01)

        snap2 = create_test_snapshot(saga_id=saga_id, step_name="step2")
        await storage.save_snapshot(snap2)

        # Filter by specific step
        latest = await storage.get_latest_snapshot(saga_id, before_step="step1")
        assert latest is not None
        assert latest.step_name == "step1"

        # Filter for non-existent step
        none_result = await storage.get_latest_snapshot(saga_id, before_step="step_nonexistent")
        assert none_result is None

    async def test_get_snapshot_at_time(self):
        """Test time-travel query."""
        storage = InMemorySnapshotStorage()
        saga_id = str(uuid4())

        from datetime import timedelta

        now = datetime.now(UTC)

        # Create snapshot in the past
        past_snapshot = SagaSnapshot(
            snapshot_id=str(uuid4()),
            saga_id=saga_id,
            saga_name="TestSaga",
            step_name="old_step",
            step_index=0,
            status="executing",
            context={"version": "old"},
            completed_steps=[],
            created_at=now - timedelta(hours=2),
            retention_until=None,
        )
        await storage.save_snapshot(past_snapshot)

        # Query at past time
        result = await storage.get_snapshot_at_time(saga_id, now - timedelta(hours=1))
        assert result is not None
        assert result.context["version"] == "old"

        # Query before any snapshots
        result = await storage.get_snapshot_at_time(saga_id, now - timedelta(hours=3))
        assert result is None

        # Query for nonexistent saga
        result = await storage.get_snapshot_at_time(str(uuid4()), now)
        assert result is None

    async def test_delete_snapshot_removes_from_saga_index(self):
        """Test that delete removes snapshot from saga index."""
        storage = InMemorySnapshotStorage()
        saga_id = str(uuid4())

        snap1 = create_test_snapshot(saga_id=saga_id, step_name="step1")
        snap2 = create_test_snapshot(saga_id=saga_id, step_name="step2")

        await storage.save_snapshot(snap1)
        await storage.save_snapshot(snap2)

        # Delete one snapshot
        await storage.delete_snapshot(snap1.snapshot_id)

        # Check saga index still has remaining snapshot
        snapshots = await storage.list_snapshots(saga_id)
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_id == snap2.snapshot_id

    async def test_replay_log_operations(self):
        """Test replay log save/get/list operations."""
        from uuid import UUID

        from sagaz.core.replay import ReplayResult, ReplayStatus

        storage = InMemorySnapshotStorage()

        original_saga_id = uuid4()
        replay_id = uuid4()

        replay_result = ReplayResult(
            replay_id=replay_id,
            original_saga_id=original_saga_id,
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.SUCCESS,
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )

        # Save replay log
        await storage.save_replay_log(replay_result)

        # Get replay log
        log = await storage.get_replay_log(replay_id)
        assert log is not None
        assert log["replay_id"] == str(replay_id)
        assert log["replay_status"] == "success"  # Enum value is lowercased in to_dict()

        # List replays for saga
        replays = await storage.list_replays(original_saga_id)
        assert len(replays) == 1
        assert replays[0]["replay_id"] == str(replay_id)

        # List replays for nonexistent saga
        empty = await storage.list_replays(uuid4())
        assert len(empty) == 0

    async def test_clear_operation(self):
        """Test clear() method."""
        storage = InMemorySnapshotStorage()

        # Add data
        snapshot = create_test_snapshot()
        await storage.save_snapshot(snapshot)

        from sagaz.core.replay import ReplayResult, ReplayStatus

        replay_result = ReplayResult(
            replay_id=uuid4(),
            original_saga_id=uuid4(),
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.SUCCESS,
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        await storage.save_replay_log(replay_result)

        # Clear
        storage.clear()

        # Verify empty
        assert await storage.get_snapshot(snapshot.snapshot_id) is None
        assert await storage.get_replay_log(replay_result.replay_id) is None
        assert len(await storage.list_snapshots(snapshot.saga_id)) == 0


# ============================================================================
# Redis Backend Tests (Mocked)
# ============================================================================


@pytest.mark.asyncio
class TestRedisSnapshotStorageMocked:
    """Test Redis backend with mocks to improve coverage."""

    async def test_missing_dependency_redis(self):
        """Test error when redis not installed."""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", False):
            from sagaz.core.exceptions import MissingDependencyError
            from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

            with pytest.raises(MissingDependencyError):
                RedisSnapshotStorage()

    async def test_missing_dependency_zstd(self):
        """Test error when zstandard not installed for compression."""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.ZSTD_AVAILABLE", False):
                from sagaz.core.exceptions import MissingDependencyError
                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                with pytest.raises(MissingDependencyError):
                    RedisSnapshotStorage(enable_compression=True)


# ============================================================================
# PostgreSQL Backend Tests (Mocked)
# ============================================================================


@pytest.mark.asyncio
class TestPostgreSQLSnapshotStorageMocked:
    """Test PostgreSQL backend with mocks to improve coverage."""

    async def test_missing_dependency(self):
        """Test error when asyncpg not installed."""
        with patch("sagaz.storage.backends.postgresql.snapshot.ASYNCPG_AVAILABLE", False):
            from sagaz.core.exceptions import MissingDependencyError
            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            with pytest.raises(MissingDependencyError):
                PostgreSQLSnapshotStorage(connection_string="postgresql://localhost/test")


# ============================================================================
# S3 Backend Tests (Mocked)
# ============================================================================


@pytest.mark.asyncio
class TestS3SnapshotStorageMocked:
    """Test S3 backend with mocks to improve coverage."""

    async def test_missing_dependency_aioboto3(self):
        """Test error when aioboto3 not installed."""
        with patch("sagaz.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", False):
            from sagaz.core.exceptions import MissingDependencyError
            from sagaz.storage.backends.s3.snapshot import S3SnapshotStorage

            with pytest.raises(MissingDependencyError):
                S3SnapshotStorage(bucket_name="test-bucket")

    async def test_missing_dependency_zstd(self):
        """Test error when zstandard not installed for compression."""
        with patch("sagaz.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.storage.backends.s3.snapshot.ZSTD_AVAILABLE", False):
                from sagaz.core.exceptions import MissingDependencyError
                from sagaz.storage.backends.s3.snapshot import S3SnapshotStorage

                with pytest.raises(MissingDependencyError):
                    S3SnapshotStorage(bucket_name="test-bucket", enable_compression=True)
