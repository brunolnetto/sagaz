"""
Tests for PostgreSQL storage backend.
Includes unit tests, mocked tests, and integration tests using testcontainers.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.exceptions import MissingDependencyError
from sagaz.storage.base import SagaStorageConnectionError, SagaStorageError
from sagaz.types import SagaStatus, SagaStepStatus

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


class TestPostgreSQLStorageImportError:
    """Tests for PostgreSQL storage when asyncpg package is not available"""

    def test_asyncpg_not_available_import_error(self):
        """Test that PostgreSQLSagaStorage raises MissingDependencyError when asyncpg not available"""
        with patch.dict("sys.modules", {"asyncpg": None}):
            with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", False):
                from sagaz.storage.postgresql import PostgreSQLSagaStorage

                with pytest.raises(MissingDependencyError):
                    PostgreSQLSagaStorage(connection_string="postgresql://...")


class TestPostgreSQLSagaStorageUnit:
    """Unit tests for PostgreSQLSagaStorage without actual PostgreSQL"""

    @pytest.mark.asyncio
    async def test_postgresql_initialization(self):
        """Test PostgreSQL storage initialization"""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.postgresql.asyncpg"):
                from sagaz.storage.postgresql import PostgreSQLSagaStorage

                storage = PostgreSQLSagaStorage(connection_string="postgresql://localhost/test")

                assert storage.connection_string == "postgresql://localhost/test"

    @pytest.mark.asyncio
    async def test_postgresql_connection_error_handling(self):
        """Test PostgreSQL connection error handling"""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.postgresql.asyncpg") as mock_asyncpg:
                mock_asyncpg.create_pool = AsyncMock(side_effect=Exception("Connection refused"))

                from sagaz.storage.postgresql import PostgreSQLSagaStorage

                storage = PostgreSQLSagaStorage(connection_string="postgresql://invalid:9999/test")

                with pytest.raises(
                    SagaStorageConnectionError, match="Failed to connect to PostgreSQL"
                ):
                    await storage._get_pool()


class TestPostgreSQLStorageEdgeCases:
    """Tests for PostgreSQL storage edge cases"""

    @pytest.mark.asyncio
    async def test_postgresql_step_result_parsing(self):
        """Test that PostgreSQL properly parses step results"""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            # Mock storage with step that has result
            storage = MagicMock(spec=PostgreSQLSagaStorage)
            storage.load_saga_state = AsyncMock(
                return_value={
                    "saga_id": "test",
                    "saga_name": "Test",
                    "status": "completed",
                    "steps": [
                        {
                            "name": "step1",
                            "status": "completed",
                            "result": {"key": "value"},
                            "error": None,
                        }
                    ],
                    "context": {},
                    "metadata": {},
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )

            state = await storage.load_saga_state("test")
            assert state["steps"][0]["result"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_postgresql_step_with_timestamps(self):
        """Test PostgreSQL step with executed_at and compensated_at timestamps"""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            now = datetime.now(UTC)

            storage = MagicMock(spec=PostgreSQLSagaStorage)
            storage.load_saga_state = AsyncMock(
                return_value={
                    "saga_id": "test",
                    "saga_name": "Test",
                    "status": "compensated",
                    "steps": [
                        {
                            "name": "step1",
                            "status": "compensated",
                            "result": None,
                            "error": None,
                            "executed_at": now.isoformat(),
                            "compensated_at": now.isoformat(),
                        }
                    ],
                    "context": {},
                    "metadata": {},
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
            )

            state = await storage.load_saga_state("test")
            assert state["steps"][0]["executed_at"] is not None
            assert state["steps"][0]["compensated_at"] is not None


class AsyncContextManagerMock:
    """Helper class to create async context manager mocks."""

    def __init__(self, return_value=None):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


class TestPostgreSQLSagaStorageMocked:
    """Test PostgreSQLSagaStorage with mocked asyncpg."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()

        # Make execute, executemany, fetch, fetchrow, fetchval all async
        conn.execute = AsyncMock(return_value="OK")
        conn.executemany = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=1)

        # Setup async context manager for acquire
        pool.acquire.return_value = AsyncContextManagerMock(conn)

        # transaction() returns an async context manager (NOT a coroutine)
        conn.transaction.return_value = AsyncContextManagerMock(None)

        # Setup pool close as async
        pool.close = AsyncMock()
        pool.get_size = MagicMock(return_value=5)

        return pool, conn

    @pytest.mark.asyncio
    async def test_save_saga_state(self, mock_pool):
        """Test saving saga state."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool

            await storage.save_saga_state(
                saga_id="saga-123",
                saga_name="OrderSaga",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={"order_id": "123"},
                metadata={"version": 1},
            )

            # Verify execute was called for saga upsert
            assert conn.execute.called

    @pytest.mark.asyncio
    async def test_load_saga_state(self, mock_pool):
        """Test loading saga state."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool

            # Mock saga row
            saga_row = {
                "saga_id": "saga-123",
                "saga_name": "OrderSaga",
                "status": "executing",
                "context": '{"order_id": "123"}',
                "metadata": "{}",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            conn.fetchrow.return_value = saga_row

            # Mock step rows
            step_row = MagicMock()
            step_row.__getitem__ = lambda self, k: {
                "step_name": "step1",
                "status": "completed",
                "result": '{"data": "test"}',
                "error": None,
                "executed_at": datetime.now(UTC),
                "compensated_at": None,
                "retry_count": 0,
            }[k]
            conn.fetch.return_value = [step_row]

            result = await storage.load_saga_state("saga-123")

            assert result["saga_id"] == "saga-123"
            assert result["saga_name"] == "OrderSaga"

    @pytest.mark.asyncio
    async def test_update_step_state(self, mock_pool):
        """Test updating step state."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.execute.return_value = "UPDATE 1"

            await storage.update_step_state(
                saga_id="saga-123",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"success": True},
                executed_at=datetime.now(UTC),
            )

            assert conn.execute.called

    @pytest.mark.asyncio
    async def test_cleanup_completed_sagas(self, mock_pool):
        """Test cleaning up completed sagas."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.execute.return_value = "DELETE 50"

            count = await storage.cleanup_completed_sagas(
                older_than=datetime.now(UTC) - timedelta(days=30)
            )

            assert count == 50

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, mock_pool):
        """Test health check when healthy."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.fetchval.side_effect = [1, "PostgreSQL 15.0"]
            pool.get_size.return_value = 5

            result = await storage.health_check()

            assert result["status"] == "healthy"

    def test_format_bytes(self):
        """Test bytes formatting helper."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            storage = PostgreSQLSagaStorage("postgresql://localhost/test")

            assert storage._format_bytes(500) == "500.0B"
            assert storage._format_bytes(1024) == "1.0KB"
            assert storage._format_bytes(1024 * 1024) == "1.0MB"


