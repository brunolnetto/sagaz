"""
Unit tests for Redis Snapshot Storage backend with mocks.

These are fast unit tests that don't require Docker or actual Redis.
For integration tests with real Redis, see tests/integration/test_redis_snapshot_integration.py
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.replay import ReplayResult, SagaSnapshot
from sagaz.core.types import SagaStatus


class TestRedisSnapshotStorageImportError:
    """Tests for Redis snapshot storage when redis is not available"""

    def test_redis_not_available_import_error(self):
        """Test that RedisSnapshotStorage raises MissingDependencyError"""
        with patch.dict("sys.modules", {"redis": None, "redis.asyncio": None}):
            with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", False):
                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                with pytest.raises(MissingDependencyError, match="redis"):
                    RedisSnapshotStorage(redis_url="redis://localhost")

    def test_zstd_not_available_with_compression(self):
        """Test that compression requirement raises MissingDependencyError"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.ZSTD_AVAILABLE", False):
                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                with pytest.raises(MissingDependencyError, match="zstandard"):
                    RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=True)


class TestRedisSnapshotStorageUnit:
    """Unit tests for RedisSnapshotStorage with mocked Redis"""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test Redis snapshot storage initialization"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis"):
                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(
                    redis_url="redis://localhost:6379",
                    key_prefix="test:",
                    default_ttl=3600,
                    enable_compression=False,  # Disable to avoid zstd requirement
                )
                assert storage.redis_url == "redis://localhost:6379"
                assert storage.key_prefix == "test:"
                assert storage.default_ttl == 3600

    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test Redis connection error handling"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock(side_effect=Exception("Connection refused"))
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://invalid:9999", enable_compression=False)

                with pytest.raises(ConnectionError, match="Failed to connect"):
                    await storage._get_redis()

    @pytest.mark.asyncio
    async def test_save_snapshot_mocked(self):
        """Test save_snapshot with mocked Redis"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                # Mock Redis client
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_client.set = AsyncMock()
                mock_client.zadd = AsyncMock()
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                # Create test snapshot
                saga_id = uuid4()
                snapshot = SagaSnapshot(
                    snapshot_id=uuid4(),
                    saga_id=saga_id,
                    saga_name="test_saga",
                    step_name="test_step",
                    step_index=0,
                    status=SagaStatus.EXECUTING,
                    context={"test": "data"},
                    completed_steps=[],
                    created_at=datetime.now(UTC),
                    retention_until=None,
                )

                # Test save
                await storage.save_snapshot(snapshot)

                # Verify Redis calls
                assert mock_client.set.called
                assert mock_client.zadd.called

    @pytest.mark.asyncio
    async def test_get_snapshot_found(self):
        """Test get_snapshot when snapshot exists"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()

                # Create test data
                saga_id = uuid4()
                snapshot_id = uuid4()
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(saga_id),
                    "saga_name": "test_saga",
                    "step_name": "test_step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {"test": "data"},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                    "retention_until": None,
                }
                mock_client.get = AsyncMock(return_value=json.dumps(snapshot_data).encode("utf-8"))
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                # Test get
                result = await storage.get_snapshot(snapshot_id)

                assert result is not None
                assert result.snapshot_id == snapshot_id
                assert result.saga_id == saga_id
                assert result.saga_name == "test_saga"

    @pytest.mark.asyncio
    async def test_get_snapshot_not_found(self):
        """Test get_snapshot when snapshot doesn't exist"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_client.get = AsyncMock(return_value=None)
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                result = await storage.get_snapshot(uuid4())
                assert result is None

    @pytest.mark.asyncio
    async def test_list_snapshots(self):
        """Test list_snapshots"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()

                # Mock snapshot IDs
                snapshot_id = uuid4()
                mock_client.zrevrange = AsyncMock(return_value=[str(snapshot_id).encode("utf-8")])

                # Mock snapshot data
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(uuid4()),
                    "saga_name": "test_saga",
                    "step_name": "test_step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                    "retention_until": None,
                }
                mock_client.get = AsyncMock(return_value=json.dumps(snapshot_data).encode("utf-8"))
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                result = await storage.list_snapshots(saga_id=uuid4())
                assert len(result) == 1
                assert result[0].snapshot_id == snapshot_id

    @pytest.mark.asyncio
    async def test_delete_snapshot(self):
        """Test delete_snapshot"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()

                snapshot_id = uuid4()
                saga_id = uuid4()

                # Mock get for snapshot data
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(saga_id),
                    "saga_name": "test",
                    "step_name": "step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                    "retention_until": None,
                }
                mock_client.get = AsyncMock(return_value=json.dumps(snapshot_data).encode("utf-8"))
                mock_client.delete = AsyncMock(return_value=1)
                mock_client.zrem = AsyncMock()
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                result = await storage.delete_snapshot(snapshot_id)
                assert result is True

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close connection"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_client.close = AsyncMock()
                mock_client.connection_pool = AsyncMock()
                mock_client.connection_pool.disconnect = AsyncMock()
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)
                await storage._get_redis()  # Initialize connection
                await storage.close()

                assert mock_client.close.called
                assert mock_client.connection_pool.disconnect.called

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_client.close = AsyncMock()
                mock_client.connection_pool = AsyncMock()
                mock_client.connection_pool.disconnect = AsyncMock()
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                async with RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False) as storage:
                    assert storage._redis is not None

                assert mock_client.close.called


class TestRedisSnapshotStorageCompression:
    """Tests for compression functionality"""

    @pytest.mark.asyncio
    async def test_compression_enabled(self):
        """Test snapshot storage with compression"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.ZSTD_AVAILABLE", True):
                with patch("sagaz.storage.backends.redis.snapshot.zstd") as mock_zstd:
                    with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                        # Mock compressor
                        mock_compressor = Mock()
                        mock_compressor.compress = Mock(return_value=b"compressed_data")
                        mock_zstd.ZstdCompressor = Mock(return_value=mock_compressor)

                        # Mock decompressor
                        mock_decompressor = Mock()
                        mock_decompressor.decompress = Mock(return_value=b'{"test": "data"}')
                        mock_zstd.ZstdDecompressor = Mock(return_value=mock_decompressor)

                        mock_client = AsyncMock()
                        mock_client.ping = AsyncMock()
                        mock_client.set = AsyncMock()
                        mock_client.zadd = AsyncMock()
                        mock_redis.from_url = MagicMock(return_value=mock_client)

                        from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                        storage = RedisSnapshotStorage(
                            redis_url="redis://localhost",
                            enable_compression=True,
                            compression_level=5,
                        )

                        assert storage.enable_compression is True
                        assert storage.compression_level == 5

    @pytest.mark.asyncio
    async def test_compression_disabled(self):
        """Test snapshot storage without compression"""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis"):
                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(
                    redis_url="redis://localhost",
                    enable_compression=False,
                )

                assert storage.enable_compression is False
                assert storage._compressor is None
                assert storage._decompressor is None


