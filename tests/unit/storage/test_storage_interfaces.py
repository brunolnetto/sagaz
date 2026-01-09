"""
Tests for sagaz.storage.interfaces module.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timezone
from typing import Any

import pytest

from sagaz.outbox.types import OutboxEvent, OutboxStatus
from sagaz.storage.interfaces import (
    OutboxStorage,
    OutboxStorageError,
    SagaStepState,
    SagaStorage,
    Transferable,
)
from sagaz.core.types import SagaStatus, SagaStepStatus


class TestSagaStorageInterface:
    """Tests for SagaStorage abstract base class."""

    def test_saga_storage_is_abstract(self):
        """Test that SagaStorage cannot be instantiated directly."""
        with pytest.raises(TypeError):
            SagaStorage()

    def test_concrete_saga_storage(self):
        """Test a minimal concrete implementation."""
        class MinimalSagaStorage(SagaStorage):
            async def save_saga_state(self, saga_id, saga_name, status, steps, context, metadata=None):
                pass

            async def load_saga_state(self, saga_id):
                return None

            async def delete_saga_state(self, saga_id):
                return False

            async def list_sagas(self, status=None, saga_name=None, limit=100, offset=0):
                return []

            async def update_step_state(self, saga_id, step_name, status, result=None, error=None, executed_at=None):
                pass

            async def get_saga_statistics(self):
                return {}

            async def cleanup_completed_sagas(self, older_than, statuses=None):
                return 0

            async def health_check(self):
                return {"status": "healthy"}

        storage = MinimalSagaStorage()
        assert storage is not None

    @pytest.mark.asyncio
    async def test_export_all_not_implemented(self):
        """Test export_all raises NotImplementedError by default."""
        class MinimalSagaStorage(SagaStorage):
            async def save_saga_state(self, *args, **kwargs): pass
            async def load_saga_state(self, saga_id): return None
            async def delete_saga_state(self, saga_id): return False
            async def list_sagas(self, **kwargs): return []
            async def update_step_state(self, *args, **kwargs): pass
            async def get_saga_statistics(self): return {}
            async def cleanup_completed_sagas(self, *args, **kwargs): return 0
            async def health_check(self): return {}

        storage = MinimalSagaStorage()

        with pytest.raises(NotImplementedError):
            async for _ in storage.export_all():
                pass

    @pytest.mark.asyncio
    async def test_import_record_not_implemented(self):
        """Test import_record raises NotImplementedError by default."""
        class MinimalSagaStorage(SagaStorage):
            async def save_saga_state(self, *args, **kwargs): pass
            async def load_saga_state(self, saga_id): return None
            async def delete_saga_state(self, saga_id): return False
            async def list_sagas(self, **kwargs): return []
            async def update_step_state(self, *args, **kwargs): pass
            async def get_saga_statistics(self): return {}
            async def cleanup_completed_sagas(self, *args, **kwargs): return 0
            async def health_check(self): return {}

        storage = MinimalSagaStorage()

        with pytest.raises(NotImplementedError):
            await storage.import_record({"saga_id": "test"})

    @pytest.mark.asyncio
    async def test_count_default_uses_list_sagas(self):
        """Test count uses list_sagas by default."""
        class CountingSagaStorage(SagaStorage):
            async def save_saga_state(self, *args, **kwargs): pass
            async def load_saga_state(self, saga_id): return None
            async def delete_saga_state(self, saga_id): return False
            async def list_sagas(self, **kwargs):
                return [{"id": "1"}, {"id": "2"}, {"id": "3"}]
            async def update_step_state(self, *args, **kwargs): pass
            async def get_saga_statistics(self): return {}
            async def cleanup_completed_sagas(self, *args, **kwargs): return 0
            async def health_check(self): return {}

        storage = CountingSagaStorage()
        count = await storage.count()

        assert count == 3

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test context manager support."""
        class MinimalSagaStorage(SagaStorage):
            async def save_saga_state(self, *args, **kwargs): pass
            async def load_saga_state(self, saga_id): return None
            async def delete_saga_state(self, saga_id): return False
            async def list_sagas(self, **kwargs): return []
            async def update_step_state(self, *args, **kwargs): pass
            async def get_saga_statistics(self): return {}
            async def cleanup_completed_sagas(self, *args, **kwargs): return 0
            async def health_check(self): return {}

        async with MinimalSagaStorage() as storage:
            assert storage is not None

    @pytest.mark.asyncio
    async def test_close_default(self):
        """Test close does nothing by default."""
        class MinimalSagaStorage(SagaStorage):
            async def save_saga_state(self, *args, **kwargs): pass
            async def load_saga_state(self, saga_id): return None
            async def delete_saga_state(self, saga_id): return False
            async def list_sagas(self, **kwargs): return []
            async def update_step_state(self, *args, **kwargs): pass
            async def get_saga_statistics(self): return {}
            async def cleanup_completed_sagas(self, *args, **kwargs): return 0
            async def health_check(self): return {}

        storage = MinimalSagaStorage()
        await storage.close()  # Should not raise


