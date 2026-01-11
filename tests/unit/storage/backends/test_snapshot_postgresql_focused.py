"""
Focused tests for PostgreSQL Snapshot Storage to improve coverage.
Tests key uncovered paths in the snapshot storage implementation.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.replay import SagaSnapshot
from sagaz.core.types import SagaStatus

# Check asyncpg availability
try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False


@pytest.mark.skipif(not ASYNCPG_AVAILABLE, reason="Requires asyncpg")
class TestPostgreSQLSnapshotStorageFocused:
    """Focused tests to cover uncovered lines in PostgreSQL snapshot storage"""

    @pytest.mark.asyncio
    async def test_save_and_get_snapshot_methods(self):
        """Test save_snapshot and get_snapshot core logic"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            # Setup mocks
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            
            # Mock pool.acquire() context manager
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            
            # Mock execute for CREATE TABLE
            mock_conn.execute = AsyncMock(return_value=None)
            
            # Mock fetchrow for get_snapshot
            test_data = {
                "snapshot_id": uuid4(),
                "saga_id": uuid4(),
                "saga_name": "test_saga",
                "step_name": "step1",
                "step_index": 0,
                "status": "RUNNING",
                "context": '{"key": "value"}',
                "completed_steps": '[]',
                "created_at": datetime.now(UTC),
                "retention_until": None,
            }
            mock_conn.fetchrow = AsyncMock(return_value=test_data)
            
            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage
            
            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            
            # Test save_snapshot
            snapshot = SagaSnapshot(
                snapshot_id=test_data["snapshot_id"],
                saga_id=test_data["saga_id"],
                saga_name="test_saga",
                step_name="step1",
                step_index=0,
                status=SagaStatus.RUNNING,
                context={"key": "value"},
                completed_steps=[],
                created_at=datetime.now(UTC),
                retention_until=None,
            )
            
            await storage.save_snapshot(snapshot)
            assert mock_conn.execute.called
            
            # Test get_snapshot
            result = await storage.get_snapshot(test_data["snapshot_id"])
            assert result is not None
            assert result.saga_name == "test_saga"
    
    @pytest.mark.asyncio
    async def test_get_snapshot_returns_none(self):
        """Test get_snapshot returns None when not found"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            
            # Mock execute for CREATE TABLE
            mock_conn.execute = AsyncMock(return_value=None)
            # Mock fetchrow returns None (not found)
            mock_conn.fetchrow = AsyncMock(return_value=None)
            
            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage
            
            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.get_snapshot(uuid4())
            assert result is None

    @pytest.mark.asyncio
    async def test_list_snapshots(self):
        """Test list_snapshots method"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_conn.execute = AsyncMock(return_value=None)
            
            # Mock fetch returns list of snapshots
            mock_conn.fetch = AsyncMock(return_value=[
                {
                    "snapshot_id": uuid4(),
                    "saga_id": uuid4(),
                    "saga_name": "test_saga",
                    "step_name": "step1",
                    "step_index": 0,
                    "status": "RUNNING",
                    "context": '{"key": "value"}',
                    "completed_steps": '[]',
                    "created_at": datetime.now(UTC),
                    "retention_until": None,
                }
            ])
            
            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage
            
            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.list_snapshots(uuid4())
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_latest_snapshot(self):
        """Test get_latest_snapshot method"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_conn.execute = AsyncMock(return_value=None)
            mock_conn.fetchrow = AsyncMock(return_value={
                "snapshot_id": uuid4(),
                "saga_id": uuid4(),
                "saga_name": "test_saga",
                "step_name": "step1",
                "step_index": 0,
                "status": "RUNNING",
                "context": '{}',
                "completed_steps": '[]',
                "created_at": datetime.now(UTC),
                "retention_until": None,
            })
            
            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage
            
            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.get_latest_snapshot(uuid4())
            assert result is not None

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time(self):
        """Test get_snapshot_at_time method"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_conn.execute = AsyncMock(return_value=None)
            mock_conn.fetchrow = AsyncMock(return_value={
                "snapshot_id": uuid4(),
                "saga_id": uuid4(),
                "saga_name": "test_saga",
                "step_name": "step1",
                "step_index": 0,
                "status": "COMPLETED",
                "context": '{}',
                "completed_steps": '[]',
                "created_at": datetime.now(UTC),
                "retention_until": None,
            })
            
            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage
            
            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.get_snapshot_at_time(uuid4(), datetime.now(UTC))
            assert result is not None

    @pytest.mark.asyncio
    async def test_delete_snapshot(self):
        """Test delete_snapshot method"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_conn.execute = AsyncMock(return_value="DELETE 1")
            
            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage
            
            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.delete_snapshot(uuid4())
            assert result is True

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots(self):
        """Test delete_expired_snapshots method"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_conn.execute = AsyncMock(return_value="DELETE 5")
            
            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage
            
            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            result = await storage.delete_expired_snapshots()
            assert result == 5

    @pytest.mark.asyncio
    async def test_close_method(self):
        """Test close method"""
        with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_pool.close = AsyncMock()
            
            from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage
            
            storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
            # Create pool
            await storage._get_pool()
            # Close it
            await storage.close()
            assert mock_pool.close.called
