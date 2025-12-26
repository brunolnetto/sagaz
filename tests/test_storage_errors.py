"""
Comprehensive error path tests for storage backends.
Tests error handling, edge cases, and exceptional conditions.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from sagaz.exceptions import MissingDependencyError
from sagaz.storage.base import SagaStorageError
from sagaz.storage.memory import InMemorySagaStorage
from sagaz.storage.postgresql import PostgreSQLSagaStorage
from sagaz.storage.redis import RedisSagaStorage
from sagaz.types import SagaStatus, SagaStepStatus


class TestPostgreSQLStorageErrors:
    """Test PostgreSQL storage error paths."""

    @pytest.mark.asyncio
    async def test_import_error_when_asyncpg_not_available(self):
        """Test MissingDependencyError is raised when asyncpg is not installed."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", False):
            with pytest.raises(MissingDependencyError):
                PostgreSQLSagaStorage("postgresql://test")


class TestRedisStorageErrors:
    """Test Redis storage error paths."""

    @pytest.mark.asyncio
    async def test_import_error_when_redis_not_available(self):
        """Test MissingDependencyError is raised when redis is not installed."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", False):
            with pytest.raises(MissingDependencyError):
                RedisSagaStorage("redis://test")


class TestMemoryStorageEdgeCases:
    """Test in-memory storage edge cases."""

    @pytest.mark.asyncio
    async def test_update_step_state_with_nonexistent_saga(self):
        """Test updating step state for non-existent saga raises error."""
        storage = InMemorySagaStorage()
        async with storage:
            # Should raise SagaStorageError for nonexistent saga
            with pytest.raises(SagaStorageError, match="Saga nonexistent-saga not found"):
                await storage.update_step_state(
                    "nonexistent-saga", "step1", SagaStepStatus.COMPLETED, result={"data": "test"}
                )

    @pytest.mark.asyncio
    async def test_update_step_state_with_nonexistent_step(self):
        """Test updating non-existent step in existing saga raises error."""
        storage = InMemorySagaStorage()
        async with storage:
            # Create saga
            await storage.save_saga_state(
                "test-saga", "test", SagaStatus.EXECUTING, steps=[], context={}, metadata={}
            )

            # Update non-existent step - should raise error
            with pytest.raises(SagaStorageError, match="Step new-step not found"):
                await storage.update_step_state(
                    "test-saga", "new-step", SagaStepStatus.COMPLETED, result={"data": "test"}
                )


class TestStorageBaseClassEdgeCases:
    """Test base storage class edge cases."""

    @pytest.mark.asyncio
    async def test_context_manager_without_implementation(self):
        """Test that base storage can be used as context manager."""
        from sagaz.storage.base import SagaStorage

        # Mock concrete implementation
        storage = Mock(spec=SagaStorage)
        storage.__aenter__ = AsyncMock(return_value=storage)
        storage.__aexit__ = AsyncMock(return_value=None)

        # Should work as context manager
        async with storage as s:
            assert s is storage

        storage.__aenter__.assert_called_once()
        storage.__aexit__.assert_called_once()