class TestSagaStepState:
    """Tests for SagaStepState helper class."""

    def test_creation(self):
        """Test creating a SagaStepState."""
        state = SagaStepState(
            name="reserve_inventory",
            status=SagaStepStatus.COMPLETED,
            result={"items": 5},
        )

        assert state.name == "reserve_inventory"
        assert state.status == SagaStepStatus.COMPLETED
        assert state.result == {"items": 5}

    def test_to_dict(self):
        """Test converting to dictionary."""
        now = datetime.now(UTC)

        state = SagaStepState(
            name="charge_payment",
            status=SagaStepStatus.COMPLETED,
            result={"amount": 99.99},
            executed_at=now,
            retry_count=2,
        )

        data = state.to_dict()

        assert data["name"] == "charge_payment"
        assert data["status"] == "completed"
        assert data["result"] == {"amount": 99.99}
        assert data["retry_count"] == 2
        assert data["executed_at"] == now.isoformat()

    def test_to_dict_with_nulls(self):
        """Test to_dict handles None values."""
        state = SagaStepState(
            name="test",
            status=SagaStepStatus.PENDING,
        )

        data = state.to_dict()

        assert data["result"] is None
        assert data["error"] is None
        assert data["executed_at"] is None
        assert data["compensated_at"] is None

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "name": "process_order",
            "status": "completed",
            "result": {"order_id": "123"},
            "error": None,
            "executed_at": "2024-01-15T10:30:00+00:00",
            "compensated_at": None,
            "retry_count": 0,
        }

        state = SagaStepState.from_dict(data)

        assert state.name == "process_order"
        assert state.status == SagaStepStatus.COMPLETED
        assert state.result == {"order_id": "123"}
        assert state.executed_at is not None

    def test_from_dict_minimal(self):
        """Test from_dict with minimal data."""
        data = {
            "name": "test",
            "status": "pending",
        }

        state = SagaStepState.from_dict(data)

        assert state.name == "test"
        assert state.status == SagaStepStatus.PENDING
        assert state.retry_count == 0

    def test_from_dict_with_compensated_at(self):
        """Test from_dict with compensated_at."""
        data = {
            "name": "test",
            "status": "compensated",
            "compensated_at": "2024-01-15T11:00:00+00:00",
        }

        state = SagaStepState.from_dict(data)

        assert state.compensated_at is not None


