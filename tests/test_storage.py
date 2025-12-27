"""
Tests for storage backends - memory
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from sagaz.storage.base import SagaStepState, SagaStorageError
from sagaz.storage.memory import InMemorySagaStorage
from sagaz.types import SagaStatus, SagaStepStatus


class TestSagaStepState:
    """Test SagaStepState data class"""

    def test_step_state_creation(self):
        """Test SagaStepState can be created"""
        step = SagaStepState(
            name="test-step",
            status=SagaStepStatus.COMPLETED,
            result={"data": "value"},
            error=None,
            executed_at=datetime.now(),
            compensated_at=None,
            retry_count=0,
        )

        assert step.name == "test-step"
        assert step.status == SagaStepStatus.COMPLETED
        assert step.result == {"data": "value"}
        assert step.error is None
        assert step.retry_count == 0

    def test_step_state_to_dict(self):
        """Test converting SagaStepState to dict"""
        now = datetime.now()
        step = SagaStepState(
            name="dict-step",
            status=SagaStepStatus.FAILED,
            result=None,
            error="Test error",
            executed_at=now,
            compensated_at=now,
            retry_count=2,
        )

        step_dict = step.to_dict()

        assert step_dict["name"] == "dict-step"
        assert step_dict["status"] == "failed"
        assert step_dict["result"] is None
        assert step_dict["error"] == "Test error"
        assert step_dict["executed_at"] == now.isoformat()
        assert step_dict["compensated_at"] == now.isoformat()
        assert step_dict["retry_count"] == 2

    def test_step_state_from_dict(self):
        """Test creating SagaStepState from dict"""
        now = datetime.now()
        step_dict = {
            "name": "from-dict-step",
            "status": "completed",
            "result": {"key": "value"},
            "error": None,
            "executed_at": now.isoformat(),
            "compensated_at": None,
            "retry_count": 1,
        }

        step = SagaStepState.from_dict(step_dict)

        assert step.name == "from-dict-step"
        assert step.status == SagaStepStatus.COMPLETED
        assert step.result == {"key": "value"}
        assert step.error is None
        assert step.executed_at == now
        assert step.compensated_at is None
        assert step.retry_count == 1

    def test_step_state_roundtrip(self):
        """Test to_dict and from_dict roundtrip"""
        original = SagaStepState(
            name="roundtrip-step",
            status=SagaStepStatus.COMPENSATED,
            result={"data": "test"},
            error=None,
            executed_at=datetime.now(),
            compensated_at=datetime.now(),
            retry_count=3,
        )

        # Convert to dict and back
        step_dict = original.to_dict()
        restored = SagaStepState.from_dict(step_dict)

        assert restored.name == original.name
        assert restored.status == original.status
        assert restored.result == original.result
        assert restored.error == original.error
        assert restored.retry_count == original.retry_count


class TestInMemorySagaStorage:
    """Tests for InMemorySagaStorage implementation"""

    @pytest.mark.asyncio
    async def test_save_and_load_saga_state(self):
        """Test saving and loading saga state"""
        storage = InMemorySagaStorage()

        saga_id = "test-saga-123"
        saga_name = "TestSaga"
        status = SagaStatus.COMPLETED
        steps = [
            {"name": "step1", "status": SagaStepStatus.COMPLETED.value},
            {"name": "step2", "status": SagaStepStatus.COMPLETED.value},
        ]
        context = {"data": "test_value"}
        metadata = {"version": "1.0"}

        await storage.save_saga_state(
            saga_id=saga_id,
            saga_name=saga_name,
            status=status,
            steps=steps,
            context=context,
            metadata=metadata,
        )

        loaded = await storage.load_saga_state(saga_id)

        assert loaded is not None
        assert loaded["saga_id"] == saga_id
        assert loaded["saga_name"] == saga_name
        assert loaded["status"] == status.value
        assert loaded["steps"] == steps
        assert loaded["context"] == context
        assert loaded["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_load_nonexistent_saga(self):
        """Test loading a saga that doesn't exist"""
        storage = InMemorySagaStorage()

        result = await storage.load_saga_state("nonexistent-saga")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_saga_state(self):
        """Test deleting saga state"""
        storage = InMemorySagaStorage()

        saga_id = "delete-test-123"
        await storage.save_saga_state(
            saga_id=saga_id,
            saga_name="DeleteTest",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )

        loaded = await storage.load_saga_state(saga_id)
        assert loaded is not None

        deleted = await storage.delete_saga_state(saga_id)
        assert deleted is True

        loaded = await storage.load_saga_state(saga_id)
        assert loaded is None

        deleted = await storage.delete_saga_state(saga_id)
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_sagas(self):
        """Test listing sagas"""
        storage = InMemorySagaStorage()

        await storage.save_saga_state(
            saga_id="saga-1",
            saga_name="TestSaga1",
            status=SagaStatus.COMPLETED,
            steps=[{"name": "step1", "status": SagaStepStatus.COMPLETED.value}],
            context={},
        )

        await storage.save_saga_state(
            saga_id="saga-2",
            saga_name="TestSaga2",
            status=SagaStatus.FAILED,
            steps=[{"name": "step1", "status": SagaStepStatus.FAILED.value}],
            context={},
        )

        await storage.save_saga_state(
            saga_id="saga-3",
            saga_name="OtherSaga",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )

        all_sagas = await storage.list_sagas()
        assert len(all_sagas) == 3

        completed = await storage.list_sagas(status=SagaStatus.COMPLETED)
        assert len(completed) == 2

        failed = await storage.list_sagas(status=SagaStatus.FAILED)
        assert len(failed) == 1

        test_sagas = await storage.list_sagas(saga_name="TestSaga")
        assert len(test_sagas) == 2

    @pytest.mark.asyncio
    async def test_update_step_state(self):
        """Test updating step state"""
        storage = InMemorySagaStorage()

        saga_id = "step-update-test"
        await storage.save_saga_state(
            saga_id=saga_id,
            saga_name="StepTest",
            status=SagaStatus.EXECUTING,
            steps=[
                {"name": "step1", "status": SagaStepStatus.PENDING.value, "result": None},
                {"name": "step2", "status": SagaStepStatus.PENDING.value, "result": None},
            ],
            context={},
        )

        await storage.update_step_state(
            saga_id=saga_id,
            step_name="step1",
            status=SagaStepStatus.COMPLETED,
            result={"data": "success"},
            error=None,
            executed_at=datetime.now(),
        )

        loaded = await storage.load_saga_state(saga_id)
        assert loaded["steps"][0]["status"] == SagaStepStatus.COMPLETED.value
        assert loaded["steps"][0]["result"] == {"data": "success"}

    @pytest.mark.asyncio
    async def test_cleanup_completed_sagas(self):
        """Test cleanup of old completed sagas"""
        storage = InMemorySagaStorage()

        await storage.save_saga_state(
            saga_id="saga-1", saga_name="Test1", status=SagaStatus.COMPLETED, steps=[], context={}
        )

        await storage.save_saga_state(
            saga_id="saga-2", saga_name="Test2", status=SagaStatus.EXECUTING, steps=[], context={}
        )

        # Clean up using a future time (everything is older than future)
        deleted = await storage.cleanup_completed_sagas(
            older_than=datetime.now() + timedelta(days=1)
        )

        # Should delete completed saga
        assert deleted >= 1
        sagas = await storage.list_sagas()
        assert len(sagas) <= 1

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test storage health check"""
        storage = InMemorySagaStorage()

        health = await storage.health_check()
        assert health["status"] == "healthy"
        assert "total_sagas" in health

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test storage as context manager"""
        storage = InMemorySagaStorage()

        async with storage:
            await storage.save_saga_state(
                saga_id="context-test",
                saga_name="ContextTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

        loaded = await storage.load_saga_state("context-test")
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_update_step_state(self):
        """Test updating individual step state"""
        storage = InMemorySagaStorage()

        # Create saga with steps
        await storage.save_saga_state(
            saga_id="step-update",
            saga_name="StepTest",
            status=SagaStatus.EXECUTING,
            steps=[{"name": "step1", "status": "pending", "result": None, "error": None}],
            context={},
        )

        # Update step
        from datetime import datetime

        await storage.update_step_state(
            saga_id="step-update",
            step_name="step1",
            status=SagaStepStatus.COMPLETED,
            result={"data": "test"},
            error=None,
            executed_at=datetime.now(UTC),
        )

        # Verify update
        loaded = await storage.load_saga_state("step-update")
        assert loaded["steps"][0]["status"] == "completed"
        assert loaded["steps"][0]["result"] == {"data": "test"}

    @pytest.mark.asyncio
    async def test_update_step_state_saga_not_found(self):
        """Test update_step_state raises error for missing saga"""
        storage = InMemorySagaStorage()

        with pytest.raises(SagaStorageError, match="not found"):
            await storage.update_step_state(
                saga_id="nonexistent",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result=None,
                error=None,
            )

    @pytest.mark.asyncio
    async def test_update_step_state_step_not_found(self):
        """Test update_step_state raises error for missing step"""
        storage = InMemorySagaStorage()

        await storage.save_saga_state(
            saga_id="saga-123",
            saga_name="Test",
            status=SagaStatus.EXECUTING,
            steps=[{"name": "step1", "status": "pending"}],
            context={},
        )

        with pytest.raises(SagaStorageError, match="Step .* not found"):
            await storage.update_step_state(
                saga_id="saga-123",
                step_name="nonexistent_step",
                status=SagaStepStatus.COMPLETED,
                result=None,
                error=None,
            )

    @pytest.mark.asyncio
    async def test_get_saga_statistics(self):
        """Test getting saga statistics"""
        storage = InMemorySagaStorage()

        # Create multiple sagas
        await storage.save_saga_state(
            saga_id="completed-1",
            saga_name="Test",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )

        await storage.save_saga_state(
            saga_id="failed-1", saga_name="Test", status=SagaStatus.FAILED, steps=[], context={}
        )

        stats = await storage.get_saga_statistics()
        assert stats["total_sagas"] == 2
        assert "by_status" in stats
        assert stats["by_status"]["completed"] >= 1
        assert stats["by_status"]["failed"] >= 1
        assert "memory_usage_bytes" in stats

    @pytest.mark.asyncio
    async def test_cleanup_completed_sagas(self):
        """Test cleanup of old completed sagas"""
        storage = InMemorySagaStorage()

        # Create old saga
        await storage.save_saga_state(
            saga_id="old-saga", saga_name="Old", status=SagaStatus.COMPLETED, steps=[], context={}
        )

        # Sleep to make it older

        await asyncio.sleep(0.1)

        # Cleanup
        from datetime import datetime

        deleted = await storage.cleanup_completed_sagas(older_than=datetime.now(UTC))

        assert deleted >= 1
        loaded = await storage.load_saga_state("old-saga")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_cleanup_sagas_invalid_timestamp(self):
        """Test cleanup handles sagas with invalid timestamps"""
        storage = InMemorySagaStorage()

        # Manually insert saga with bad timestamp
        async with storage._lock:
            storage._sagas["bad-timestamp"] = {
                "saga_id": "bad-timestamp",
                "status": "completed",
                "updated_at": "invalid-date",
            }

        # Should not crash
        from datetime import datetime

        await storage.cleanup_completed_sagas(older_than=datetime.now(UTC))

        # Bad saga should still exist (skipped due to invalid timestamp)
        assert "bad-timestamp" in storage._sagas

    @pytest.mark.asyncio
    async def test_clear_all(self):
        """Test clearing all sagas"""
        storage = InMemorySagaStorage()

        # Add some sagas
        for i in range(3):
            await storage.save_saga_state(
                saga_id=f"saga-{i}",
                saga_name="Test",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

        count = await storage.clear_all()
        assert count == 3
        assert storage.get_saga_count() == 0

    @pytest.mark.asyncio
    async def test_get_saga_count(self):
        """Test getting saga count"""
        storage = InMemorySagaStorage()

        assert storage.get_saga_count() == 0

        await storage.save_saga_state(
            saga_id="test", saga_name="Test", status=SagaStatus.COMPLETED, steps=[], context={}
        )

        assert storage.get_saga_count() == 1


class TestInMemoryStorageListFiltering:
    """Tests for InMemorySagaStorage list filtering edge cases"""

    @pytest.mark.asyncio
    async def test_list_sagas_with_status_mismatch(self):
        """Test listing sagas that don't match status filter"""
        storage = InMemorySagaStorage()

        # Create saga with EXECUTING status
        await storage.save_saga_state(
            saga_id="executing-saga",
            saga_name="ExecutingSaga",
            status=SagaStatus.EXECUTING,
            steps=[],
            context={},
        )

        # Search for COMPLETED status - should not find it
        result = await storage.list_sagas(status=SagaStatus.COMPLETED)
        assert len(result) == 0 or not any(s["saga_id"] == "executing-saga" for s in result)

    @pytest.mark.asyncio
    async def test_list_sagas_with_name_mismatch(self):
        """Test listing sagas that don't match name filter"""
        storage = InMemorySagaStorage()

        await storage.save_saga_state(
            saga_id="unique-name-saga",
            saga_name="VeryUniqueName",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )

        # Search for different name - should not find it
        result = await storage.list_sagas(saga_name="DifferentName")
        assert not any(s["saga_id"] == "unique-name-saga" for s in result)

    @pytest.mark.asyncio
    async def test_cleanup_with_custom_statuses(self):
        """Test cleanup with custom status list"""
        storage = InMemorySagaStorage()

        # Create sagas with different statuses
        await storage.save_saga_state(
            saga_id="failed-saga",
            saga_name="FailedSaga",
            status=SagaStatus.FAILED,
            steps=[],
            context={},
        )

        await storage.save_saga_state(
            saga_id="executing-saga",
            saga_name="ExecutingSaga",
            status=SagaStatus.EXECUTING,
            steps=[],
            context={},
        )

        await asyncio.sleep(0.1)

        # Cleanup only FAILED status (not default)
        deleted = await storage.cleanup_completed_sagas(
            older_than=datetime.now(UTC), statuses=[SagaStatus.FAILED]
        )

        assert deleted == 1

        # EXECUTING should still exist
        assert await storage.load_saga_state("executing-saga") is not None

        # FAILED should be deleted
        assert await storage.load_saga_state("failed-saga") is None
