"""
Complete test coverage for PostgreSQL Snapshot Storage.
Targets all uncovered paths to reach 95%+ coverage.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.replay import ReplayResult, ReplayStatus, SagaSnapshot
from sagaz.core.types import SagaStatus

# Check asyncpg availability
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False


@pytest.mark.skipif(not ASYNCPG_AVAILABLE, reason="Requires asyncpg")
class TestPostgreSQLSnapshotComplete:
    """Complete coverage tests for PostgreSQL snapshot storage"""

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_with_before_step(self):
        """Test get_latest_snapshot with before_step parameter"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            test_data = self._create_test_snapshot_data()
            mock_conn.fetchrow = AsyncMock(return_value=test_data)

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.get_latest_snapshot(test_data["saga_id"], before_step="step1")

            assert result is not None
            assert result.step_name == "step1"
            assert mock_conn.fetchrow.called

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_without_before_step(self):
        """Test get_latest_snapshot without before_step parameter"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            test_data = self._create_test_snapshot_data()
            mock_conn.fetchrow = AsyncMock(return_value=test_data)

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.get_latest_snapshot(test_data["saga_id"])

            assert result is not None
            assert mock_conn.fetchrow.called

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time_found(self):
        """Test get_snapshot_at_time when snapshot exists"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            test_data = self._create_test_snapshot_data()
            mock_conn.fetchrow = AsyncMock(return_value=test_data)

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            timestamp = datetime.now(UTC)
            result = await storage.get_snapshot_at_time(test_data["saga_id"], timestamp)

            assert result is not None
            assert mock_conn.fetchrow.called

    @pytest.mark.asyncio
    async def test_list_snapshots_with_results(self):
        """Test list_snapshots returns multiple snapshots"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            test_data1 = self._create_test_snapshot_data()
            test_data2 = self._create_test_snapshot_data()
            mock_conn.fetch = AsyncMock(return_value=[test_data1, test_data2])

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            results = await storage.list_snapshots(test_data1["saga_id"], limit=10)

            assert len(results) == 2
            assert mock_conn.fetch.called

    @pytest.mark.asyncio
    async def test_delete_snapshot_success(self):
        """Test delete_snapshot successfully deletes"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            mock_conn.execute = AsyncMock(return_value="DELETE 1")

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.delete_snapshot(uuid4())

            assert result is True
            assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_delete_snapshot_not_found(self):
        """Test delete_snapshot when snapshot doesn't exist"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            mock_conn.execute = AsyncMock(return_value="DELETE 0")

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.delete_snapshot(uuid4())

            assert result is False

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots(self):
        """Test delete_expired_snapshots removes old snapshots"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            mock_conn.execute = AsyncMock(return_value="DELETE 5")

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            count = await storage.delete_expired_snapshots()

            assert count == 5
            assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots_none_deleted(self):
        """Test delete_expired_snapshots when none are expired"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            mock_conn.execute = AsyncMock(return_value="DELETE 0")

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            count = await storage.delete_expired_snapshots()

            assert count == 0

    @pytest.mark.asyncio
    async def test_save_replay_log(self):
        """Test save_replay_log saves replay result"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            mock_conn.execute = AsyncMock(return_value=None)

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            
            replay_result = ReplayResult(
                replay_id=uuid4(),
                original_saga_id=uuid4(),
                new_saga_id=uuid4(),
                checkpoint_step="step1",
                replay_status=ReplayStatus.SUCCESS,
                initiated_by="test_user",
                error_message=None,
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )

            await storage.save_replay_log(replay_result)
            assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_save_replay_log_with_null_context(self):
        """Test save_replay_log with null context_override"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            mock_conn.execute = AsyncMock(return_value=None)

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            
            replay_result = ReplayResult(
                replay_id=uuid4(),
                original_saga_id=uuid4(),
                new_saga_id=uuid4(),
                checkpoint_step="step1",
                replay_status=ReplayStatus.SUCCESS,
                initiated_by="test_user",
                error_message=None,
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )

            await storage.save_replay_log(replay_result)
            assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_get_replay_log_found(self):
        """Test get_replay_log returns replay data"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            replay_id = uuid4()
            test_data = {
                "replay_id": replay_id,
                "original_saga_id": uuid4(),
                "new_saga_id": uuid4(),
                "checkpoint_step": "step1",
                "context_override": '{"key": "value"}',
                "initiated_by": "test_user",
                "replay_status": "success",
                "error_message": None,
                "created_at": datetime.now(UTC),
                "completed_at": datetime.now(UTC),
            }
            mock_conn.fetchrow = AsyncMock(return_value=test_data)

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.get_replay_log(replay_id)

            assert result is not None
            assert result["checkpoint_step"] == "step1"
            assert result["context_override"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_replay_log_with_null_timestamps(self):
        """Test get_replay_log with null timestamps"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            replay_id = uuid4()
            test_data = {
                "replay_id": replay_id,
                "original_saga_id": uuid4(),
                "new_saga_id": uuid4(),
                "checkpoint_step": "step1",
                "context_override": None,
                "initiated_by": "test_user",
                "replay_status": "pending",
                "error_message": "test error",
                "created_at": None,
                "completed_at": None,
            }
            mock_conn.fetchrow = AsyncMock(return_value=test_data)

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.get_replay_log(replay_id)

            assert result is not None
            assert result["created_at"] is None
            assert result["completed_at"] is None
            assert result["context_override"] is None

    @pytest.mark.asyncio
    async def test_list_replays(self):
        """Test list_replays returns multiple replays"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            original_saga_id = uuid4()
            test_data1 = {
                "replay_id": uuid4(),
                "original_saga_id": original_saga_id,
                "new_saga_id": uuid4(),
                "checkpoint_step": "step1",
                "context_override": '{"key": "value1"}',
                "initiated_by": "user1",
                "replay_status": "success",
                "error_message": None,
                "created_at": datetime.now(UTC),
                "completed_at": datetime.now(UTC),
            }
            test_data2 = {
                "replay_id": uuid4(),
                "original_saga_id": original_saga_id,
                "new_saga_id": uuid4(),
                "checkpoint_step": "step2",
                "context_override": None,
                "initiated_by": "user2",
                "replay_status": "failed",
                "error_message": "error",
                "created_at": datetime.now(UTC),
                "completed_at": None,
            }
            mock_conn.fetch = AsyncMock(return_value=[test_data1, test_data2])

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            results = await storage.list_replays(original_saga_id, limit=10)

            assert len(results) == 2
            assert results[0]["context_override"] == {"key": "value1"}
            assert results[1]["context_override"] is None
            assert results[1]["completed_at"] is None

    @pytest.mark.asyncio
    async def test_row_to_snapshot_with_string_json(self):
        """Test _row_to_snapshot converts string JSON"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            test_data = self._create_test_snapshot_data()
            # Ensure context and completed_steps are strings
            test_data["context"] = '{"key": "value"}'
            test_data["completed_steps"] = '["step1"]'
            mock_conn.fetchrow = AsyncMock(return_value=test_data)

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.get_snapshot(test_data["snapshot_id"])

            assert result is not None
            assert result.context == {"key": "value"}
            assert result.completed_steps == ["step1"]

    @pytest.mark.asyncio
    async def test_row_to_snapshot_with_dict_json(self):
        """Test _row_to_snapshot with already parsed JSON"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool, mock_conn = self._setup_mocks(mock_asyncpg)

            test_data = self._create_test_snapshot_data()
            # Ensure context and completed_steps are already dicts/lists
            test_data["context"] = {"key": "value"}
            test_data["completed_steps"] = ["step1"]
            mock_conn.fetchrow = AsyncMock(return_value=test_data)

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.get_snapshot(test_data["snapshot_id"])

            assert result is not None
            assert result.context == {"key": "value"}
            assert result.completed_steps == ["step1"]

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test context manager __aenter__ and __aexit__"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_pool.acquire = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_conn),
                    __aexit__=AsyncMock(return_value=None),
                )
            )
            mock_conn.execute = AsyncMock()
            mock_pool.close = AsyncMock()

            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

            async with PostgreSQLSnapshotStorage("postgresql://localhost/test") as storage:
                assert storage is not None

            assert mock_pool.close.called

    def _setup_mocks(self, mock_asyncpg):
        """Helper to setup common mocks"""
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
        mock_pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=None),
            )
        )
        mock_conn.execute = AsyncMock()
        return mock_pool, mock_conn

    def _create_test_snapshot_data(self):
        """Helper to create test snapshot data"""
        return {
            "snapshot_id": uuid4(),
            "saga_id": uuid4(),
            "saga_name": "test_saga",
            "step_name": "step1",
            "step_index": 0,
            "status": "executing",
            "context": '{"key": "value"}',
            "completed_steps": "[]",
            "created_at": datetime.now(UTC),
            "retention_until": None,
        }