class TestRedisSnapshotStorageAdvanced:
    """Additional tests for Redis snapshot storage edge cases."""

    @pytest.mark.asyncio
    async def test_save_snapshot_with_retention_ttl(self):
        """Test save_snapshot sets TTL when retention_until is specified."""
        from datetime import UTC, datetime, timedelta

        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_client.set = AsyncMock()
                mock_client.expire = AsyncMock()
                mock_client.zadd = AsyncMock()
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.core.replay import SagaSnapshot
                from sagaz.core.types import SagaStatus
                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                retention_until = datetime.now(UTC) + timedelta(hours=1)
                snapshot = SagaSnapshot(
                    snapshot_id=uuid4(),
                    saga_id=uuid4(),
                    saga_name="test_saga",
                    step_name="test_step",
                    step_index=0,
                    status=SagaStatus.EXECUTING,
                    context={"test": "data"},
                    completed_steps=[],
                    created_at=datetime.now(UTC),
                    retention_until=retention_until,
                )

                await storage.save_snapshot(snapshot)
                assert mock_client.expire.called

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_no_matching_step(self):
        """Test get_latest_snapshot returns None when no matching step found."""
        from datetime import UTC, datetime

        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_client.zrevrange = AsyncMock(return_value=[
                    str(uuid4()).encode("utf-8"),
                ])

                snapshot_data = {
                    "snapshot_id": str(uuid4()),
                    "saga_id": str(uuid4()),
                    "saga_name": "test",
                    "step_name": "different_step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                    "retention_until": None,
                }
                mock_client.get = AsyncMock(return_value=json.dumps(snapshot_data).encode("utf-8"))
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                result = await storage.get_latest_snapshot(uuid4(), before_step="nonexistent_step")
                assert result is None

    @pytest.mark.asyncio
    async def test_delete_snapshot_not_found(self):
        """Test delete_snapshot returns False when snapshot doesn't exist."""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_client.get = AsyncMock(return_value=None)
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                result = await storage.delete_snapshot(uuid4())
                assert result is False

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots_returns_zero(self):
        """Test delete_expired_snapshots returns 0 (handled by Redis TTL)."""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                result = await storage.delete_expired_snapshots()
                assert result == 0

    @pytest.mark.asyncio
    async def test_get_replay_log_not_found(self):
        """Test get_replay_log returns None when replay doesn't exist."""
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_client.get = AsyncMock(return_value=None)
                mock_redis.from_url = MagicMock(return_value=mock_client)

                from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage

                storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)

                result = await storage.get_replay_log(uuid4())
                assert result is None

