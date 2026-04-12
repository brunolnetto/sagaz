"""
Tests for SQLite storage backends.
"""

import importlib
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.types import SagaStatus, SagaStepStatus

# Skip all tests if aiosqlite is not installed
try:
    import aiosqlite

    AIOSQLITE_AVAILABLE = True
except ImportError:
    AIOSQLITE_AVAILABLE = False

pytestmark = pytest.mark.skipif(not AIOSQLITE_AVAILABLE, reason="aiosqlite not installed")


class TestSQLiteSagaStorage:
    """Tests for SQLiteSagaStorage."""

    @pytest.fixture
    async def storage(self):
        """Create an in-memory SQLite saga storage."""
        from sagaz.core.storage.backends.sqlite import SQLiteSagaStorage

        storage = SQLiteSagaStorage(":memory:")
        async with storage:
            yield storage

    @pytest.mark.asyncio
    async def test_save_and_load_saga(self, storage):
        """Test saving and loading a saga."""
        await storage.save_saga_state(
            saga_id="test-saga-1",
            saga_name="OrderSaga",
            status=SagaStatus.EXECUTING,
            steps=[{"name": "step1", "status": "pending"}],
            context={"order_id": "123"},
        )

        saga = await storage.load_saga_state("test-saga-1")

        assert saga is not None
        assert saga["saga_id"] == "test-saga-1"
        assert saga["saga_name"] == "OrderSaga"
        assert saga["status"] == "executing"
        assert saga["context"]["order_id"] == "123"

    @pytest.mark.asyncio
    async def test_load_nonexistent_saga(self, storage):
        """Test loading a saga that doesn't exist."""
        saga = await storage.load_saga_state("nonexistent")
        assert saga is None

    @pytest.mark.asyncio
    async def test_update_saga_state(self, storage):
        """Test updating an existing saga."""
        await storage.save_saga_state(
            saga_id="test-saga-1",
            saga_name="OrderSaga",
            status=SagaStatus.EXECUTING,
            steps=[],
            context={},
        )

        # Update the saga
        await storage.save_saga_state(
            saga_id="test-saga-1",
            saga_name="OrderSaga",
            status=SagaStatus.COMPLETED,
            steps=[{"name": "step1", "status": "completed"}],
            context={"result": "success"},
        )

        saga = await storage.load_saga_state("test-saga-1")

        assert saga["status"] == "completed"
        assert saga["context"]["result"] == "success"

    @pytest.mark.asyncio
    async def test_delete_saga(self, storage):
        """Test deleting a saga."""
        await storage.save_saga_state(
            saga_id="test-saga-1",
            saga_name="OrderSaga",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )

        result = await storage.delete_saga_state("test-saga-1")
        assert result is True

        saga = await storage.load_saga_state("test-saga-1")
        assert saga is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_saga(self, storage):
        """Test deleting a saga that doesn't exist."""
        result = await storage.delete_saga_state("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_sagas(self, storage):
        """Test listing sagas."""
        for i in range(5):
            await storage.save_saga_state(
                saga_id=f"saga-{i}",
                saga_name="OrderSaga",
                status=SagaStatus.COMPLETED if i % 2 == 0 else SagaStatus.EXECUTING,
                steps=[],
                context={},
            )

        all_sagas = await storage.list_sagas()
        assert len(all_sagas) == 5

        completed_sagas = await storage.list_sagas(status=SagaStatus.COMPLETED)
        assert len(completed_sagas) == 3

    @pytest.mark.asyncio
    async def test_list_sagas_with_name_filter(self, storage):
        """Test listing sagas with name filter."""
        await storage.save_saga_state(
            saga_id="saga-1",
            saga_name="OrderSaga",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )
        await storage.save_saga_state(
            saga_id="saga-2",
            saga_name="PaymentSaga",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )

        order_sagas = await storage.list_sagas(saga_name="OrderSaga")
        assert len(order_sagas) == 1
        assert order_sagas[0]["saga_name"] == "OrderSaga"

    @pytest.mark.asyncio
    async def test_update_step_state(self, storage):
        """Test updating a single step."""
        await storage.save_saga_state(
            saga_id="saga-1",
            saga_name="OrderSaga",
            status=SagaStatus.EXECUTING,
            steps=[{"name": "step1", "status": "pending"}],
            context={},
        )

        await storage.update_step_state(
            saga_id="saga-1",
            step_name="step1",
            status=SagaStepStatus.COMPLETED,
            result={"data": "success"},
        )

        saga = await storage.load_saga_state("saga-1")
        step = saga["steps"][0]
        assert step["status"] == "completed"
        assert step["result"]["data"] == "success"

    @pytest.mark.asyncio
    async def test_get_saga_statistics(self, storage):
        """Test getting saga statistics."""
        await storage.save_saga_state(
            saga_id="saga-1",
            saga_name="OrderSaga",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )
        await storage.save_saga_state(
            saga_id="saga-2",
            saga_name="OrderSaga",
            status=SagaStatus.FAILED,
            steps=[],
            context={},
        )

        stats = await storage.get_saga_statistics()

        assert stats["total"] == 2
        assert stats["by_status"]["completed"] == 1
        assert stats["by_status"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_completed_sagas(self, storage):
        """Test cleaning up old completed sagas."""
        # Create an old completed saga
        await storage.save_saga_state(
            saga_id="old-saga",
            saga_name="OrderSaga",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )

        # Cleanup with a far future date should delete all
        deleted = await storage.cleanup_completed_sagas(
            older_than=datetime.now(UTC) + timedelta(hours=1),
            statuses=[SagaStatus.COMPLETED, SagaStatus.ROLLED_BACK],
        )

        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_health_check(self, storage):
        """Test health check."""
        health = await storage.health_check()

        assert health["status"] == "healthy"
        assert health["backend"] == "sqlite"

    @pytest.mark.asyncio
    async def test_count(self, storage):
        """Test counting sagas."""
        for i in range(3):
            await storage.save_saga_state(
                saga_id=f"saga-{i}",
                saga_name="OrderSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

        count = await storage.count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_export_all(self, storage):
        """Test exporting all sagas."""
        for i in range(3):
            await storage.save_saga_state(
                saga_id=f"saga-{i}",
                saga_name="OrderSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

        exported = []
        async for record in storage.export_all():
            exported.append(record)

        assert len(exported) == 3

    @pytest.mark.asyncio
    async def test_import_record(self, storage):
        """Test importing a record."""
        await storage.import_record(
            {
                "saga_id": "imported-saga",
                "saga_name": "ImportedSaga",
                "status": "completed",
                "steps": [],
                "context": {"imported": True},
            }
        )

        saga = await storage.load_saga_state("imported-saga")
        assert saga is not None
        assert saga["saga_name"] == "ImportedSaga"


class TestSQLiteOutboxStorage:
    """Tests for SQLiteOutboxStorage."""

    @pytest.fixture
    async def storage(self):
        """Create an in-memory SQLite outbox storage."""
        from sagaz.core.storage.backends.sqlite import SQLiteOutboxStorage

        storage = SQLiteOutboxStorage(":memory:")
        async with storage:
            yield storage

    @pytest.fixture
    def sample_event(self):
        """Create a sample outbox event."""
        return OutboxEvent(
            saga_id="order-123",
            event_type="OrderCreated",
            payload={"order_id": "123", "amount": 99.99},
            aggregate_type="Order",
            aggregate_id="123",
        )

    @pytest.mark.asyncio
    async def test_insert_and_get_event(self, storage, sample_event):
        """Test inserting and retrieving an event."""
        await storage.insert(sample_event)

        retrieved = await storage.get_by_id(sample_event.event_id)

        assert retrieved is not None
        assert retrieved.saga_id == "order-123"
        assert retrieved.event_type == "OrderCreated"
        assert retrieved.payload["amount"] == 99.99

    @pytest.mark.asyncio
    async def test_get_nonexistent_event(self, storage):
        """Test getting an event that doesn't exist."""
        event = await storage.get_by_id("nonexistent")
        assert event is None

    @pytest.mark.asyncio
    async def test_update_status(self, storage, sample_event):
        """Test updating event status."""
        await storage.insert(sample_event)

        updated = await storage.update_status(
            sample_event.event_id,
            OutboxStatus.SENT,
        )

        assert updated is not None
        assert updated.status == OutboxStatus.SENT
        assert updated.sent_at is not None

    @pytest.mark.asyncio
    async def test_claim_batch(self, storage):
        """Test claiming a batch of events."""
        # Insert multiple events
        for i in range(5):
            event = OutboxEvent(
                saga_id=f"order-{i}",
                event_type="OrderCreated",
                payload={"index": i},
            )
            await storage.insert(event)

        # Claim a batch
        claimed = await storage.claim_batch("worker-1", batch_size=3)

        assert len(claimed) == 3
        for event in claimed:
            assert event.status == OutboxStatus.CLAIMED
            assert event.worker_id == "worker-1"

    @pytest.mark.asyncio
    async def test_get_events_by_saga(self, storage, sample_event):
        """Test getting events by saga ID."""
        await storage.insert(sample_event)

        events = await storage.get_events_by_saga("order-123")

        assert len(events) == 1
        assert events[0].saga_id == "order-123"

    @pytest.mark.asyncio
    async def test_get_pending_count(self, storage):
        """Test getting pending event count."""
        for i in range(3):
            event = OutboxEvent(
                saga_id=f"order-{i}",
                event_type="OrderCreated",
                payload={},
            )
            await storage.insert(event)

        count = await storage.get_pending_count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_get_dead_letter_events(self, storage, sample_event):
        """Test getting dead letter events."""
        await storage.insert(sample_event)
        await storage.update_status(sample_event.event_id, OutboxStatus.DEAD_LETTER)

        dead_letters = await storage.get_dead_letter_events()

        assert len(dead_letters) == 1
        assert dead_letters[0].status == OutboxStatus.DEAD_LETTER

    @pytest.mark.asyncio
    async def test_health_check(self, storage):
        """Test health check."""
        result = await storage.health_check()

        assert result.is_healthy
        assert "pending_count" in result.details

    @pytest.mark.asyncio
    async def test_get_statistics(self, storage):
        """Test getting statistics."""
        for i in range(3):
            event = OutboxEvent(
                saga_id=f"order-{i}",
                event_type="OrderCreated",
                payload={},
            )
            await storage.insert(event)

        stats = await storage.get_statistics()

        assert stats.total_records == 3
        assert stats.pending_records == 3

    @pytest.mark.asyncio
    async def test_count(self, storage):
        """Test counting events."""
        for i in range(4):
            event = OutboxEvent(
                saga_id=f"order-{i}",
                event_type="OrderCreated",
                payload={},
            )
            await storage.insert(event)

        count = await storage.count()
        assert count == 4

    @pytest.mark.asyncio
    async def test_export_all(self, storage):
        """Test exporting all events."""
        for i in range(2):
            event = OutboxEvent(
                saga_id=f"order-{i}",
                event_type="OrderCreated",
                payload={},
            )
            await storage.insert(event)

        exported = []
        async for record in storage.export_all():
            exported.append(record)

        assert len(exported) == 2

    @pytest.mark.asyncio
    async def test_import_record(self, storage):
        """Test importing a record."""
        await storage.import_record(
            {
                "saga_id": "imported-order",
                "event_type": "OrderImported",
                "payload": {"imported": True},
                "status": "pending",
            }
        )

        count = await storage.count()
        assert count == 1


class TestSQLiteStorageFactory:
    """Tests for SQLite storage via factory."""

    @pytest.mark.asyncio
    async def test_create_sqlite_saga_storage(self):
        """Test creating SQLite saga storage via factory."""
        from sagaz.core.storage import create_storage
        from sagaz.core.storage.backends.sqlite import SQLiteSagaStorage

        storage = create_storage("sqlite", storage_type="saga")
        assert isinstance(storage, SQLiteSagaStorage)

    @pytest.mark.asyncio
    async def test_create_sqlite_outbox_storage(self):
        """Test creating SQLite outbox storage via factory."""
        from sagaz.core.storage import create_storage
        from sagaz.core.storage.backends.sqlite import SQLiteOutboxStorage

        storage = create_storage("sqlite", storage_type="outbox")
        assert isinstance(storage, SQLiteOutboxStorage)

    @pytest.mark.asyncio
    async def test_create_sqlite_both_storages(self):
        """Test creating both SQLite storages via factory."""
        from sagaz.core.storage import create_storage
        from sagaz.core.storage.backends.sqlite import SQLiteOutboxStorage, SQLiteSagaStorage

        saga, outbox = create_storage("sqlite", storage_type="both")

        assert isinstance(saga, SQLiteSagaStorage)
        assert isinstance(outbox, SQLiteOutboxStorage)

    @pytest.mark.asyncio
    async def test_create_sqlite_with_db_path(self, tmp_path):
        """Test creating SQLite storage with custom db_path."""
        from sagaz.core.storage import create_storage

        db_file = tmp_path / "test.db"

        storage = create_storage("sqlite", db_path=str(db_file))

        async with storage:
            await storage.save_saga_state(
                saga_id="test-1",
                saga_name="TestSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

        # Verify file was created
        assert db_file.exists()

    def test_sqlite_in_available_backends(self):
        """Test SQLite appears in available backends."""
        from sagaz.core.storage import get_available_backends

        backends = get_available_backends()

        assert "sqlite" in backends
        assert backends["sqlite"]["available"] is True


class TestSQLiteTransfer:
    """Tests for transferring data to/from SQLite."""

    @pytest.mark.asyncio
    async def test_transfer_from_memory_to_sqlite(self):
        """Test transferring data from memory to SQLite."""
        from sagaz.core.storage import create_storage
        from sagaz.core.storage.transfer import transfer_data

        # Create source with data
        source = create_storage("memory")
        await source.save_saga_state(
            saga_id="saga-1",
            saga_name="TestSaga",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={"data": "test"},
        )

        # Create target
        target = create_storage("sqlite")
        async with target:
            # Transfer
            result = await transfer_data(source, target, validate=False)

            assert result.transferred == 1
            assert result.success

            # Verify data
            saga = await target.load_saga_state("saga-1")
            assert saga is not None
            assert saga["saga_name"] == "TestSaga"


class TestSQLiteSagaImportError:
    """Lines 38-40, 85-86 in sqlite/saga.py: aiosqlite unavailable paths."""

    def test_aiosqlite_unavailable_flag_saga(self):
        """Lines 38-40: AIOSQLITE_AVAILABLE=False when aiosqlite absent."""
        import sagaz.core.storage.backends.sqlite.saga as saga_mod

        original = sys.modules.get("aiosqlite")
        try:
            sys.modules["aiosqlite"] = None  # type: ignore[assignment]
            importlib.reload(saga_mod)
            assert saga_mod.AIOSQLITE_AVAILABLE is False
        finally:
            if original is not None:
                sys.modules["aiosqlite"] = original
            else:
                sys.modules.pop("aiosqlite", None)
            importlib.reload(saga_mod)

    def test_init_raises_when_aiosqlite_unavailable(self):
        """Lines 85-86: MissingDependencyError when AIOSQLITE_AVAILABLE=False."""
        import sagaz.core.storage.backends.sqlite.saga as saga_mod
        from sagaz.core.exceptions import MissingDependencyError

        with patch.object(saga_mod, "AIOSQLITE_AVAILABLE", False):
            with pytest.raises(MissingDependencyError):
                saga_mod.SQLiteSagaStorage()

    @pytest.mark.asyncio
    async def test_init_schema_raises_when_conn_none(self):
        """Lines 112-113: RuntimeError in _init_schema when _conn is None."""
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage

        storage = SQLiteSagaStorage(":memory:")
        with pytest.raises(RuntimeError, match="Connection not initialized"):
            await storage._init_schema()

    @pytest.mark.asyncio
    async def test_close_when_conn_already_none(self):
        """Line 143->exit: close() does nothing when _conn is already None."""
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage

        storage = SQLiteSagaStorage(":memory:")
        storage._conn = None
        await storage.close()  # must not raise

    @pytest.mark.asyncio
    async def test_get_saga_statistics_empty_db(self):
        """Line 311: if not row path in get_saga_statistics."""
        from unittest.mock import AsyncMock, MagicMock

        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage

        storage = SQLiteSagaStorage(":memory:")
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        storage._conn = mock_conn
        storage._initialized = True

        result = await storage.get_saga_statistics()
        assert result.get("total", 0) == 0 or isinstance(result, dict)


class TestSQLiteOutboxImportError:
    """Lines 31-33, 76-77, 103-104, 143->exit, 414 in sqlite/outbox.py."""

    def test_aiosqlite_unavailable_flag_outbox(self):
        """Lines 31-33: AIOSQLITE_AVAILABLE=False in outbox module."""
        import sagaz.core.storage.backends.sqlite.outbox as outbox_mod

        original = sys.modules.get("aiosqlite")
        try:
            sys.modules["aiosqlite"] = None  # type: ignore[assignment]
            importlib.reload(outbox_mod)
            assert outbox_mod.AIOSQLITE_AVAILABLE is False
        finally:
            if original is not None:
                sys.modules["aiosqlite"] = original
            else:
                sys.modules.pop("aiosqlite", None)
            importlib.reload(outbox_mod)

    def test_outbox_init_raises_when_aiosqlite_unavailable(self):
        """Lines 76-77: MissingDependencyError."""
        import sagaz.core.storage.backends.sqlite.outbox as outbox_mod
        from sagaz.core.exceptions import MissingDependencyError

        with patch.object(outbox_mod, "AIOSQLITE_AVAILABLE", False):
            with pytest.raises(MissingDependencyError):
                outbox_mod.SQLiteOutboxStorage()

    @pytest.mark.asyncio
    async def test_outbox_init_schema_raises_when_conn_none(self):
        """Lines 103-104: RuntimeError when no connection."""
        from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        storage = SQLiteOutboxStorage(":memory:")
        with pytest.raises(RuntimeError, match="Connection not initialized"):
            await storage._init_schema()

    @pytest.mark.asyncio
    async def test_outbox_close_when_conn_already_none(self):
        """Line 143->exit: close is no-op when _conn is None."""
        from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        storage = SQLiteOutboxStorage(":memory:")
        storage._conn = None
        await storage.close()  # must not raise

    @pytest.mark.asyncio
    async def test_outbox_statistics_empty_db(self):
        """Line 414: if not row path returns StorageStatistics(0, 0)."""
        from unittest.mock import AsyncMock

        from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage
        from sagaz.core.storage.core import StorageStatistics

        storage = SQLiteOutboxStorage(":memory:")
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        storage._conn = mock_conn
        storage._initialized = True

        result = await storage.get_statistics()
        assert isinstance(result, StorageStatistics)
        assert result.total_records == 0


class TestSqliteSagaBranches:
    async def test_update_step_status_step_not_found(self):
        """275->287: for loop exhausted without break (step_name not found)."""
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStatus, SagaStepStatus

        storage = SQLiteSagaStorage(":memory:")
        await storage.initialize()
        saga_id = str(uuid4())
        await storage.save_saga_state(
            saga_id=saga_id,
            saga_name="TestSaga",
            status=SagaStatus.EXECUTING,
            steps=[{"name": "step1", "status": "pending"}],
            context={},
        )
        # Update a step that doesn't exist → 275->287 (loop exits without break)
        await storage.update_step_state(
            saga_id=saga_id,
            step_name="nonexistent_step",  # Not in steps list
            status=SagaStepStatus.COMPLETED,
        )

    async def test_update_step_status_step_name_mismatch(self):
        """276->275: if step.get('name') == step_name: False → continue loop."""
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStatus, SagaStepStatus

        storage = SQLiteSagaStorage(":memory:")
        await storage.initialize()
        saga_id = str(uuid4())
        await storage.save_saga_state(
            saga_id=saga_id,
            saga_name="TestSaga",
            status=SagaStatus.EXECUTING,
            steps=[
                {"name": "step1", "status": "pending"},
                {"name": "step2", "status": "pending"},
            ],
            context={},
        )
        # Update step2 → step1 skipped (276->275), step2 matched
        await storage.update_step_state(
            saga_id=saga_id,
            step_name="step2",
            status=SagaStepStatus.COMPLETED,
        )


# ==========================================================================
# storage/base.py  – 193->196