# ============================================
# INTEGRATION TESTS
# ============================================


@pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers not available")
@pytest.mark.skipif(not ASYNCPG_AVAILABLE, reason="asyncpg not installed")
@pytest.mark.xdist_group(name="postgres")
class TestPostgreSQLStorageIntegration:
    """Tests for PostgreSQL storage with real database"""

    @pytest.mark.asyncio
    async def test_save_and_load_saga_state(self, postgres_container):
        """Test saving and loading saga state"""
        from sagaz.storage.postgresql import PostgreSQLSagaStorage

        # testcontainers returns postgresql+psycopg2://, but asyncpg expects postgresql://
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Save saga state
            await storage.save_saga_state(
                saga_id="test-123",
                saga_name="TestSaga",
                status=SagaStatus.COMPLETED,
                steps=[
                    {
                        "name": "step1",
                        "status": "completed",
                        "result": {"data": "value"},
                        "error": None,
                        "retry_count": 0,
                    }
                ],
                context={"user_id": "user-456"},
                metadata={"version": "1.0"},
            )

            # Load saga state
            state = await storage.load_saga_state("test-123")

            assert state is not None
            assert state["saga_id"] == "test-123"
            assert state["saga_name"] == "TestSaga"
            assert state["status"] == "completed"  # Enum values are lowercase
            assert state["context"] == {"user_id": "user-456"}
            assert state["metadata"] == {"version": "1.0"}
            assert len(state["steps"]) == 1
            assert state["steps"][0]["name"] == "step1"

    @pytest.mark.asyncio
    async def test_load_nonexistent_saga(self, postgres_container):
        """Test loading a saga that doesn't exist"""
        from sagaz.storage.postgresql import PostgreSQLSagaStorage

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            state = await storage.load_saga_state("nonexistent")
            assert state is None

    @pytest.mark.asyncio
    async def test_delete_saga_state(self, postgres_container):
        """Test deleting saga state"""
        from sagaz.storage.postgresql import PostgreSQLSagaStorage

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Save saga
            await storage.save_saga_state(
                saga_id="delete-me",
                saga_name="DeleteTest",
                status=SagaStatus.FAILED,
                steps=[],
                context={},
                metadata={},
            )

            # Delete it
            result = await storage.delete_saga_state("delete-me")
            assert result is True

            # Verify it's gone
            state = await storage.load_saga_state("delete-me")
            assert state is None

            # Delete again (should return False)
            result = await storage.delete_saga_state("delete-me")
            assert result is False

    @pytest.mark.asyncio
    async def test_list_sagas(self, postgres_container):
        """Test listing sagas"""
        from sagaz.storage.postgresql import PostgreSQLSagaStorage

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create completed saga
            await storage.save_saga_state(
                saga_id="completed-1",
                saga_name="TestSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            # Create failed saga
            await storage.save_saga_state(
                saga_id="failed-1",
                saga_name="TestSaga",
                status=SagaStatus.FAILED,
                steps=[],
                context={},
                metadata={},
            )

            # List all
            all_sagas = await storage.list_sagas()
            assert len(all_sagas) >= 2

            # Filter by status
            completed = await storage.list_sagas(status=SagaStatus.COMPLETED)
            assert len(completed) >= 1
            assert completed[0]["status"] == "completed"

            # Filter by name
            test_sagas = await storage.list_sagas(saga_name="TestSaga")
            assert len(test_sagas) >= 2

    @pytest.mark.asyncio
    async def test_update_step_state(self, postgres_container):
        """Test updating step state"""
        from sagaz.storage.postgresql import PostgreSQLSagaStorage

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create saga with pending step
            await storage.save_saga_state(
                saga_id="step-update",
                saga_name="StepTest",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending", "result": None}],
                context={},
                metadata={},
            )

            # Update step
            await storage.update_step_state(
                saga_id="step-update",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"data": "success"},
                error=None,
            )

            # Check update
            state = await storage.load_saga_state("step-update")
            step = state["steps"][0]
            assert step["status"] == "completed"
            assert step["result"]["data"] == "success"

    @pytest.mark.asyncio
    async def test_connection_error(self):
        """Test connection failure raises SagaStorageError"""
        from sagaz.storage.postgresql import PostgreSQLSagaStorage

        # Use invalid port
        storage = PostgreSQLSagaStorage("postgresql://user:pass@localhost:9999/db")

        with pytest.raises(SagaStorageError):
            async with storage:
                pass
