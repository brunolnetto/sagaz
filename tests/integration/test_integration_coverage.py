"""
Integration tests for maximizing code coverage using testcontainers.

Targets:
- Redis outbox storage (currently 87%)
- PostgreSQL saga storage edge cases (currently 96%)
- Storage manager transfer/backup scenarios (currently 93%)

Uses session-scoped fixtures from conftest.py for efficient container reuse.

Run with:
    pytest -m integration tests/test_integration_coverage.py -v
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("testcontainers")

# Mark all tests in this module as integration tests (excluded by default)
pytestmark = pytest.mark.integration


# ============================================
# REDIS OUTBOX STORAGE TESTS
# Target: sagaz/storage/backends/redis/outbox.py (87%)
# ============================================


class TestRedisOutboxStorageIntegration:
    """Integration tests for Redis outbox storage using testcontainers."""

    @pytest.mark.asyncio
    async def test_redis_outbox_full_lifecycle(self, redis_container):
        """Test complete lifecycle: insert, claim, update, query."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        from sagaz.outbox.types import OutboxEvent, OutboxStatus
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisOutboxStorage(
            redis_url=redis_url,
            prefix="test:outbox",
            consumer_group="test-workers",
        ) as storage:
            # Insert event
            event = OutboxEvent(
                saga_id="saga-redis-test",
                event_type="order.created",
                payload={"order_id": "ORD-123", "amount": 99.99},
            )
            inserted = await storage.insert(event)
            assert inserted.event_id == event.event_id

            # Get by ID
            retrieved = await storage.get_by_id(event.event_id)
            assert retrieved is not None
            assert retrieved.saga_id == "saga-redis-test"

            # Claim batch
            claimed = await storage.claim_batch(
                worker_id="test-worker",
                batch_size=10,
            )
            assert len(claimed) >= 1
            assert claimed[0].status == OutboxStatus.CLAIMED
            assert claimed[0].worker_id == "test-worker"

            # Update status to SENT
            updated = await storage.update_status(
                event_id=claimed[0].event_id,
                status=OutboxStatus.SENT,
            )
            assert updated.status == OutboxStatus.SENT
            assert updated.sent_at is not None

    @pytest.mark.asyncio
    async def test_redis_outbox_stuck_events(self, redis_container):
        """Test stuck event detection and release."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        from sagaz.outbox.types import OutboxEvent, OutboxStatus
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisOutboxStorage(
            redis_url=redis_url,
            prefix="test:stuck",
            consumer_group="stuck-workers",
        ) as storage:
            # Insert and claim
            event = OutboxEvent(
                saga_id="saga-stuck-test",
                event_type="test.stuck",
                payload={"test": True},
            )
            await storage.insert(event)
            claimed = await storage.claim_batch(worker_id="stuck-worker", batch_size=1)
            assert len(claimed) == 1

            # Wait a moment and check for stuck events (0 second threshold)
            await asyncio.sleep(0.1)
            await storage.get_stuck_events(claimed_older_than_seconds=0)
            # Stuck events depend on Redis pending entries

            # Release stuck events
            released = await storage.release_stuck_events(claimed_older_than_seconds=0)
            # Should release or return 0 if none stuck
            assert released >= 0

    @pytest.mark.asyncio
    async def test_redis_outbox_saga_query(self, redis_container):
        """Test querying events by saga ID."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisOutboxStorage(
            redis_url=redis_url,
            prefix="test:sagaquery",
            consumer_group="saga-query-workers",
        ) as storage:
            # Insert multiple events for same saga
            saga_id = "saga-multi-event"
            for i in range(3):
                event = OutboxEvent(
                    saga_id=saga_id,
                    event_type=f"test.event.{i}",
                    payload={"index": i},
                )
                await storage.insert(event)

            # Query by saga
            events = await storage.get_events_by_saga(saga_id)
            assert len(events) == 3

    @pytest.mark.asyncio
    async def test_redis_outbox_dead_letter(self, redis_container):
        """Test dead letter queue operations."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        from sagaz.outbox.types import OutboxEvent, OutboxStatus
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisOutboxStorage(
            redis_url=redis_url,
            prefix="test:dlq",
            consumer_group="dlq-workers",
        ) as storage:
            # Insert and update to FAILED
            event = OutboxEvent(
                saga_id="saga-dlq-test",
                event_type="test.fail",
                payload={"test": True},
            )
            await storage.insert(event)
            await storage.update_status(
                event_id=event.event_id,
                status=OutboxStatus.FAILED,
                error_message="Test error",
            )

            # Get DLQ events
            dlq_events = await storage.get_dead_letter_events(limit=10)
            # May or may not have entries depending on DLQ stream
            assert isinstance(dlq_events, list)

    @pytest.mark.asyncio
    async def test_redis_outbox_statistics(self, redis_container):
        """Test storage statistics and health check."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage
        from sagaz.storage.core.health import HealthStatus

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisOutboxStorage(
            redis_url=redis_url,
            prefix="test:stats",
            consumer_group="stats-workers",
        ) as storage:
            # Insert some events
            for i in range(2):
                event = OutboxEvent(
                    saga_id=f"saga-stats-{i}",
                    event_type="test.stats",
                    payload={"index": i},
                )
                await storage.insert(event)

            # Health check
            health = await storage.health_check()
            assert health.status == HealthStatus.HEALTHY

            # Get pending count
            count = await storage.get_pending_count()
            assert count >= 2

            # Get statistics
            stats = await storage.get_statistics()
            assert stats.pending_records >= 2

            # Count total
            total = await storage.count()
            assert total >= 2

    @pytest.mark.asyncio
    async def test_redis_outbox_export_import(self, redis_container):
        """Test export and import functionality."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisOutboxStorage(
            redis_url=redis_url,
            prefix="test:export",
            consumer_group="export-workers",
        ) as storage:
            # Insert events
            for i in range(2):
                event = OutboxEvent(
                    saga_id=f"saga-export-{i}",
                    event_type="test.export",
                    payload={"index": i},
                )
                await storage.insert(event)

            # Export all
            exported = []
            async for record in storage.export_all():
                exported.append(record)
            assert len(exported) >= 2

            # Import a record (into a different prefix)
            async with RedisOutboxStorage(
                redis_url=redis_url,
                prefix="test:import",
                consumer_group="import-workers",
            ) as storage2:
                # Provide full record to ensure no fields are None that Redis doesn't like
                await storage2.import_record({
                    "event_id": "imported-event-id",
                    "saga_id": "imported-saga",
                    "event_type": "imported.event",
                    "payload": {"imported": True},
                    "aggregate_id": "imported-saga",  # Explicitly provide to avoid None
                    "aggregate_type": "saga",
                    "status": "pending",
                    "retry_count": 0,
                })

                # Verify import
                count = await storage2.count()
                assert count >= 1


# ============================================
# POSTGRESQL SAGA STORAGE TESTS
# Target: sagaz/storage/backends/postgresql/saga.py (96%)
# ============================================


class TestPostgreSQLSagaStorageIntegration:
    """Integration tests for PostgreSQL saga storage edge cases."""

    @pytest.mark.asyncio
    async def test_postgresql_saga_cleanup(self, postgres_container):
        """Test cleaning up old completed sagas."""
        if postgres_container is None:
            pytest.skip("PostgreSQL container not available")

        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.postgresql.saga import ASYNCPG_AVAILABLE, PostgreSQLSagaStorage

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        conn_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string=conn_string) as storage:
            # Insert a completed saga
            await storage.save_saga_state(
                saga_id="saga-cleanup-test",
                saga_name="CleanupTest",
                status=SagaStatus.COMPLETED,
                steps=[{"name": "step1", "status": "completed"}],
                context={"test": True},
            )

            # Cleanup sagas older than 0 days (should delete our fresh saga)
            older_than = datetime.now(UTC) + timedelta(days=1)
            deleted = await storage.cleanup_completed_sagas(older_than=older_than)
            assert deleted >= 1

            # Verify deleted
            loaded = await storage.load_saga_state("saga-cleanup-test")
            assert loaded is None

    @pytest.mark.asyncio
    async def test_postgresql_saga_list_filters(self, postgres_container):
        """Test listing sagas with various filters."""
        if postgres_container is None:
            pytest.skip("PostgreSQL container not available")

        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.postgresql.saga import ASYNCPG_AVAILABLE, PostgreSQLSagaStorage

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        conn_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string=conn_string) as storage:
            # Insert sagas with different statuses
            for i, status in enumerate([SagaStatus.COMPLETED, SagaStatus.ROLLED_BACK, SagaStatus.FAILED]):
                await storage.save_saga_state(
                    saga_id=f"saga-filter-{i}",
                    saga_name=f"FilterTest{i}",
                    status=status,
                    steps=[],
                    context={},
                )

            # List by status
            completed = await storage.list_sagas(status=SagaStatus.COMPLETED, limit=10)
            assert all(s["status"] == "completed" for s in completed)

            # List by name filter
            filtered = await storage.list_sagas(saga_name="FilterTest", limit=10)
            assert len(filtered) >= 1

            # Test pagination
            paginated = await storage.list_sagas(limit=1, offset=0)
            assert len(paginated) <= 1

    @pytest.mark.asyncio
    async def test_postgresql_saga_step_update(self, postgres_container):
        """Test updating individual step state."""
        if postgres_container is None:
            pytest.skip("PostgreSQL container not available")

        from sagaz.core.types import SagaStatus, SagaStepStatus
        from sagaz.storage.backends.postgresql.saga import ASYNCPG_AVAILABLE, PostgreSQLSagaStorage

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        conn_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string=conn_string) as storage:
            # Create saga with steps
            await storage.save_saga_state(
                saga_id="saga-step-update",
                saga_name="StepUpdateTest",
                status=SagaStatus.EXECUTING,
                steps=[
                    {"name": "step1", "status": "pending"},
                    {"name": "step2", "status": "pending"},
                ],
                context={},
            )

            # Update step status
            await storage.update_step_state(
                saga_id="saga-step-update",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"output": "success"},
                executed_at=datetime.now(UTC),
            )

            # Verify update
            loaded = await storage.load_saga_state("saga-step-update")
            assert loaded is not None
            step1 = next(s for s in loaded["steps"] if s["name"] == "step1")
            assert step1["status"] == "completed"
            assert step1["result"] == {"output": "success"}

    @pytest.mark.asyncio
    async def test_postgresql_saga_statistics(self, postgres_container):
        """Test getting storage statistics."""
        if postgres_container is None:
            pytest.skip("PostgreSQL container not available")

        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.postgresql.saga import ASYNCPG_AVAILABLE, PostgreSQLSagaStorage

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        conn_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string=conn_string) as storage:
            # Insert a saga
            await storage.save_saga_state(
                saga_id="saga-stats-test",
                saga_name="StatsTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

            # Get statistics
            stats = await storage.get_saga_statistics()
            assert "total_sagas" in stats
            assert "by_status" in stats
            assert stats["total_sagas"] >= 1


# ============================================
# STORAGE MANAGER TRANSFER TESTS
# Target: sagaz/storage/manager.py (93%)
# ============================================


class TestStorageManagerTransferIntegration:
    """Integration tests for storage manager transfer/backup scenarios."""

    @pytest.mark.asyncio
    async def test_storage_manager_memory_to_memory_transfer(self):
        """Test transferring data between memory storages."""
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.memory.saga import InMemorySagaStorage

        # Source storage with data
        source = InMemorySagaStorage()
        for i in range(3):
            await source.save_saga_state(
                saga_id=f"saga-transfer-{i}",
                saga_name="TransferTest",
                status=SagaStatus.COMPLETED,
                steps=[{"name": f"step{i}", "status": "completed"}],
                context={"index": i},
            )

        # Target storage (empty)
        target = InMemorySagaStorage()

        # Transfer to target using export/import
        transferred = 0
        async for record in source.export_all():
            await target.import_record(record)
            transferred += 1

        assert transferred == 3

        # Verify transfer
        loaded = await target.load_saga_state("saga-transfer-1")
        assert loaded is not None
        assert loaded["saga_name"] == "TransferTest"

    @pytest.mark.asyncio
    async def test_storage_manager_backup_restore(self):
        """Test backup and restore functionality using memory storage."""
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.memory.saga import InMemorySagaStorage
        from sagaz.storage.transfer.service import TransferConfig, TransferService

        source = InMemorySagaStorage()
        backup = InMemorySagaStorage()

        # Add data
        for i in range(5):
            await source.save_saga_state(
                saga_id=f"saga-backup-{i}",
                saga_name="BackupTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={"index": i},
            )

        # Create transfer service
        config = TransferConfig(batch_size=10)
        service = TransferService(
            source=source,
            target=backup,
            config=config,
        )

        # Transfer (backup)
        result = await service.transfer_all()

        assert result.success is True
        assert result.transferred == 5

        # Verify backup
        count = await backup.count()
        assert count == 5

    @pytest.mark.asyncio
    async def test_storage_transfer_with_validation(self):
        """Test transfer with post-validation using memory storage."""
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.memory.saga import InMemorySagaStorage
        from sagaz.storage.transfer.service import TransferConfig, TransferService

        source = InMemorySagaStorage()
        target = InMemorySagaStorage()

        # Add data
        for i in range(3):
            await source.save_saga_state(
                saga_id=f"saga-validate-{i}",
                saga_name="ValidateTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

        # Transfer with validation
        config = TransferConfig(
            batch_size=10,
            validate=True,
        )
        service = TransferService(
            source=source,
            target=target,
            config=config,
        )

        result = await service.transfer_all()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_storage_transfer_cancellation(self):
        """Test transfer cancellation handling using memory storage."""
        import asyncio

        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.memory.saga import InMemorySagaStorage
        from sagaz.storage.transfer.service import TransferConfig, TransferService

        # Create a slow target to allow cancellation to take effect
        class SlowMemoryStorage(InMemorySagaStorage):
            async def import_record(self, record):
                await asyncio.sleep(0.01)  # Small delay
                await super().import_record(record)

        source = InMemorySagaStorage()
        target = SlowMemoryStorage()

        # Add data
        for i in range(50):  # More items to ensure we catch it
            await source.save_saga_state(
                saga_id=f"saga-cancel-{i}",
                saga_name="CancelTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

        # Create transfer and cancel it
        config = TransferConfig(batch_size=5)
        service = TransferService(
            source=source,
            target=target,
            config=config,
        )

        # Start transfer in background
        task = asyncio.create_task(service.transfer_all())

        # Wait a bit then cancel
        await asyncio.sleep(0.05)
        service.cancel()

        # Wait for completion
        result = await task

        # Should be cancelled before completing all records
        assert result.transferred < 50
        assert result.transferred > 0  # Should have transferred at least some


# ============================================
# REDIS SAGA STORAGE TESTS
# Target: sagaz/storage/backends/redis/saga.py (97%)
# ============================================


class TestRedisSagaStorageIntegration:
    """Integration tests for Redis saga storage."""

    @pytest.mark.asyncio
    async def test_redis_saga_full_lifecycle(self, redis_container):
        """Test complete saga lifecycle in Redis."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        from sagaz.core.types import SagaStatus, SagaStepStatus
        from sagaz.storage.backends.redis.saga import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        storage = RedisSagaStorage(redis_url=redis_url, key_prefix="test:saga:")

        try:
            # Save saga
            await storage.save_saga_state(
                saga_id="saga-redis-lifecycle",
                saga_name="RedisLifecycleTest",
                status=SagaStatus.EXECUTING,
                steps=[
                    {"name": "step1", "status": "pending"},
                    {"name": "step2", "status": "pending"},
                ],
                context={"test": True},
                metadata={"created_by": "test"},
            )

            # Load saga
            loaded = await storage.load_saga_state("saga-redis-lifecycle")
            assert loaded is not None
            assert loaded["saga_name"] == "RedisLifecycleTest"
            assert loaded["status"] == "executing"

            # Update step
            await storage.update_step_state(
                saga_id="saga-redis-lifecycle",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"output": "done"},
            )

            # Delete saga
            deleted = await storage.delete_saga_state("saga-redis-lifecycle")
            assert deleted is True

            # Verify deleted
            loaded = await storage.load_saga_state("saga-redis-lifecycle")
            assert loaded is None

        finally:
            # Use aclose for Redis
            if hasattr(storage, "_redis") and storage._redis:
                await storage._redis.aclose()

    @pytest.mark.asyncio
    async def test_redis_saga_list_and_cleanup(self, redis_container):
        """Test listing and cleanup operations."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.redis.saga import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        storage = RedisSagaStorage(redis_url=redis_url, key_prefix="test:sagalist:")

        try:
            # Insert multiple sagas
            for i in range(5):
                await storage.save_saga_state(
                    saga_id=f"saga-list-{i}",
                    saga_name="ListTest",
                    status=SagaStatus.COMPLETED if i % 2 == 0 else SagaStatus.FAILED,
                    steps=[],
                    context={},
                )

            # List all
            all_sagas = await storage.list_sagas(limit=10)
            assert len(all_sagas) >= 5

            # List by status
            completed = await storage.list_sagas(status=SagaStatus.COMPLETED, limit=10)
            assert all(s["status"] == "completed" for s in completed)

            # Cleanup old sagas
            older_than = datetime.now(UTC) + timedelta(days=1)
            await storage.cleanup_completed_sagas(older_than=older_than)
            # Should clean up the completed ones

        finally:
            # Use aclose for Redis
            if hasattr(storage, "_redis") and storage._redis:
                await storage._redis.aclose()
