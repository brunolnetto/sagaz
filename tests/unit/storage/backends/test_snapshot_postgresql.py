"""
Tests for PostgreSQL Snapshot Storage backend.

Covers snapshot creation, retrieval, listing, deletion, and time-travel functionality.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.replay import ReplayResult, SagaSnapshot, SnapshotNotFoundError
from sagaz.core.types import SagaStatus
from sagaz.storage.base import SagaStorageConnectionError

# Check availability of dependencies
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

try:
    from testcontainers.postgres import PostgresContainer

    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False


# ============================================
# UNIT/MOCKED TESTS
# ============================================


class TestPostgreSQLSnapshotStorageImportError:
    """Tests for PostgreSQL snapshot storage when asyncpg is not available"""

    def test_asyncpg_not_available_import_error(self):
        """Test that PostgreSQLSnapshotStorage raises MissingDependencyError"""
        with patch.dict("sys.modules", {"asyncpg": None}):
            with patch("sagaz.storage.backends.postgresql.snapshot.ASYNCPG_AVAILABLE", False):
                from sagaz.storage.backends.postgresql.snapshot import (
                    PostgreSQLSnapshotStorage,
                )

                with pytest.raises(MissingDependencyError):
                    PostgreSQLSnapshotStorage(connection_string="postgresql://...")


class TestPostgreSQLSnapshotStorageUnit:
    """Unit tests for PostgreSQLSnapshotStorage with mocked asyncpg"""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test PostgreSQL snapshot storage initialization"""
        with patch("sagaz.storage.backends.postgresql.snapshot.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg"):
                from sagaz.storage.backends.postgresql.snapshot import (
                    PostgreSQLSnapshotStorage,
                )

                storage = PostgreSQLSnapshotStorage(connection_string="postgresql://localhost/test")
                assert storage.connection_string == "postgresql://localhost/test"

    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test PostgreSQL connection error handling"""
        with patch("sagaz.storage.backends.postgresql.snapshot.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
                mock_asyncpg.create_pool = AsyncMock(side_effect=Exception("Connection refused"))

                from sagaz.storage.backends.postgresql.snapshot import (
                    PostgreSQLSnapshotStorage,
                )

                storage = PostgreSQLSnapshotStorage(
                    connection_string="postgresql://invalid:9999/test"
                )

                with pytest.raises(ConnectionError, match="Failed to connect"):
                    await storage._get_pool()

    @pytest.mark.asyncio
    async def test_save_snapshot_mocked(self):
        """Test save_snapshot with mocked database"""
        with patch("sagaz.storage.backends.postgresql.snapshot.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
                # Mock pool and connection
                mock_pool = AsyncMock()
                mock_conn = AsyncMock()
                mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
                # Mock acquire to return an async context manager
                mock_pool.acquire = MagicMock(
                    return_value=AsyncMock(
                        __aenter__=AsyncMock(return_value=mock_conn),
                        __aexit__=AsyncMock(return_value=None),
                    )
                )

                # Mock execute for table creation and insert
                mock_conn.execute = AsyncMock(return_value="INSERT 1")

                from sagaz.storage.backends.postgresql.snapshot import (
                    PostgreSQLSnapshotStorage,
                )

                storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")

                # Create a snapshot
                snapshot = SagaSnapshot(
                    snapshot_id=uuid4(),
                    saga_id=uuid4(),
                    saga_name="test_saga",
                    step_name="step1",
                    step_index=0,
                    status=SagaStatus.EXECUTING,
                    context={"key": "value"},
                    completed_steps=[],
                    created_at=datetime.now(UTC),
                    retention_until=None,
                )

                await storage.save_snapshot(snapshot)
                assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_get_snapshot_not_found(self):
        """Test get_snapshot when snapshot doesn't exist"""
        with patch("sagaz.storage.backends.postgresql.snapshot.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
                mock_pool = AsyncMock()
                mock_conn = AsyncMock()
                mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
                # Mock acquire to return an async context manager
                mock_pool.acquire = MagicMock(
                    return_value=AsyncMock(
                        __aenter__=AsyncMock(return_value=mock_conn),
                        __aexit__=AsyncMock(return_value=None),
                    )
                )
                # Mock execute for table creation
                mock_conn.execute = AsyncMock(return_value=None)
                # Mock fetchrow to return None (not found)
                mock_conn.fetchrow = AsyncMock(return_value=None)

                from sagaz.storage.backends.postgresql.snapshot import (
                    PostgreSQLSnapshotStorage,
                )

                storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")

                # Should return None for non-existent snapshot
                result = await storage.get_snapshot(snapshot_id=uuid4())
                assert result is None

    @pytest.mark.asyncio
    async def test_list_snapshots_empty(self):
        """Test list_snapshots when no snapshots exist"""
        with patch("sagaz.storage.backends.postgresql.snapshot.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
                mock_pool = AsyncMock()
                mock_conn = AsyncMock()
                mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
                # Mock acquire to return an async context manager
                mock_pool.acquire = MagicMock(
                    return_value=AsyncMock(
                        __aenter__=AsyncMock(return_value=mock_conn),
                        __aexit__=AsyncMock(return_value=None),
                    )
                )
                # Mock fetch to return empty list
                mock_conn.fetch = AsyncMock(return_value=[])

                from sagaz.storage.backends.postgresql.snapshot import (
                    PostgreSQLSnapshotStorage,
                )

                storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")

                result = await storage.list_snapshots(saga_id=uuid4())
                assert result == []

    @pytest.mark.asyncio
    async def test_delete_snapshot_mocked(self):
        """Test delete_snapshot with mocked database"""
        with patch("sagaz.storage.backends.postgresql.snapshot.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
                mock_pool = AsyncMock()
                mock_conn = AsyncMock()
                mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
                # Mock acquire to return an async context manager
                mock_pool.acquire = MagicMock(
                    return_value=AsyncMock(
                        __aenter__=AsyncMock(return_value=mock_conn),
                        __aexit__=AsyncMock(return_value=None),
                    )
                )
                mock_conn.execute = AsyncMock(return_value="DELETE 1")

                from sagaz.storage.backends.postgresql.snapshot import (
                    PostgreSQLSnapshotStorage,
                )

                storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")

                await storage.delete_snapshot(snapshot_id=uuid4())
                assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test cleanup closes the connection pool"""
        with patch("sagaz.storage.backends.postgresql.snapshot.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.backends.postgresql.snapshot.asyncpg") as mock_asyncpg:
                mock_pool = AsyncMock()
                mock_conn = AsyncMock()
                mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

                # Mock acquire for _get_pool table creation
                mock_pool.acquire = MagicMock(
                    return_value=AsyncMock(
                        __aenter__=AsyncMock(return_value=mock_conn),
                        __aexit__=AsyncMock(return_value=None),
                    )
                )
                mock_conn.execute = AsyncMock(return_value=None)
                mock_pool.close = AsyncMock()

                from sagaz.storage.backends.postgresql.snapshot import (
                    PostgreSQLSnapshotStorage,
                )

                storage = PostgreSQLSnapshotStorage("postgresql://localhost/test")
                # Create pool first
                await storage._get_pool()
                # Then close it
                await storage.close()

                assert mock_pool.close.called


# ============================================
# INTEGRATION TESTS (with real PostgreSQL)
# ============================================


@pytest.mark.integration
@pytest.mark.skipif(
    not ASYNCPG_AVAILABLE or not TESTCONTAINERS_AVAILABLE,
    reason="Requires asyncpg and testcontainers",
)
class TestPostgreSQLSnapshotStorageIntegration:
    """Integration tests for PostgreSQL snapshot storage with real database"""

    @pytest.fixture(scope="class")
    def postgres_container(self):
        """Start PostgreSQL container for testing"""
        container = PostgresContainer("postgres:15-alpine")
        container.start()
        yield container
        container.stop()

    @pytest.fixture
    async def storage(self, postgres_container):
        """Create PostgreSQL snapshot storage instance"""
        from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

        connection_string = postgres_container.get_connection_url()
        # Fix DSN format: asyncpg only understands postgresql:// or postgres://
        connection_string = connection_string.replace("postgresql+asyncpg://", "postgresql://")
        connection_string = connection_string.replace("postgresql+psycopg2://", "postgresql://")
        connection_string = connection_string.replace("postgresql+psycopg://", "postgresql://")
        
        storage = PostgreSQLSnapshotStorage(connection_string=connection_string)
        yield storage
        await storage.close()

    @pytest.mark.asyncio
    async def test_save_and_get_snapshot(self, storage):
        """Test saving and retrieving a snapshot"""
        saga_id = uuid4()
        snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="payment_saga",
            step_name="authorize_payment",
            step_index=1,
            status=SagaStatus.EXECUTING,
            context={"amount": 100.50, "currency": "USD"},
            completed_steps=[],
            created_at=datetime.now(UTC),
        )

        # Save snapshot
        await storage.save_snapshot(snapshot)

        # Retrieve snapshot
        retrieved = await storage.get_snapshot(snapshot_id=snapshot.snapshot_id)
        assert retrieved is not None
        assert retrieved.saga_id == saga_id
        assert retrieved.saga_name == "payment_saga"
        assert retrieved.step_name == "authorize_payment"
        assert retrieved.context["amount"] == 100.50

    @pytest.mark.asyncio
    async def test_list_snapshots(self, storage):
        """Test listing snapshots for a saga"""
        saga_id = uuid4()

        # Create multiple snapshots
        for i in range(3):
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="test_saga",
                step_name=f"step_{i}",
                step_index=i,
                status=SagaStatus.EXECUTING,
                context={"step": i},
                completed_steps=[],
                created_at=datetime.now(UTC),
            )
            await storage.save_snapshot(snapshot)

        # List snapshots
        snapshots = await storage.list_snapshots(saga_id=saga_id)
        assert len(snapshots) == 3
        assert all(s.saga_id == saga_id for s in snapshots)

    @pytest.mark.asyncio
    async def test_list_snapshots_with_limit(self, storage):
        """Test listing snapshots with limit"""
        saga_id = uuid4()

        # Create 5 snapshots
        for i in range(5):
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="test_saga",
                step_name=f"step_{i}",
                step_index=i,
                status=SagaStatus.EXECUTING,
                context={"step": i},
                completed_steps=[],
                created_at=datetime.now(UTC),
            )
            await storage.save_snapshot(snapshot)

        # List with limit
        snapshots = await storage.list_snapshots(saga_id=saga_id, limit=3)
        assert len(snapshots) == 3

    @pytest.mark.asyncio
    async def test_delete_snapshot(self, storage):
        """Test deleting a snapshot"""
        snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=uuid4(),
            saga_name="test_saga",
            step_name="step1",
            step_index=0,
            status=SagaStatus.EXECUTING,
            context={},
            completed_steps=[],
            created_at=datetime.now(UTC),
        )

        # Save and then delete
        await storage.save_snapshot(snapshot)
        deleted = await storage.delete_snapshot(snapshot_id=snapshot.snapshot_id)
        assert deleted is True

        # Verify deleted - should return None
        retrieved = await storage.get_snapshot(snapshot_id=snapshot.snapshot_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_latest_snapshot(self, storage):
        """Test getting the most recent snapshot"""
        saga_id = uuid4()

        # Create snapshots with delays
        for i in range(3):
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="test_saga",
                step_name=f"step_{i}",
                step_index=i,
                status=SagaStatus.EXECUTING,
                context={"step": i, "latest": i == 2},
                completed_steps=[],
                created_at=datetime.now(UTC),
            )
            await storage.save_snapshot(snapshot)

        # Get latest
        latest = await storage.get_latest_snapshot(saga_id=saga_id)
        assert latest is not None
        assert latest.context["latest"] is True

    @pytest.mark.asyncio
    async def test_prune_old_snapshots(self, storage):
        """Test pruning snapshots older than retention period"""
        saga_id = uuid4()

        # Create old snapshot with expired retention
        old_snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="test_saga",
            step_name="step_old",
            step_index=0,
            status=SagaStatus.COMPLETED,
            context={},
            completed_steps=[],
            created_at=datetime.now(UTC) - timedelta(days=31),
            retention_until=datetime.now(UTC) - timedelta(days=1),  # Expired
        )

        # Create recent snapshot
        recent_snapshot = SagaSnapshot(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name="test_saga",
            step_name="step_recent",
            step_index=1,
            status=SagaStatus.EXECUTING,
            context={},
            completed_steps=[],
            created_at=datetime.now(UTC),
        )

        await storage.save_snapshot(old_snapshot)
        await storage.save_snapshot(recent_snapshot)

        # Delete expired snapshots (older than retention period)
        deleted_count = await storage.delete_expired_snapshots()
        assert deleted_count >= 1  # Should delete the expired snapshot

        # Verify old deleted, recent remains
        old_retrieved = await storage.get_snapshot(snapshot_id=old_snapshot.snapshot_id)
        assert old_retrieved is None  # Should be deleted

        retrieved_recent = await storage.get_snapshot(snapshot_id=recent_snapshot.snapshot_id)
        assert retrieved_recent is not None
