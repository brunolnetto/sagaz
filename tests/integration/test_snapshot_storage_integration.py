"""
Integration tests for Snapshot Storage backends using testcontainers.

These tests use Docker containers to test real PostgreSQL and Redis
snapshot storage without requiring manual infrastructure setup.

Requires:
    - Docker running
    - testcontainers[postgres,redis] installed

Run with:
    pytest -m integration tests/integration/test_snapshot_storage_integration.py -v

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


# ============================================
# POSTGRESQL SNAPSHOT STORAGE TESTS
# ============================================


class TestPostgreSQLSnapshotStorageIntegration:
    """Integration tests for PostgreSQL snapshot storage using testcontainers.

    Uses session-scoped postgres_container fixture from conftest.py for efficiency.
    """

    @pytest.mark.asyncio
    async def test_postgresql_snapshot_lifecycle(self, postgres_container):
        """Test full snapshot lifecycle: save, get, list, delete."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.postgresql.snapshot import (
            ASYNCPG_AVAILABLE,
            PostgreSQLSnapshotStorage,
        )

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        # Create storage from container
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        storage = PostgreSQLSnapshotStorage(
            connection_string=connection_string,
            pool_min_size=1,
            pool_max_size=5,
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
    async def test_postgresql_multiple_snapshots(self, postgres_container):
        """Test handling multiple snapshots for the same saga."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.postgresql.snapshot import (
            ASYNCPG_AVAILABLE,
            PostgreSQLSnapshotStorage,
        )

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        storage = PostgreSQLSnapshotStorage(connection_string=connection_string)

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
    async def test_postgresql_get_snapshot_at_time(self, postgres_container):
        """Test retrieving snapshot at a specific point in time."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.postgresql.snapshot import (
            ASYNCPG_AVAILABLE,
            PostgreSQLSnapshotStorage,
        )

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        storage = PostgreSQLSnapshotStorage(connection_string=connection_string)

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
    async def test_postgresql_delete_expired_snapshots(self, postgres_container):
        """Test automatic deletion of expired snapshots."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.postgresql.snapshot import (
            ASYNCPG_AVAILABLE,
            PostgreSQLSnapshotStorage,
        )

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        storage = PostgreSQLSnapshotStorage(connection_string=connection_string)

        try:
            saga_id = uuid4()

            # Create expired snapshot
            expired_snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="expired_saga",
                step_name="old_step",
                step_index=0,
                status=SagaStatus.COMPLETED,
                context={},
                completed_steps=[],
                created_at=datetime.now(UTC),
                retention_until=datetime.now(UTC) - timedelta(days=1),  # Already expired
            )
            await storage.save_snapshot(expired_snapshot)

            # Create valid snapshot
            valid_snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="valid_saga",
                step_name="current_step",
                step_index=1,
                status=SagaStatus.EXECUTING,
                context={},
                completed_steps=[],
                created_at=datetime.now(UTC),
                retention_until=datetime.now(UTC) + timedelta(days=30),
            )
            await storage.save_snapshot(valid_snapshot)

            # Delete expired snapshots
            deleted_count = await storage.delete_expired_snapshots()
            assert deleted_count >= 1

            # Verify expired snapshot is gone
            expired_retrieved = await storage.get_snapshot(expired_snapshot.snapshot_id)
            assert expired_retrieved is None

            # Verify valid snapshot still exists
            valid_retrieved = await storage.get_snapshot(valid_snapshot.snapshot_id)
            assert valid_retrieved is not None

        finally:
            await storage.close()


# ============================================
# REDIS SNAPSHOT STORAGE TESTS
# ============================================


class TestRedisSnapshotStorageIntegration:
    """Integration tests for Redis snapshot storage using testcontainers.

    Uses session-scoped redis_container fixture from conftest.py for efficiency.
    """

    @pytest.mark.asyncio
    async def test_redis_snapshot_lifecycle(self, redis_container):
        """Test full snapshot lifecycle: save, get, list, delete."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.redis.snapshot import (
            REDIS_AVAILABLE,
            RedisSnapshotStorage,
        )

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")

        # Create storage from container
        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}/0"
        storage = RedisSnapshotStorage(redis_url=redis_url, enable_compression=False)

        try:
            # Create test snapshot
            saga_id = uuid4()
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="redis_payment_saga",
                step_name="validate_payment",
                step_index=2,
                status=SagaStatus.EXECUTING,
                context={"amount": 250.75, "method": "credit_card"},
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
            assert retrieved.saga_name == "redis_payment_saga"
            assert retrieved.context["amount"] == 250.75

            # Test list_snapshots
            snapshots = await storage.list_snapshots(saga_id=saga_id)
            assert len(snapshots) >= 1

            # Test delete_snapshot
            deleted = await storage.delete_snapshot(snapshot.snapshot_id)
            assert deleted is True

            # Verify deleted
            retrieved_after = await storage.get_snapshot(snapshot.snapshot_id)
            assert retrieved_after is None

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_redis_multiple_snapshots(self, redis_container):
        """Test handling multiple snapshots in Redis."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.redis.snapshot import (
            REDIS_AVAILABLE,
            RedisSnapshotStorage,
        )

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}/0"
        storage = RedisSnapshotStorage(redis_url=redis_url, enable_compression=False)

        try:
            saga_id = uuid4()

            # Create multiple snapshots
            for i in range(3):
                snapshot = SagaSnapshot(
                    snapshot_id=uuid4(),
                    saga_id=saga_id,
                    saga_name="redis_order_saga",
                    step_name=f"redis_step_{i}",
                    step_index=i,
                    status=SagaStatus.EXECUTING,
                    context={"step": i},
                    completed_steps=[],
                    created_at=datetime.now(UTC),
                    retention_until=None,
                )
                await storage.save_snapshot(snapshot)

            # List all snapshots
            all_snapshots = await storage.list_snapshots(saga_id=saga_id)
            assert len(all_snapshots) == 3

            # Get latest
            latest = await storage.get_latest_snapshot(saga_id=saga_id)
            assert latest is not None

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_redis_ttl_expiration(self, redis_container):
        """Test TTL-based expiration in Redis."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.redis.snapshot import (
            REDIS_AVAILABLE,
            RedisSnapshotStorage,
        )

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}/0"

        # Create storage with short TTL, disable compression to avoid zstandard dependency
        storage = RedisSnapshotStorage(redis_url=redis_url, default_ttl=2, enable_compression=False)

        try:
            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=uuid4(),
                saga_name="ttl_test_saga",
                step_name="ttl_step",
                step_index=0,
                status=SagaStatus.EXECUTING,
                context={},
                completed_steps=[],
                created_at=datetime.now(UTC),
                retention_until=None,
            )

            # Save snapshot
            await storage.save_snapshot(snapshot)

            # Verify it exists immediately
            retrieved = await storage.get_snapshot(snapshot.snapshot_id)
            assert retrieved is not None

            # Wait for TTL to expire
            await asyncio.sleep(3)

            # Verify it's gone
            expired_retrieved = await storage.get_snapshot(snapshot.snapshot_id)
            assert expired_retrieved is None

        finally:
            await storage.close()
