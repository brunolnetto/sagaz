"""
Integration tests for Redis Snapshot Storage using testcontainers.

These tests use Docker containers to test real Redis
snapshot storage without requiring manual infrastructure setup.

Requires:
    - Docker running
    - testcontainers[redis] installed
    - redis and zstandard packages

Run with:
    pytest -m integration tests/integration/test_redis_snapshot_integration.py -v

Skip during regular runs (default):
    pytest tests/  # These tests are excluded by default
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

# Skip if testcontainers not available
pytest.importorskip("testcontainers")

# Mark all tests in this module as integration tests (excluded by default)
pytestmark = pytest.mark.integration


class TestRedisSnapshotStorageIntegration:
    """Integration tests for Redis snapshot storage using testcontainers.

    Uses session-scoped redis_container fixture from conftest.py for efficiency.
    """

    @pytest.mark.asyncio
    async def test_redis_snapshot_lifecycle(self, redis_container):
        """Test full snapshot lifecycle: save, get, list, delete."""
        try:
            from sagaz.storage.backends.redis.snapshot import (
                REDIS_AVAILABLE,
                RedisSnapshotStorage,
            )
        except ImportError:
            pytest.skip("redis package not installed")

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")

        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus

        # Get connection URL from container
        redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}"
        
        storage = RedisSnapshotStorage(
            redis_url=redis_url,
            enable_compression=False,  # Disable to avoid zstd requirement
        )

        try:
            # Create test snapshot
            saga_id = uuid4()
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="payment_saga",
                step_name="authorize_payment",
                step_index=1,
                status=SagaStatus.EXECUTING,
                context={"amount": 100.50, "currency": "USD", "customer_id": "CUST-123"},
                completed_steps=[],
                created_at=datetime.now(UTC),
                retention_until=None,
            )

            # Test save_snapshot
            await storage.save_snapshot(snapshot)

            # Test get_snapshot
            retrieved = await storage.get_snapshot(snapshot.snapshot_id)
            assert retrieved is not None
            assert retrieved.saga_id == saga_id
            assert retrieved.saga_name == "payment_saga"
            assert retrieved.step_name == "authorize_payment"
            assert retrieved.context["amount"] == 100.50
            assert retrieved.context["currency"] == "USD"

            # Test list_snapshots
            snapshots = await storage.list_snapshots(saga_id=saga_id)
            assert len(snapshots) >= 1
            assert any(s.snapshot_id == snapshot.snapshot_id for s in snapshots)

            # Test delete_snapshot
            deleted = await storage.delete_snapshot(snapshot.snapshot_id)
            assert deleted is True

            # Verify deleted
            retrieved_after_delete = await storage.get_snapshot(snapshot.snapshot_id)
            assert retrieved_after_delete is None

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_redis_multiple_snapshots(self, redis_container):
        """Test handling multiple snapshots for the same saga."""
        try:
            from sagaz.storage.backends.redis.snapshot import (
                REDIS_AVAILABLE,
                RedisSnapshotStorage,
            )
        except ImportError:
            pytest.skip("redis package not installed")

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")

        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus

        redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}"
        storage = RedisSnapshotStorage(redis_url=redis_url, enable_compression=False)

        try:
            saga_id = uuid4()

            # Create multiple snapshots for the same saga
            for i in range(5):
                snapshot = SagaSnapshot(
                    snapshot_id=uuid4(),
                    saga_id=saga_id,
                    saga_name="order_saga",
                    step_name=f"step_{i}",
                    step_index=i,
                    status=SagaStatus.EXECUTING,
                    context={"step": i, "order_id": "ORD-456"},
                    completed_steps=[],
                    created_at=datetime.now(UTC),
                    retention_until=None,
                )
                await storage.save_snapshot(snapshot)
                await asyncio.sleep(0.01)  # Small delay to ensure ordering

            # List all snapshots
            all_snapshots = await storage.list_snapshots(saga_id=saga_id)
            assert len(all_snapshots) == 5

            # Test with limit
            limited_snapshots = await storage.list_snapshots(saga_id=saga_id, limit=3)
            assert len(limited_snapshots) == 3

            # Get latest snapshot
            latest = await storage.get_latest_snapshot(saga_id=saga_id)
            assert latest is not None
            assert latest.step_name == "step_4"  # Last one created

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_redis_get_snapshot_at_time(self, redis_container):
        """Test retrieving snapshot at a specific point in time."""
        try:
            from sagaz.storage.backends.redis.snapshot import (
                REDIS_AVAILABLE,
                RedisSnapshotStorage,
            )
        except ImportError:
            pytest.skip("redis package not installed")

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")

        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus

        redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}"
        storage = RedisSnapshotStorage(redis_url=redis_url, enable_compression=False)

        try:
            saga_id = uuid4()
            timestamps = []

            # Create snapshots at different times
            for i in range(3):
                snapshot = SagaSnapshot(
                    snapshot_id=uuid4(),
                    saga_id=saga_id,
                    saga_name="time_travel_saga",
                    step_name=f"step_{i}",
                    step_index=i,
                    status=SagaStatus.EXECUTING,
                    context={"step": i},
                    completed_steps=[],
                    created_at=datetime.now(UTC),
                    retention_until=None,
                )
                await storage.save_snapshot(snapshot)
                timestamps.append(snapshot.created_at)
                await asyncio.sleep(0.1)  # Delay between snapshots

            # Get snapshot at middle timestamp
            middle_snapshot = await storage.get_snapshot_at_time(
                saga_id=saga_id, timestamp=timestamps[1]
            )
            assert middle_snapshot is not None
            assert middle_snapshot.step_name in ["step_0", "step_1"]

            # Get snapshot at latest timestamp
            latest_snapshot = await storage.get_snapshot_at_time(
                saga_id=saga_id, timestamp=timestamps[2]
            )
            assert latest_snapshot is not None

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_redis_snapshot_with_ttl(self, redis_container):
        """Test snapshot TTL functionality."""
        try:
            from sagaz.storage.backends.redis.snapshot import (
                REDIS_AVAILABLE,
                RedisSnapshotStorage,
            )
        except ImportError:
            pytest.skip("redis package not installed")

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")

        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus

        redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}"
        
        # Use short TTL for testing
        storage = RedisSnapshotStorage(
            redis_url=redis_url,
            default_ttl=2,  # 2 seconds
            enable_compression=False,  # Avoid zstd requirement
        )

        try:
            saga_id = uuid4()
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="ttl_saga",
                step_name="temp_step",
                step_index=0,
                status=SagaStatus.EXECUTING,
                context={},
                completed_steps=[],
                created_at=datetime.now(UTC),
                retention_until=None,
            )

            await storage.save_snapshot(snapshot)

            # Should exist immediately
            retrieved = await storage.get_snapshot(snapshot.snapshot_id)
            assert retrieved is not None

            # Wait for TTL expiration
            await asyncio.sleep(3)

            # Should be expired now
            expired = await storage.get_snapshot(snapshot.snapshot_id)
            assert expired is None

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_redis_compression(self, redis_container):
        """Test snapshot compression functionality."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.redis.snapshot import (
            REDIS_AVAILABLE,
            ZSTD_AVAILABLE,
            RedisSnapshotStorage,
        )

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")
        if not ZSTD_AVAILABLE:
            pytest.skip("zstandard not installed")

        redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}"
        
        storage = RedisSnapshotStorage(
            redis_url=redis_url,
            enable_compression=True,  # Test compression functionality
            compression_level=5,
        )

        try:
            saga_id = uuid4()
            
            # Create snapshot with large context
            large_context = {"data": "x" * 10000}  # 10KB of data
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="compression_saga",
                step_name="compress_step",
                step_index=0,
                status=SagaStatus.EXECUTING,
                context=large_context,
                completed_steps=[],
                created_at=datetime.now(UTC),
                retention_until=None,
            )

            await storage.save_snapshot(snapshot)

            # Retrieve and verify data is intact
            retrieved = await storage.get_snapshot(snapshot.snapshot_id)
            assert retrieved is not None
            assert retrieved.context["data"] == large_context["data"]

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_redis_context_manager(self, redis_container):
        """Test Redis snapshot storage with context manager."""
        try:
            from sagaz.storage.backends.redis.snapshot import (
                REDIS_AVAILABLE,
                RedisSnapshotStorage,
            )
        except ImportError:
            pytest.skip("redis package not installed")

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")

        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus

        redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}"

        async with RedisSnapshotStorage(
            redis_url=redis_url,
            enable_compression=False  # Avoid zstd requirement
        ) as storage:
            saga_id = uuid4()
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="context_saga",
                step_name="test_step",
                step_index=0,
                status=SagaStatus.EXECUTING,
                context={"test": "data"},
                completed_steps=[],
                created_at=datetime.now(UTC),
                retention_until=None,
            )

            await storage.save_snapshot(snapshot)
            retrieved = await storage.get_snapshot(snapshot.snapshot_id)
            assert retrieved is not None

        # Connection should be closed after context manager exits
