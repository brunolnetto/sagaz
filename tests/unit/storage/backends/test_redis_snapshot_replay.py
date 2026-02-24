"""
Unit tests for Redis Snapshot Storage Replay functionality.
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sagaz.core.replay import ReplayResult, ReplayStatus
from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage
from sagaz.core.exceptions import MissingDependencyError


class TestRedisSnapshotReplay:
    """Test replay log functionality in Redis storage"""
    
    @pytest.fixture
    def mock_redis(self):
        with patch("sagaz.storage.backends.redis.snapshot.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.backends.redis.snapshot.redis") as mock_redis:
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock()
                mock_redis.from_url = MagicMock(return_value=mock_client)
                yield mock_client

    @pytest.mark.asyncio
    async def test_save_replay_log(self, mock_redis):
        """Test saving replay log entry"""
        storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)
        
        # Create replay result
        replay_id = uuid4()
        original_saga_id = uuid4()
        
        result = ReplayResult(
            replay_id=replay_id,
            original_saga_id=original_saga_id,
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.SUCCESS,
            initiated_by="user",
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC)
        )
        
        await storage.save_replay_log(result)
        
        # Verify calls
        assert mock_redis.set.called
        # Check that zadd was called for indexing (this covers _saga_replays_key)
        assert mock_redis.zadd.called
        call_args = mock_redis.zadd.call_args
        assert str(original_saga_id) in call_args[0][0]  # Key contains saga_id

    @pytest.mark.asyncio
    async def test_save_replay_log_with_ttl(self, mock_redis):
        """Test saving replay log with TTL"""
        storage = RedisSnapshotStorage(
            redis_url="redis://localhost", 
            enable_compression=False,
            default_ttl=3600
        )
        
        result = ReplayResult(
            replay_id=uuid4(),
            original_saga_id=uuid4(),
            new_saga_id=uuid4(),
            checkpoint_step="step1",
            replay_status=ReplayStatus.SUCCESS
        )
        
        await storage.save_replay_log(result)
        assert mock_redis.expire.called

    @pytest.mark.asyncio
    async def test_get_replay_log_success(self, mock_redis):
        """Test retrieving existing replay log"""
        storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)
        
        replay_id = uuid4()
        replay_data = {
            "replay_id": str(replay_id),
            "original_saga_id": str(uuid4()),
            "new_saga_id": str(uuid4()),
            "checkpoint_step": "step1",
            "replay_status": "success",
            "initiated_by": "system",
            "created_at": datetime.now(UTC).isoformat(),
        }
        
        mock_redis.get = AsyncMock(return_value=json.dumps(replay_data).encode("utf-8"))
        
        result = await storage.get_replay_log(replay_id)
        
        assert result is not None
        assert result["replay_id"] == str(replay_id)
        assert result["replay_status"] == "success"

    @pytest.mark.asyncio
    async def test_list_replays(self, mock_redis):
        """Test listing replays"""
        storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)
        
        original_saga_id = uuid4()
        replay_id_1 = uuid4()
        replay_id_2 = uuid4()
        
        # Mock index response
        mock_redis.zrevrange = AsyncMock(return_value=[
            str(replay_id_1).encode("utf-8"),
            str(replay_id_2).encode("utf-8")
        ])
        
        # Mock get calls
        data1 = {
            "replay_id": str(replay_id_1), 
            "original_saga_id": str(original_saga_id),
            "status": "success"
        }
        data2 = {
            "replay_id": str(replay_id_2), 
            "original_saga_id": str(original_saga_id),
            "status": "failed"
        }
        
        # Configure side effect for get
        async def get_side_effect(key):
            if str(replay_id_1) in key:
                return json.dumps(data1).encode("utf-8")
            if str(replay_id_2) in key:
                return json.dumps(data2).encode("utf-8")
            return None
            
        mock_redis.get = AsyncMock(side_effect=get_side_effect)
        
        replays = await storage.list_replays(original_saga_id)
        
        assert len(replays) == 2
        assert replays[0]["replay_id"] == str(replay_id_1)
        assert replays[1]["replay_id"] == str(replay_id_2)

    @pytest.mark.asyncio
    async def test_list_replays_empty(self, mock_redis):
        """Test listing replays when none exist"""
        storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)
        
        mock_redis.zrevrange = AsyncMock(return_value=[])
        
        replays = await storage.list_replays(uuid4())
        assert len(replays) == 0

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time_empty(self, mock_redis):
        """Test get_snapshot_at_time when no snapshot found"""
        storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)
        
        # Return empty list from zrevrangebyscore
        mock_redis.zrevrangebyscore = AsyncMock(return_value=[])
        
        result = await storage.get_snapshot_at_time(uuid4(), datetime.now(UTC))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_empty_ids(self, mock_redis):
        """Test get_latest_snapshot when saga has no snapshots"""
        storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)
        mock_redis.zrevrange = AsyncMock(return_value=[])
        result = await storage.get_latest_snapshot(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_missing_snapshot(self, mock_redis):
        """Test get_latest_snapshot when snapshot keys are missing (race condition/cleanup)"""
        storage = RedisSnapshotStorage(redis_url="redis://localhost", enable_compression=False)
        snapshot_id = uuid4()
        mock_redis.zrevrange = AsyncMock(return_value=[str(snapshot_id).encode("utf-8")])
        mock_redis.get = AsyncMock(return_value=None)  # Snapshot missing
        
        result = await storage.get_latest_snapshot(uuid4())
        assert result is None