class TestOutboxStorageInterface:
    """Tests for OutboxStorage abstract base class."""

    def test_outbox_storage_is_abstract(self):
        """Test that OutboxStorage cannot be instantiated directly."""
        with pytest.raises(TypeError):
            OutboxStorage()

    def test_concrete_outbox_storage(self):
        """Test a minimal concrete implementation."""
        class MinimalOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None):
                return event

            async def get_by_id(self, event_id):
                return None

            async def update_status(self, event_id, status, error_message=None, connection=None):
                return OutboxEvent(saga_id="test", event_type="test", payload={})

            async def claim_batch(self, worker_id, batch_size=100, older_than_seconds=0.0):
                return []

            async def get_events_by_saga(self, saga_id):
                return []

            async def get_stuck_events(self, claimed_older_than_seconds=300.0):
                return []

            async def release_stuck_events(self, claimed_older_than_seconds=300.0):
                return 0

            async def get_pending_count(self):
                return 0

            async def get_dead_letter_events(self, limit=100):
                return []

        storage = MinimalOutboxStorage()
        assert storage is not None

    @pytest.mark.asyncio
    async def test_health_check_default(self):
        """Test default health_check implementation."""
        class MinimalOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None): return event
            async def get_by_id(self, event_id): return None
            async def update_status(self, *args, **kwargs):
                return OutboxEvent(saga_id="test", event_type="test", payload={})
            async def claim_batch(self, *args, **kwargs): return []
            async def get_events_by_saga(self, saga_id): return []
            async def get_stuck_events(self, *args): return []
            async def release_stuck_events(self, *args): return 0
            async def get_pending_count(self): return 5
            async def get_dead_letter_events(self, *args): return []

        storage = MinimalOutboxStorage()
        result = await storage.health_check()

        assert result.is_healthy
        assert result.details["pending_count"] == 5

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        """Test health_check handles exception."""
        class FailingOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None): return event
            async def get_by_id(self, event_id): return None
            async def update_status(self, *args, **kwargs):
                return OutboxEvent(saga_id="test", event_type="test", payload={})
            async def claim_batch(self, *args, **kwargs): return []
            async def get_events_by_saga(self, saga_id): return []
            async def get_stuck_events(self, *args): return []
            async def release_stuck_events(self, *args): return 0
            async def get_pending_count(self): raise Exception("DB error")
            async def get_dead_letter_events(self, *args): return []

        storage = FailingOutboxStorage()
        result = await storage.health_check()

        assert not result.is_healthy
        assert "DB error" in result.message

    @pytest.mark.asyncio
    async def test_get_statistics_default(self):
        """Test default get_statistics implementation."""
        class MinimalOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None): return event
            async def get_by_id(self, event_id): return None
            async def update_status(self, *args, **kwargs):
                return OutboxEvent(saga_id="test", event_type="test", payload={})
            async def claim_batch(self, *args, **kwargs): return []
            async def get_events_by_saga(self, saga_id): return []
            async def get_stuck_events(self, *args): return []
            async def release_stuck_events(self, *args): return 0
            async def get_pending_count(self): return 10
            async def get_dead_letter_events(self, *args): return []

        storage = MinimalOutboxStorage()
        stats = await storage.get_statistics()

        assert stats.pending_records == 10

    @pytest.mark.asyncio
    async def test_export_all_not_implemented(self):
        """Test export_all raises NotImplementedError."""
        class MinimalOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None): return event
            async def get_by_id(self, event_id): return None
            async def update_status(self, *args, **kwargs):
                return OutboxEvent(saga_id="test", event_type="test", payload={})
            async def claim_batch(self, *args, **kwargs): return []
            async def get_events_by_saga(self, saga_id): return []
            async def get_stuck_events(self, *args): return []
            async def release_stuck_events(self, *args): return 0
            async def get_pending_count(self): return 0
            async def get_dead_letter_events(self, *args): return []

        storage = MinimalOutboxStorage()

        with pytest.raises(NotImplementedError):
            async for _ in storage.export_all():
                pass

    @pytest.mark.asyncio
    async def test_import_record_not_implemented(self):
        """Test import_record raises NotImplementedError."""
        class MinimalOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None): return event
            async def get_by_id(self, event_id): return None
            async def update_status(self, *args, **kwargs):
                return OutboxEvent(saga_id="test", event_type="test", payload={})
            async def claim_batch(self, *args, **kwargs): return []
            async def get_events_by_saga(self, saga_id): return []
            async def get_stuck_events(self, *args): return []
            async def release_stuck_events(self, *args): return 0
            async def get_pending_count(self): return 0
            async def get_dead_letter_events(self, *args): return []

        storage = MinimalOutboxStorage()

        with pytest.raises(NotImplementedError):
            await storage.import_record({})

    @pytest.mark.asyncio
    async def test_count_default(self):
        """Test count uses get_pending_count by default."""
        class MinimalOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None): return event
            async def get_by_id(self, event_id): return None
            async def update_status(self, *args, **kwargs):
                return OutboxEvent(saga_id="test", event_type="test", payload={})
            async def claim_batch(self, *args, **kwargs): return []
            async def get_events_by_saga(self, saga_id): return []
            async def get_stuck_events(self, *args): return []
            async def release_stuck_events(self, *args): return 0
            async def get_pending_count(self): return 42
            async def get_dead_letter_events(self, *args): return []

        storage = MinimalOutboxStorage()
        count = await storage.count()

        assert count == 42

    @pytest.mark.asyncio
    async def test_archive_events_not_implemented(self):
        """Test archive_events raises NotImplementedError."""
        class MinimalOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None): return event
            async def get_by_id(self, event_id): return None
            async def update_status(self, *args, **kwargs):
                return OutboxEvent(saga_id="test", event_type="test", payload={})
            async def claim_batch(self, *args, **kwargs): return []
            async def get_events_by_saga(self, saga_id): return []
            async def get_stuck_events(self, *args): return []
            async def release_stuck_events(self, *args): return 0
            async def get_pending_count(self): return 0
            async def get_dead_letter_events(self, *args): return []

        storage = MinimalOutboxStorage()

        with pytest.raises(NotImplementedError):
            await storage.archive_events()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test context manager support."""
        class MinimalOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None): return event
            async def get_by_id(self, event_id): return None
            async def update_status(self, *args, **kwargs):
                return OutboxEvent(saga_id="test", event_type="test", payload={})
            async def claim_batch(self, *args, **kwargs): return []
            async def get_events_by_saga(self, saga_id): return []
            async def get_stuck_events(self, *args): return []
            async def release_stuck_events(self, *args): return 0
            async def get_pending_count(self): return 0
            async def get_dead_letter_events(self, *args): return []

        async with MinimalOutboxStorage() as storage:
            assert storage is not None

    @pytest.mark.asyncio
    async def test_close_default(self):
        """Test close does nothing by default."""
        class MinimalOutboxStorage(OutboxStorage):
            async def insert(self, event, connection=None): return event
            async def get_by_id(self, event_id): return None
            async def update_status(self, *args, **kwargs):
                return OutboxEvent(saga_id="test", event_type="test", payload={})
            async def claim_batch(self, *args, **kwargs): return []
            async def get_events_by_saga(self, saga_id): return []
            async def get_stuck_events(self, *args): return []
            async def release_stuck_events(self, *args): return 0
            async def get_pending_count(self): return 0
            async def get_dead_letter_events(self, *args): return []

        storage = MinimalOutboxStorage()
        await storage.close()  # Should not raise


class TestOutboxStorageError:
    """Tests for OutboxStorageError exception."""

    def test_outbox_storage_error(self):
        """Test OutboxStorageError."""
        error = OutboxStorageError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)


class TestTransferableProtocol:
    """Tests for Transferable protocol."""

    def test_transferable_protocol_check(self):
        """Test that Transferable is a runtime checkable protocol."""
        class ImplementsTransferable:
            async def export_all(self):
                yield {}

            async def import_record(self, record):
                pass

            async def count(self):
                return 0

        obj = ImplementsTransferable()
        assert isinstance(obj, Transferable)

    def test_non_transferable_fails_check(self):
        """Test that non-conforming class fails protocol check."""
        class NotTransferable:
            pass

        obj = NotTransferable()
        assert not isinstance(obj, Transferable)
