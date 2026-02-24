"""
Integration tests for S3 Snapshot Storage using LocalStack.

LocalStack provides a fully functional local AWS cloud stack that supports
aioboto3's async operations. Containers start in parallel automatically.

Requires:
    - testcontainers-localstack installed  
    - aioboto3 and zstandard packages
    - Docker running with adequate resources

Tests run automatically if LocalStack container is available.
S3 unit tests provide full code coverage (these are for integration validation).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

# Mark all tests in this module as integration tests (excluded by default)
pytestmark = pytest.mark.integration


@pytest.fixture
async def s3_storage_setup(localstack_container):
    """Setup S3 storage with LocalStack (auto-initialized in parallel)."""
    import aioboto3
    
    # Get LocalStack S3 endpoint
    endpoint_url = localstack_container.get_url()
    
    # Create bucket using boto3 (sync) first
    import boto3
    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    bucket_name = "test-saga-snapshots"
    s3_client.create_bucket(Bucket=bucket_name)
    
    # Return connection details for async client
    yield {
        "endpoint_url": endpoint_url,
        "bucket_name": bucket_name,
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",
        "region_name": "us-east-1",
    }


class TestS3SnapshotStorageIntegration:
    """Integration tests for S3 snapshot storage using LocalStack.

    Uses LocalStack to provide a fully functional local S3 service that
    supports aioboto3's async operations.
    """

    @pytest.mark.asyncio
    async def test_s3_snapshot_lifecycle(self, s3_storage_setup):
        """Test full snapshot lifecycle: save, get, list, delete."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.s3.snapshot import S3SnapshotStorage

        # Create storage with LocalStack config
        storage = S3SnapshotStorage(
            bucket_name=s3_storage_setup["bucket_name"],
            region_name=s3_storage_setup["region_name"],
            endpoint_url=s3_storage_setup["endpoint_url"],
            aws_access_key_id=s3_storage_setup["aws_access_key_id"],
            aws_secret_access_key=s3_storage_setup["aws_secret_access_key"],
            enable_compression=False,
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
                context={"amount": 100.50, "currency": "USD"},
                completed_steps=[],
                created_at=datetime.now(UTC),
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
    async def test_s3_multiple_snapshots(self, s3_storage_setup):
        """Test handling multiple snapshots for the same saga."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.s3.snapshot import (
            AIOBOTO3_AVAILABLE,
            S3SnapshotStorage,
        )

        if not AIOBOTO3_AVAILABLE:
            pytest.skip("aioboto3 not installed")

        storage = S3SnapshotStorage(
            bucket_name=s3_storage_setup["bucket_name"],
            endpoint_url=s3_storage_setup["endpoint_url"],
            aws_access_key_id=s3_storage_setup["aws_access_key_id"],
            aws_secret_access_key=s3_storage_setup["aws_secret_access_key"],
            region_name=s3_storage_setup["region_name"],
            enable_compression=False,
        )

        try:
            await storage._get_s3_client()
            saga_id = uuid4()

            # Create multiple snapshots
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
                await asyncio.sleep(0.01)

            # List all snapshots
            all_snapshots = await storage.list_snapshots(saga_id=saga_id)
            assert len(all_snapshots) == 5

            # Test with limit
            limited_snapshots = await storage.list_snapshots(saga_id=saga_id, limit=3)
            assert len(limited_snapshots) == 3

            # Get latest snapshot
            latest = await storage.get_latest_snapshot(saga_id=saga_id)
            assert latest is not None
            assert latest.step_name == "step_4"

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_s3_get_snapshot_at_time(self, s3_storage_setup):
        """Test retrieving snapshot at a specific point in time."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.s3.snapshot import (
            AIOBOTO3_AVAILABLE,
            S3SnapshotStorage,
        )

        if not AIOBOTO3_AVAILABLE:
            pytest.skip("aioboto3 not installed")

        storage = S3SnapshotStorage(
            bucket_name=s3_storage_setup["bucket_name"],
            endpoint_url=s3_storage_setup["endpoint_url"],
            aws_access_key_id=s3_storage_setup["aws_access_key_id"],
            aws_secret_access_key=s3_storage_setup["aws_secret_access_key"],
            region_name=s3_storage_setup["region_name"],
            enable_compression=False,
        )

        try:
            await storage._get_s3_client()
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
                await asyncio.sleep(0.1)

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
    async def test_s3_compression(self, s3_storage_setup):
        """Test snapshot compression functionality."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.s3.snapshot import (
            AIOBOTO3_AVAILABLE,
            ZSTD_AVAILABLE,
            S3SnapshotStorage,
        )

        if not AIOBOTO3_AVAILABLE:
            pytest.skip("aioboto3 not installed")
        if not ZSTD_AVAILABLE:
            pytest.skip("zstandard not installed")

        bucket_name = s3_storage_setup
        storage = S3SnapshotStorage(
            bucket_name=bucket_name,
            region_name="us-east-1",
            enable_compression=True,
            compression_level=5,
        )

        try:
            await storage._get_s3_client()
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
    async def test_s3_context_manager(self, s3_storage_setup):
        """Test S3 snapshot storage with context manager."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.s3.snapshot import (
            AIOBOTO3_AVAILABLE,
            S3SnapshotStorage,
        )

        if not AIOBOTO3_AVAILABLE:
            pytest.skip("aioboto3 not installed")

        bucket_name = s3_storage_setup

        async with S3SnapshotStorage(
            bucket_name=bucket_name, region_name="us-east-1"
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

    @pytest.mark.asyncio
    async def test_s3_encryption(self, s3_storage_setup):
        """Test S3 server-side encryption."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.types import SagaStatus
        from sagaz.storage.backends.s3.snapshot import (
            AIOBOTO3_AVAILABLE,
            S3SnapshotStorage,
        )

        if not AIOBOTO3_AVAILABLE:
            pytest.skip("aioboto3 not installed")

        bucket_name = s3_storage_setup
        storage = S3SnapshotStorage(
            bucket_name=bucket_name,
            region_name="us-east-1",
            enable_encryption=True,
        )

        try:
            await storage._get_s3_client()
            saga_id = uuid4()

            snapshot = SagaSnapshot(
                snapshot_id=uuid4(),
                saga_id=saga_id,
                saga_name="encrypted_saga",
                step_name="secure_step",
                step_index=0,
                status=SagaStatus.EXECUTING,
                context={"sensitive": "data"},
                completed_steps=[],
                created_at=datetime.now(UTC),
                retention_until=None,
            )

            await storage.save_snapshot(snapshot)
            retrieved = await storage.get_snapshot(snapshot.snapshot_id)
            assert retrieved is not None
            assert retrieved.context["sensitive"] == "data"

        finally:
            await storage.close()
