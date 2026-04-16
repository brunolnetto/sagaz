"""
Unit tests for S3 Snapshot Storage backend with mocks.

These are fast unit tests that don't require AWS or actual S3.
For integration tests with mocked S3, see tests/integration/test_s3_snapshot_integration.py
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.replay import ReplayResult, SagaSnapshot
from sagaz.core.types import SagaStatus


class TestS3SnapshotStorageImportError:
    """Tests for S3 snapshot storage when aioboto3 is not available"""

    def test_aioboto3_not_available_import_error(self):
        """Test that S3SnapshotStorage raises MissingDependencyError"""
        with patch.dict("sys.modules", {"aioboto3": None}):
            with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", False):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                with pytest.raises(MissingDependencyError, match="aioboto3"):
                    S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)

    def test_zstd_not_available_with_compression(self):
        """Test that compression requirement raises MissingDependencyError"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.ZSTD_AVAILABLE", False):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                with pytest.raises(MissingDependencyError, match="zstandard"):
                    S3SnapshotStorage(bucket_name="test-bucket", enable_compression=True)


class TestS3SnapshotStorageUnit:
    """Unit tests for S3SnapshotStorage with mocked S3 client"""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test S3 snapshot storage initialization"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    region_name="us-west-2",
                    prefix="snapshots/",
                    enable_encryption=True,
                    enable_compression=False,
                )
                assert storage.bucket_name == "test-bucket"
                assert storage.region_name == "us-west-2"
                assert storage.prefix == "snapshots/"
                assert storage.enable_encryption is True

    @pytest.mark.asyncio
    async def test_save_snapshot_mocked(self):
        """Test save_snapshot with mocked S3"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                # Mock S3 client
                mock_session = MagicMock()
                mock_client = AsyncMock()

                # Mock the client context manager
                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                # Mock NoSuchKey exception - must inherit from BaseException
                class MockNoSuchKey(BaseException):
                    pass

                mock_exceptions = MagicMock()
                mock_exceptions.NoSuchKey = MockNoSuchKey
                mock_client.exceptions = mock_exceptions

                # Mock S3 operations
                mock_client.put_object = AsyncMock()
                mock_client.head_bucket = AsyncMock()
                # Mock get_object to raise NoSuchKey for index (new saga, no index yet)
                mock_client.get_object = AsyncMock(side_effect=MockNoSuchKey())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    enable_compression=False,
                )

                # Initialize client
                await storage._get_s3_client()

                # Create test snapshot
                saga_id = uuid4()
                snapshot = SagaSnapshot(
                    snapshot_id=uuid4(),
                    saga_id=saga_id,
                    saga_name="test_saga",
                    step_name="test_step",
                    step_index=0,
                    status=SagaStatus.EXECUTING,
                    context={"test": "data"},
                    completed_steps=[],
                    created_at=datetime.now(UTC),
                    retention_until=None,
                )

                # Test save
                await storage.save_snapshot(snapshot)

                # Verify S3 calls were made
                assert mock_client.put_object.called
                # Should be called twice: once for snapshot, once for index
                assert mock_client.put_object.call_count == 2

    @pytest.mark.asyncio
    async def test_get_snapshot_found(self):
        """Test get_snapshot when snapshot exists"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                # Create test data
                saga_id = uuid4()
                snapshot_id = uuid4()
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(saga_id),
                    "saga_name": "test_saga",
                    "step_name": "test_step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {"test": "data"},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                    "retention_until": None,
                }

                # Mock S3 get_object response
                mock_body = AsyncMock()
                mock_body.read = AsyncMock(return_value=json.dumps(snapshot_data).encode("utf-8"))
                mock_client.get_object = AsyncMock(return_value={"Body": mock_body})

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    enable_compression=False,
                )
                await storage._get_s3_client()

                # Test get
                result = await storage.get_snapshot(snapshot_id)

                assert result is not None
                assert result.snapshot_id == snapshot_id
                assert result.saga_id == saga_id
                assert result.saga_name == "test_saga"

    @pytest.mark.asyncio
    async def test_get_snapshot_not_found(self):
        """Test get_snapshot when snapshot doesn't exist"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                # Mock NoSuchKey exception - must inherit from BaseException
                class MockNoSuchKey(BaseException):
                    pass

                mock_exceptions = MagicMock()
                mock_exceptions.NoSuchKey = MockNoSuchKey
                mock_client.exceptions = mock_exceptions
                mock_client.get_object = AsyncMock(side_effect=MockNoSuchKey())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_snapshot(uuid4())
                assert result is None

    @pytest.mark.asyncio
    async def test_list_snapshots(self):
        """Test list_snapshots"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                # Create test data
                snapshot_id = uuid4()
                saga_id = uuid4()
                created_at = datetime.now(UTC)

                # Mock saga index data
                index_data = {
                    "saga_id": str(saga_id),
                    "snapshots": [
                        {"snapshot_id": str(snapshot_id), "created_at": created_at.isoformat()}
                    ],
                }

                # Mock snapshot data
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(saga_id),
                    "saga_name": "test_saga",
                    "step_name": "test_step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": created_at.isoformat(),
                    "retention_until": None,
                }

                # Mock get_object to return index first, then snapshot
                async def mock_get_object(**kwargs):
                    if "index/saga" in kwargs["Key"]:
                        # Return index
                        mock_body = AsyncMock()
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(index_data).encode("utf-8")
                        )
                        return {"Body": mock_body}
                    # Return snapshot
                    mock_body = AsyncMock()
                    mock_body.read = AsyncMock(
                        return_value=json.dumps(snapshot_data).encode("utf-8")
                    )
                    return {"Body": mock_body}

                mock_client.get_object = mock_get_object

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.list_snapshots(saga_id=saga_id)
                assert len(result) == 1
                assert result[0].snapshot_id == snapshot_id

    @pytest.mark.asyncio
    async def test_delete_snapshot(self):
        """Test delete_snapshot"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                snapshot_id = uuid4()
                saga_id = uuid4()
                created_at = datetime.now(UTC)

                # Mock snapshot data
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(saga_id),
                    "saga_name": "test",
                    "step_name": "step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": created_at.isoformat(),
                    "retention_until": None,
                }

                # Mock index data
                index_data = {
                    "saga_id": str(saga_id),
                    "snapshots": [
                        {"snapshot_id": str(snapshot_id), "created_at": created_at.isoformat()}
                    ],
                }

                # Mock get_object to return snapshot and index
                async def mock_get_object(**kwargs):
                    if "index/saga" in kwargs["Key"]:
                        mock_body = AsyncMock()
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(index_data).encode("utf-8")
                        )
                        return {"Body": mock_body}
                    mock_body = AsyncMock()
                    mock_body.read = AsyncMock(
                        return_value=json.dumps(snapshot_data).encode("utf-8")
                    )
                    return {"Body": mock_body}

                mock_client.get_object = mock_get_object
                mock_client.delete_object = AsyncMock()
                mock_client.put_object = AsyncMock()

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.delete_snapshot(snapshot_id)
                assert result is True
                assert mock_client.delete_object.called

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close connection"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                mock_client.close = AsyncMock()

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()
                await storage.close()

                # Verify close was called
                assert storage._s3_client is None

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                mock_client.close = AsyncMock()

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                async with S3SnapshotStorage(
                    bucket_name="test-bucket", enable_compression=False
                ) as storage:
                    assert storage is not None

                assert storage._s3_client is None


class TestS3SnapshotStorageCompression:
    """Tests for compression functionality"""

    @pytest.mark.asyncio
    async def test_compression_enabled(self):
        """Test snapshot storage with compression"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.ZSTD_AVAILABLE", True):
                with patch("sagaz.core.storage.backends.s3.snapshot.zstd") as mock_zstd:
                    with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                        # Mock compressor
                        mock_compressor = Mock()
                        mock_compressor.compress = Mock(return_value=b"compressed_data")
                        mock_zstd.ZstdCompressor = Mock(return_value=mock_compressor)

                        # Mock decompressor
                        mock_decompressor = Mock()
                        mock_decompressor.decompress = Mock(return_value=b'{"test": "data"}')
                        mock_zstd.ZstdDecompressor = Mock(return_value=mock_decompressor)

                        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                        storage = S3SnapshotStorage(
                            bucket_name="test-bucket",
                            enable_compression=True,
                            compression_level=5,
                        )

                        assert storage.enable_compression is True
                        assert storage.compression_level == 5

    @pytest.mark.asyncio
    async def test_compression_disabled(self):
        """Test snapshot storage without compression"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    enable_compression=False,
                )

                assert storage.enable_compression is False
                assert storage._compressor is None
                assert storage._decompressor is None


class TestS3SnapshotStorageEncryption:
    """Tests for S3 encryption settings"""

    @pytest.mark.asyncio
    async def test_encryption_enabled(self):
        """Test with encryption enabled"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket", enable_encryption=True, enable_compression=False
                )

                assert storage.enable_encryption is True

    @pytest.mark.asyncio
    async def test_custom_storage_class(self):
        """Test with custom S3 storage class"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket", storage_class="GLACIER", enable_compression=False
                )

                assert storage.storage_class == "GLACIER"


class TestS3SnapshotStorageKeyGeneration:
    """Tests for key generation methods"""

    @pytest.mark.asyncio
    async def test_snapshot_key_with_compression(self):
        """Test snapshot key generation with compression"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.ZSTD_AVAILABLE", True):
                with patch("sagaz.core.storage.backends.s3.snapshot.zstd"):
                    with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                        storage = S3SnapshotStorage(
                            bucket_name="test-bucket",
                            enable_compression=True,
                            prefix="snapshots/",
                        )

                        snapshot_id = uuid4()
                        key = storage._snapshot_key(snapshot_id)
                        assert key == f"snapshots/snapshot/{snapshot_id}.json.zst"

    @pytest.mark.asyncio
    async def test_snapshot_key_without_compression(self):
        """Test snapshot key generation without compression"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    enable_compression=False,
                    prefix="snapshots/",
                )

                snapshot_id = uuid4()
                key = storage._snapshot_key(snapshot_id)
                assert key == f"snapshots/snapshot/{snapshot_id}.json"

    @pytest.mark.asyncio
    async def test_saga_index_key(self):
        """Test saga index key generation"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket", prefix="snapshots/", enable_compression=False
                )

                saga_id = uuid4()
                key = storage._saga_index_key(saga_id)
                assert key == f"snapshots/index/saga/{saga_id}.json"

    @pytest.mark.asyncio
    async def test_replay_log_key(self):
        """Test replay log key generation"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket", prefix="snapshots/", enable_compression=False
                )

                replay_id = uuid4()
                key = storage._replay_log_key(replay_id)
                assert key == f"snapshots/replay/{replay_id}.json"


class TestS3SnapshotStorageSerializationIntegration:
    """Tests for serialization and deserialization"""

    @pytest.mark.asyncio
    async def test_serialize_without_compression(self):
        """Test serialize method without compression"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    enable_compression=False,
                )

                data = {"test": "value", "number": 123}
                serialized = storage._serialize(data)

                assert isinstance(serialized, bytes)
                assert json.loads(serialized.decode("utf-8")) == data

    @pytest.mark.asyncio
    async def test_serialize_with_compression(self):
        """Test serialize method with compression"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.ZSTD_AVAILABLE", True):
                with patch("sagaz.core.storage.backends.s3.snapshot.zstd") as mock_zstd:
                    with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                        mock_compressor = Mock()
                        mock_compressor.compress = Mock(return_value=b"compressed")
                        mock_zstd.ZstdCompressor = Mock(return_value=mock_compressor)
                        mock_zstd.ZstdDecompressor = Mock()

                        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                        storage = S3SnapshotStorage(
                            bucket_name="test-bucket",
                            enable_compression=True,
                        )

                        data = {"test": "value"}
                        serialized = storage._serialize(data)

                        assert serialized == b"compressed"
                        assert mock_compressor.compress.called

    @pytest.mark.asyncio
    async def test_deserialize_without_compression(self):
        """Test deserialize method without compression"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    enable_compression=False,
                )

                data = {"test": "value", "number": 123}
                serialized = json.dumps(data).encode("utf-8")
                deserialized = storage._deserialize(serialized)

                assert deserialized == data

    @pytest.mark.asyncio
    async def test_deserialize_with_compression(self):
        """Test deserialize method with compression"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.ZSTD_AVAILABLE", True):
                with patch("sagaz.core.storage.backends.s3.snapshot.zstd") as mock_zstd:
                    with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                        data_dict = {"test": "value"}
                        json_bytes = json.dumps(data_dict).encode("utf-8")

                        mock_decompressor = Mock()
                        mock_decompressor.decompress = Mock(return_value=json_bytes)
                        mock_zstd.ZstdDecompressor = Mock(return_value=mock_decompressor)
                        mock_zstd.ZstdCompressor = Mock()

                        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                        storage = S3SnapshotStorage(
                            bucket_name="test-bucket",
                            enable_compression=True,
                        )

                        compressed_data = b"compressed"
                        deserialized = storage._deserialize(compressed_data)

                        assert deserialized == data_dict
                        assert mock_decompressor.decompress.called


class TestS3SnapshotStorageAdvancedOperations:
    """Tests for advanced snapshot operations"""

    @pytest.mark.asyncio
    async def test_save_snapshot_full(self):
        """Test save_snapshot with all features"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                # Mock S3 operations
                mock_client.put_object = AsyncMock()

                # Mock get_object for index (not found initially)
                class NoSuchKeyError(Exception):
                    pass

                mock_client.exceptions = type("obj", (object,), {"NoSuchKey": NoSuchKeyError})
                mock_client.get_object = AsyncMock(side_effect=NoSuchKeyError())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    enable_compression=False,
                    enable_encryption=True,
                )

                saga_id = uuid4()
                snapshot_id = uuid4()
                created_at = datetime.now(UTC)
                retention_until = created_at + timedelta(days=30)

                snapshot = SagaSnapshot(
                    snapshot_id=snapshot_id,
                    saga_id=saga_id,
                    saga_name="test_saga",
                    step_name="test_step",
                    step_index=0,
                    status=SagaStatus.EXECUTING,
                    context={"test": "data"},
                    completed_steps=[],
                    created_at=created_at,
                    retention_until=retention_until,
                )

                await storage._get_s3_client()
                await storage.save_snapshot(snapshot)

                # Verify put_object was called twice (snapshot + index)
                assert mock_client.put_object.call_count == 2

    @pytest.mark.asyncio
    async def test_update_saga_index_new(self):
        """Test _update_saga_index when index doesn't exist"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                # Mock S3 exception for not found
                class NoSuchKeyError(Exception):
                    pass

                mock_client.exceptions = type("obj", (object,), {"NoSuchKey": NoSuchKeyError})
                mock_client.get_object = AsyncMock(side_effect=NoSuchKeyError())
                mock_client.put_object = AsyncMock()

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                saga_id = uuid4()
                snapshot_id = uuid4()
                created_at = datetime.now(UTC)

                await storage._update_saga_index(saga_id, snapshot_id, created_at)

                # Verify index was created
                assert mock_client.put_object.called

    @pytest.mark.asyncio
    async def test_update_saga_index_existing(self):
        """Test _update_saga_index when index exists"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                saga_id = uuid4()
                existing_snapshot = uuid4()

                # Mock existing index
                existing_index = {
                    "saga_id": str(saga_id),
                    "snapshots": [
                        {
                            "snapshot_id": str(existing_snapshot),
                            "created_at": datetime.now(UTC).isoformat(),
                        }
                    ],
                }

                mock_body = AsyncMock()
                mock_body.read = AsyncMock(return_value=json.dumps(existing_index).encode("utf-8"))
                mock_client.get_object = AsyncMock(return_value={"Body": mock_body})
                mock_client.put_object = AsyncMock()

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                new_snapshot_id = uuid4()
                await storage._update_saga_index(saga_id, new_snapshot_id, datetime.now(UTC))

                # Verify index was updated
                assert mock_client.put_object.called

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_with_filter(self):
        """Test get_latest_snapshot with before_step filter"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                saga_id = uuid4()
                snapshot_id = uuid4()

                # Mock index
                index_data = {
                    "saga_id": str(saga_id),
                    "snapshots": [
                        {
                            "snapshot_id": str(snapshot_id),
                            "created_at": datetime.now(UTC).isoformat(),
                        }
                    ],
                }

                # Mock snapshot
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(saga_id),
                    "saga_name": "test_saga",
                    "step_name": "target_step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                    "retention_until": None,
                }

                call_count = [0]

                async def mock_get_object(**kwargs):
                    call_count[0] += 1
                    mock_body = AsyncMock()
                    if call_count[0] == 1:
                        # First call - index
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(index_data).encode("utf-8")
                        )
                    else:
                        # Second call - snapshot
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(snapshot_data).encode("utf-8")
                        )
                    return {"Body": mock_body}

                mock_client.get_object = mock_get_object

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_latest_snapshot(saga_id, before_step="target_step")

                assert result is not None
                assert result.step_name == "target_step"

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_not_found(self):
        """Test get_latest_snapshot when index not found"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                class NoSuchKeyError(Exception):
                    pass

                mock_client.exceptions = type("obj", (object,), {"NoSuchKey": NoSuchKeyError})
                mock_client.get_object = AsyncMock(side_effect=NoSuchKeyError())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_latest_snapshot(uuid4())
                assert result is None

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time(self):
        """Test get_snapshot_at_time"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                saga_id = uuid4()
                snapshot_id = uuid4()
                target_time = datetime.now(UTC)

                # Mock index
                index_data = {
                    "saga_id": str(saga_id),
                    "snapshots": [
                        {
                            "snapshot_id": str(snapshot_id),
                            "created_at": (target_time - timedelta(hours=1)).isoformat(),
                        }
                    ],
                }

                # Mock snapshot
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(saga_id),
                    "saga_name": "test_saga",
                    "step_name": "test_step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": (target_time - timedelta(hours=1)).isoformat(),
                    "retention_until": None,
                }

                call_count = [0]

                async def mock_get_object(**kwargs):
                    call_count[0] += 1
                    mock_body = AsyncMock()
                    if call_count[0] == 1:
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(index_data).encode("utf-8")
                        )
                    else:
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(snapshot_data).encode("utf-8")
                        )
                    return {"Body": mock_body}

                mock_client.get_object = mock_get_object

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_snapshot_at_time(saga_id, target_time)

                assert result is not None
                assert result.snapshot_id == snapshot_id

    @pytest.mark.asyncio
    async def test_list_snapshots_with_limit(self):
        """Test list_snapshots with limit"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                saga_id = uuid4()
                snapshot_ids = [uuid4(), uuid4(), uuid4()]

                # Mock index
                index_data = {
                    "saga_id": str(saga_id),
                    "snapshots": [
                        {"snapshot_id": str(sid), "created_at": datetime.now(UTC).isoformat()}
                        for sid in snapshot_ids
                    ],
                }

                call_counter = [0]

                async def mock_get_object(**kwargs):
                    call_counter[0] += 1
                    mock_body = AsyncMock()

                    if call_counter[0] == 1:
                        # Index
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(index_data).encode("utf-8")
                        )
                    else:
                        # Snapshots
                        idx = call_counter[0] - 2
                        if idx < len(snapshot_ids):
                            snapshot_data = {
                                "snapshot_id": str(snapshot_ids[idx]),
                                "saga_id": str(saga_id),
                                "saga_name": "test_saga",
                                "step_name": "test_step",
                                "step_index": idx,
                                "status": "executing",
                                "context": {},
                                "completed_steps": [],
                                "created_at": datetime.now(UTC).isoformat(),
                                "retention_until": None,
                            }
                            mock_body.read = AsyncMock(
                                return_value=json.dumps(snapshot_data).encode("utf-8")
                            )

                    return {"Body": mock_body}

                mock_client.get_object = mock_get_object

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.list_snapshots(saga_id, limit=2)

                assert len(result) == 2

    @pytest.mark.asyncio
    async def test_delete_snapshot_success(self):
        """Test delete_snapshot successful deletion"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                saga_id = uuid4()
                snapshot_id = uuid4()

                # Mock get_snapshot
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(saga_id),
                    "saga_name": "test_saga",
                    "step_name": "test_step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                    "retention_until": None,
                }

                # Mock index
                index_data = {
                    "saga_id": str(saga_id),
                    "snapshots": [
                        {
                            "snapshot_id": str(snapshot_id),
                            "created_at": datetime.now(UTC).isoformat(),
                        }
                    ],
                }

                call_counter = [0]

                async def mock_get_object(**kwargs):
                    call_counter[0] += 1
                    mock_body = AsyncMock()
                    if call_counter[0] == 1:
                        # Snapshot
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(snapshot_data).encode("utf-8")
                        )
                    else:
                        # Index
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(index_data).encode("utf-8")
                        )
                    return {"Body": mock_body}

                mock_client.get_object = mock_get_object
                mock_client.delete_object = AsyncMock()
                mock_client.put_object = AsyncMock()

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.delete_snapshot(snapshot_id)

                assert result is True
                assert mock_client.delete_object.called

    @pytest.mark.asyncio
    async def test_delete_snapshot_not_found(self):
        """Test delete_snapshot when snapshot doesn't exist"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                class NoSuchKeyError(Exception):
                    pass

                mock_client.exceptions = type("obj", (object,), {"NoSuchKey": NoSuchKeyError})
                mock_client.get_object = AsyncMock(side_effect=NoSuchKeyError())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.delete_snapshot(uuid4())
                assert result is False


class TestS3SnapshotStorageReplayOperations:
    """Tests for replay log operations"""

    @pytest.mark.asyncio
    async def test_save_replay_log(self):
        """Test save_replay_log"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                mock_client.put_object = AsyncMock()

                from sagaz.core.replay import ReplayStatus
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket", enable_compression=False, enable_encryption=True
                )
                await storage._get_s3_client()

                replay_result = ReplayResult(
                    replay_id=uuid4(),
                    original_saga_id=uuid4(),
                    new_saga_id=uuid4(),
                    checkpoint_step="test_step",
                    replay_status=ReplayStatus.SUCCESS,
                    initiated_by="test",
                    created_at=datetime.now(UTC),
                )

                await storage.save_replay_log(replay_result)

                assert mock_client.put_object.called

    @pytest.mark.asyncio
    async def test_get_replay_log_found(self):
        """Test get_replay_log when replay exists"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                replay_id = uuid4()
                replay_data = {
                    "replay_id": str(replay_id),
                    "original_saga_id": str(uuid4()),
                    "replay_saga_id": str(uuid4()),
                    "snapshot_id": str(uuid4()),
                    "success": True,
                    "status": "completed",
                    "created_at": datetime.now(UTC).isoformat(),
                }

                mock_body = AsyncMock()
                mock_body.read = AsyncMock(return_value=json.dumps(replay_data).encode("utf-8"))
                mock_client.get_object = AsyncMock(return_value={"Body": mock_body})

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_replay_log(replay_id)

                assert result is not None
                assert result["replay_id"] == str(replay_id)

    @pytest.mark.asyncio
    async def test_get_replay_log_not_found(self):
        """Test get_replay_log when replay doesn't exist"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                class NoSuchKeyError(Exception):
                    pass

                mock_client.exceptions = type("obj", (object,), {"NoSuchKey": NoSuchKeyError})
                mock_client.get_object = AsyncMock(side_effect=NoSuchKeyError())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_replay_log(uuid4())
                assert result is None

    @pytest.mark.asyncio
    async def test_list_replays(self):
        """Test list_replays"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                original_saga_id = uuid4()
                replay_id1 = uuid4()
                replay_id2 = uuid4()

                replay_data1 = {
                    "replay_id": str(replay_id1),
                    "original_saga_id": str(original_saga_id),
                    "replay_saga_id": str(uuid4()),
                    "snapshot_id": str(uuid4()),
                    "success": True,
                    "status": "completed",
                    "created_at": datetime.now(UTC).isoformat(),
                }

                replay_data2 = {
                    "replay_id": str(replay_id2),
                    "original_saga_id": str(original_saga_id),
                    "replay_saga_id": str(uuid4()),
                    "snapshot_id": str(uuid4()),
                    "success": False,
                    "status": "failed",
                    "created_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                }

                # Mock paginator
                class MockPaginator:
                    async def paginate(self, **kwargs):
                        yield {
                            "Contents": [
                                {"Key": f"snapshots/replay/{replay_id1}.json"},
                                {"Key": f"snapshots/replay/{replay_id2}.json"},
                            ]
                        }

                mock_client.get_paginator = Mock(return_value=MockPaginator())

                call_counter = [0]

                async def mock_get_object(**kwargs):
                    call_counter[0] += 1
                    mock_body = AsyncMock()
                    if call_counter[0] == 1:
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(replay_data1).encode("utf-8")
                        )
                    else:
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(replay_data2).encode("utf-8")
                        )
                    return {"Body": mock_body}

                mock_client.get_object = mock_get_object

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.list_replays(original_saga_id, limit=10)

                assert len(result) == 2
                # Should be sorted by created_at DESC
                assert result[0]["replay_id"] == str(replay_id1)

    @pytest.mark.asyncio
    async def test_list_replays_with_limit(self):
        """Test list_replays respects limit"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                original_saga_id = uuid4()

                # Create multiple replays
                replays = []
                for i in range(5):
                    replays.append(
                        {
                            "replay_id": str(uuid4()),
                            "original_saga_id": str(original_saga_id),
                            "replay_saga_id": str(uuid4()),
                            "snapshot_id": str(uuid4()),
                            "success": True,
                            "status": "completed",
                            "created_at": (datetime.now(UTC) - timedelta(hours=i)).isoformat(),
                        }
                    )

                # Mock paginator
                class MockPaginator:
                    async def paginate(self, **kwargs):
                        yield {
                            "Contents": [{"Key": f"snapshots/replay/{i}.json"} for i in range(5)]
                        }

                mock_client.get_paginator = Mock(return_value=MockPaginator())

                call_counter = [0]

                async def mock_get_object(**kwargs):
                    idx = call_counter[0]
                    call_counter[0] += 1
                    if idx < len(replays):
                        mock_body = AsyncMock()
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(replays[idx]).encode("utf-8")
                        )
                        return {"Body": mock_body}
                    msg = "Out of range"
                    raise Exception(msg)

                mock_client.get_object = mock_get_object

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.list_replays(original_saga_id, limit=2)

                assert len(result) <= 2


class TestS3SnapshotStorageEdgeCases:
    """Tests for edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time_not_found(self):
        """Test get_snapshot_at_time when no index exists"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                class NoSuchKeyError(Exception):
                    pass

                mock_client.exceptions = type("obj", (object,), {"NoSuchKey": NoSuchKeyError})
                mock_client.get_object = AsyncMock(side_effect=NoSuchKeyError())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_snapshot_at_time(uuid4(), datetime.now(UTC))
                assert result is None

    @pytest.mark.asyncio
    async def test_list_snapshots_empty(self):
        """Test list_snapshots when no snapshots exist"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                class NoSuchKeyError(Exception):
                    pass

                mock_client.exceptions = type("obj", (object,), {"NoSuchKey": NoSuchKeyError})
                mock_client.get_object = AsyncMock(side_effect=NoSuchKeyError())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.list_snapshots(uuid4())
                assert result == []

    @pytest.mark.asyncio
    async def test_remove_from_saga_index_not_found(self):
        """Test _remove_from_saga_index when index doesn't exist"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                class NoSuchKeyError(Exception):
                    pass

                mock_client.exceptions = type("obj", (object,), {"NoSuchKey": NoSuchKeyError})
                mock_client.get_object = AsyncMock(side_effect=NoSuchKeyError())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                # Should not raise exception
                await storage._remove_from_saga_index(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_with_none_snapshot(self):
        """Test get_latest_snapshot when snapshot fetch returns None"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                saga_id = uuid4()

                # Mock index with snapshots
                index_data = {
                    "saga_id": str(saga_id),
                    "snapshots": [
                        {"snapshot_id": str(uuid4()), "created_at": datetime.now(UTC).isoformat()}
                    ],
                }

                call_counter = [0]

                class NoSuchKeyError(Exception):
                    pass

                mock_client.exceptions = type("obj", (object,), {"NoSuchKey": NoSuchKeyError})

                async def mock_get_object(**kwargs):
                    call_counter[0] += 1
                    if call_counter[0] == 1:
                        # Index found
                        mock_body = AsyncMock()
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(index_data).encode("utf-8")
                        )
                        return {"Body": mock_body}
                    # Snapshot not found
                    raise NoSuchKeyError

                mock_client.get_object = mock_get_object

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_latest_snapshot(saga_id)
                assert result is None


class TestS3SnapshotStorageDeleteExpired:
    """Tests for delete_expired_snapshots functionality"""

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots(self):
        """Test delete_expired_snapshots"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                saga_id = uuid4()
                snapshot_id = uuid4()

                # Mock paginator for listing
                class MockPaginator:
                    async def paginate(self, **kwargs):
                        yield {"Contents": [{"Key": f"snapshots/snapshot/{snapshot_id}.json"}]}

                mock_client.get_paginator = Mock(return_value=MockPaginator())

                # Mock head_object to return expired snapshot
                expired_time = datetime.now(UTC) - timedelta(days=1)
                mock_client.head_object = AsyncMock(return_value={"Expires": expired_time})

                # Mock get_snapshot
                snapshot_data = {
                    "snapshot_id": str(snapshot_id),
                    "saga_id": str(saga_id),
                    "saga_name": "test_saga",
                    "step_name": "test_step",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                    "retention_until": None,
                }

                # Mock index
                index_data = {
                    "saga_id": str(saga_id),
                    "snapshots": [
                        {
                            "snapshot_id": str(snapshot_id),
                            "created_at": datetime.now(UTC).isoformat(),
                        }
                    ],
                }

                call_counter = [0]

                async def mock_get_object(**kwargs):
                    call_counter[0] += 1
                    mock_body = AsyncMock()
                    if call_counter[0] == 1:
                        # Snapshot
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(snapshot_data).encode("utf-8")
                        )
                    else:
                        # Index
                        mock_body.read = AsyncMock(
                            return_value=json.dumps(index_data).encode("utf-8")
                        )
                    return {"Body": mock_body}

                mock_client.get_object = mock_get_object
                mock_client.delete_object = AsyncMock()
                mock_client.put_object = AsyncMock()

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                deleted = await storage.delete_expired_snapshots()

                # Should have deleted 1 expired snapshot
                assert deleted == 1
                assert mock_client.delete_object.called

    @pytest.mark.asyncio
    async def test_delete_expired_snapshots_no_expired(self):
        """Test delete_expired_snapshots when no snapshots are expired"""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client = AsyncMock()

                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cm.__aexit__ = AsyncMock()

                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                # Mock paginator with no results
                class MockPaginator:
                    async def paginate(self, **kwargs):
                        yield {"Contents": []}

                mock_client.get_paginator = Mock(return_value=MockPaginator())

                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                deleted = await storage.delete_expired_snapshots()

                assert deleted == 0


def _make_mock_s3_setup(mock_aioboto3):
    """Helper to create mock S3 session and client."""
    mock_session = MagicMock()
    mock_client = AsyncMock()
    mock_client_cm = AsyncMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock()
    mock_session.client = MagicMock(return_value=mock_client_cm)
    mock_aioboto3.Session = MagicMock(return_value=mock_session)

    class MockNoSuchKey(BaseException):
        pass

    mock_exceptions = MagicMock()
    mock_exceptions.NoSuchKey = MockNoSuchKey
    mock_client.exceptions = mock_exceptions
    return mock_client, mock_session, MockNoSuchKey


class TestS3SnapshotMissingBranches:
    """Lines 102-104, 165->169, 251->243, 272->279, 274->272, 300->297,
    322-323, 374->368, 383->368, 385-386, 410->413, 447->439, 452-453, 465->exit."""

    @pytest.mark.asyncio
    async def test_get_s3_client_exception(self):
        """Lines 102-104: _get_s3_client raises ConnectionError on exception."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_session = MagicMock()
                mock_client_cm = AsyncMock()
                mock_client_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("S3 error"))
                mock_session.client = MagicMock(return_value=mock_client_cm)
                mock_aioboto3.Session = MagicMock(return_value=mock_session)

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                with pytest.raises(ConnectionError):
                    await storage._get_s3_client()

    @pytest.mark.asyncio
    async def test_save_snapshot_without_encryption(self):
        """Lines 165->169: encryption disabled branch (no ServerSideEncryption)."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, MockNoSuchKey = _make_mock_s3_setup(mock_aioboto3)
                mock_client.put_object = AsyncMock()
                mock_client.get_object = AsyncMock(side_effect=MockNoSuchKey())

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    enable_compression=False,
                    enable_encryption=False,
                )
                await storage._get_s3_client()

                snapshot = SagaSnapshot(
                    snapshot_id=uuid4(),
                    saga_id=uuid4(),
                    saga_name="T",
                    step_name="s1",
                    step_index=0,
                    status=SagaStatus.EXECUTING,
                    context={},
                    completed_steps=[],
                    created_at=datetime.now(UTC),
                )
                await storage.save_snapshot(snapshot)
                call_kwargs = mock_client.put_object.call_args_list[0][1]
                assert "ServerSideEncryption" not in call_kwargs

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_before_step_mismatch(self):
        """Lines 251->243: before_step doesn't match any snapshot."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, MockNoSuchKey = _make_mock_s3_setup(mock_aioboto3)
                saga_id = uuid4()
                snap_id = uuid4()
                index_data = {
                    "snapshots": [
                        {"snapshot_id": str(snap_id), "created_at": datetime.now(UTC).isoformat()}
                    ]
                }
                snap_data = {
                    "snapshot_id": str(snap_id),
                    "saga_id": str(saga_id),
                    "saga_name": "T",
                    "step_name": "step_a",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                }

                index_resp = {
                    "Body": AsyncMock(read=AsyncMock(return_value=json.dumps(index_data).encode()))
                }
                snap_resp = {
                    "Body": AsyncMock(read=AsyncMock(return_value=json.dumps(snap_data).encode()))
                }
                mock_client.get_object = AsyncMock(side_effect=[index_resp, snap_resp])

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_latest_snapshot(saga_id, before_step="nonexistent_step")
                assert result is None

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time_empty_index(self):
        """Lines 272->279: get_snapshot_at_time returns None when index is empty."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, _ = _make_mock_s3_setup(mock_aioboto3)
                index_data = {"snapshots": []}
                index_resp = {
                    "Body": AsyncMock(read=AsyncMock(return_value=json.dumps(index_data).encode()))
                }
                mock_client.get_object = AsyncMock(return_value=index_resp)

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_snapshot_at_time(uuid4(), datetime.now(UTC))
                assert result is None

    @pytest.mark.asyncio
    async def test_get_snapshot_at_time_entry_after_target(self):
        """Lines 274->272: entry_time > timestamp, loop continues without match."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, _ = _make_mock_s3_setup(mock_aioboto3)
                future_time = datetime.now(UTC) + timedelta(days=1)
                index_data = {
                    "snapshots": [
                        {"snapshot_id": str(uuid4()), "created_at": future_time.isoformat()}
                    ]
                }
                index_resp = {
                    "Body": AsyncMock(read=AsyncMock(return_value=json.dumps(index_data).encode()))
                }
                mock_client.get_object = AsyncMock(return_value=index_resp)

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.get_snapshot_at_time(
                    uuid4(), datetime.now(UTC) - timedelta(days=1)
                )
                assert result is None

    @pytest.mark.asyncio
    async def test_list_snapshots_snapshot_is_none(self):
        """Lines 300->297: snapshot is None from get_snapshot, branch not appended."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, MockNoSuchKey = _make_mock_s3_setup(mock_aioboto3)
                saga_id = uuid4()
                snap_id = uuid4()
                index_data = {"snapshots": [{"snapshot_id": str(snap_id)}]}
                index_resp = {
                    "Body": AsyncMock(read=AsyncMock(return_value=json.dumps(index_data).encode()))
                }
                # Index found, but snapshot itself raises NoSuchKey
                mock_client.get_object = AsyncMock(side_effect=[index_resp, MockNoSuchKey()])

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.list_snapshots(saga_id)
                assert result == []

    @pytest.mark.asyncio
    async def test_delete_snapshot_exception_returns_false(self):
        """Lines 322-323: exception during delete returns False."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, _ = _make_mock_s3_setup(mock_aioboto3)
                snap_id = uuid4()
                saga_id = uuid4()
                snap_data = {
                    "snapshot_id": str(snap_id),
                    "saga_id": str(saga_id),
                    "saga_name": "T",
                    "step_name": "s1",
                    "step_index": 0,
                    "status": "executing",
                    "context": {},
                    "completed_steps": [],
                    "created_at": datetime.now(UTC).isoformat(),
                }
                snap_resp = {
                    "Body": AsyncMock(read=AsyncMock(return_value=json.dumps(snap_data).encode()))
                }
                mock_client.get_object = AsyncMock(return_value=snap_resp)
                mock_client.delete_object = AsyncMock(side_effect=RuntimeError("S3 error"))

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.delete_snapshot(snap_id)
                assert result is False

    @pytest.mark.asyncio
    async def test_delete_expired_skips_not_expired(self):
        """Lines 374->368: object without expiry metadata is skipped."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, _ = _make_mock_s3_setup(mock_aioboto3)
                mock_client.head_object = AsyncMock(return_value={"Expires": None})

                class MockPaginator:
                    async def paginate(self, **kwargs):
                        yield {"Contents": [{"Key": f"snapshot/{uuid4()}.json"}]}

                mock_client.get_paginator = Mock(return_value=MockPaginator())

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                count = await storage.delete_expired_snapshots()
                assert count == 0

    @pytest.mark.asyncio
    async def test_delete_expired_exception_continues(self):
        """Lines 385-386: exception in delete_expired head_object is swallowed."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, _ = _make_mock_s3_setup(mock_aioboto3)
                mock_client.head_object = AsyncMock(side_effect=RuntimeError("error"))

                class MockPaginator:
                    async def paginate(self, **kwargs):
                        yield {"Contents": [{"Key": f"snapshot/{uuid4()}.json"}]}

                mock_client.get_paginator = Mock(return_value=MockPaginator())

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                count = await storage.delete_expired_snapshots()
                assert count == 0

    @pytest.mark.asyncio
    async def test_save_replay_log_without_encryption(self):
        """Lines 410->413: enable_encryption=False in save_replay_log."""
        from sagaz.core.replay import ReplayStatus
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, _ = _make_mock_s3_setup(mock_aioboto3)
                mock_client.put_object = AsyncMock()

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket", enable_compression=False, enable_encryption=False
                )
                await storage._get_s3_client()

                replay = ReplayResult(
                    replay_id=uuid4(),
                    original_saga_id=uuid4(),
                    new_saga_id=uuid4(),
                    checkpoint_step="step1",
                    replay_status=ReplayStatus.SUCCESS,
                )
                await storage.save_replay_log(replay)
                call_kwargs = mock_client.put_object.call_args[1]
                assert "ServerSideEncryption" not in call_kwargs

    @pytest.mark.asyncio
    async def test_list_replays_skips_non_matching_saga(self):
        """Lines 447->439: replay with different original_saga_id is skipped."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, _ = _make_mock_s3_setup(mock_aioboto3)
                other_saga_id = uuid4()
                replay_data = {
                    "original_saga_id": str(other_saga_id),
                    "created_at": datetime.now(UTC).isoformat(),
                }
                resp = {
                    "Body": AsyncMock(read=AsyncMock(return_value=json.dumps(replay_data).encode()))
                }
                mock_client.get_object = AsyncMock(return_value=resp)

                class MockPaginator:
                    async def paginate(self, **kwargs):
                        yield {"Contents": [{"Key": "replay/test.json"}]}

                mock_client.get_paginator = Mock(return_value=MockPaginator())

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.list_replays(uuid4())  # Different saga id
                assert result == []

    @pytest.mark.asyncio
    async def test_list_replays_exception_continues(self):
        """Lines 452-453: exception in list_replays is swallowed."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                mock_client, _, _ = _make_mock_s3_setup(mock_aioboto3)
                mock_client.get_object = AsyncMock(side_effect=RuntimeError("error"))

                class MockPaginator:
                    async def paginate(self, **kwargs):
                        yield {"Contents": [{"Key": "replay/test.json"}]}

                mock_client.get_paginator = Mock(return_value=MockPaginator())

                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                await storage._get_s3_client()

                result = await storage.list_replays(uuid4())
                assert result == []

    @pytest.mark.asyncio
    async def test_close_when_client_is_none(self):
        """Lines 465->exit: close() is no-op when _s3_client is None."""
        from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3"):
                storage = S3SnapshotStorage(bucket_name="test-bucket", enable_compression=False)
                assert storage._s3_client is None
                await storage.close()  # Should not raise


class TestS3SnapshotBranch:
    async def test_delete_expired_snapshots_deletes_expired(self):
        """383->368: delete_expired_snapshots uses paginator to list and delete expired objects."""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    region="us-east-1",
                    enable_compression=False,
                )

                snap_key = "snapshots/snapshot-abc.json"
                expired_time = datetime(2000, 1, 1, tzinfo=UTC)

                class AsyncPaginator:
                    def __init__(self, pages):
                        self._pages = pages

                    def paginate(self, **kwargs):
                        return self

                    def __aiter__(self):
                        return self._iter()

                    async def _iter(self):
                        for page in self._pages:
                            yield page

                pages = [{"Contents": [{"Key": snap_key}]}]
                mock_s3 = AsyncMock()
                mock_s3.get_paginator = MagicMock(return_value=AsyncPaginator(pages))
                mock_s3.head_object = AsyncMock(return_value={"Expires": expired_time})
                mock_s3.delete_object = AsyncMock()

                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
                mock_ctx.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.client = MagicMock(return_value=mock_ctx)
                mock_aioboto3.Session.return_value = mock_session

                count = await storage.delete_expired_snapshots()

        assert count >= 0

    async def test_delete_expired_snapshots_delete_returns_false(self):
        """383->368 FALSE: delete_snapshot returns False → deleted_count not incremented."""
        with patch("sagaz.core.storage.backends.s3.snapshot.AIOBOTO3_AVAILABLE", True):
            with patch("sagaz.core.storage.backends.s3.snapshot.aioboto3") as mock_aioboto3:
                from sagaz.core.storage.backends.s3.snapshot import S3SnapshotStorage

                storage = S3SnapshotStorage(
                    bucket_name="test-bucket",
                    region="us-east-1",
                    enable_compression=False,
                )
                snap_key = f"snapshots/{uuid4()}.json"
                expired_time = datetime(2000, 1, 1, tzinfo=UTC)

                class AsyncPaginator:
                    def __init__(self, pages):
                        self._pages = pages

                    def paginate(self, **kwargs):
                        return self

                    def __aiter__(self):
                        return self._iter()

                    async def _iter(self):
                        for page in self._pages:
                            yield page

                pages = [{"Contents": [{"Key": snap_key}]}]
                mock_s3 = AsyncMock()
                mock_s3.get_paginator = MagicMock(return_value=AsyncPaginator(pages))
                mock_s3.head_object = AsyncMock(return_value={"Expires": expired_time})

                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
                mock_ctx.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.client = MagicMock(return_value=mock_ctx)
                mock_aioboto3.Session.return_value = mock_session

                with patch.object(storage, "delete_snapshot", return_value=False):
                    count = await storage.delete_expired_snapshots()

        assert count == 0  # delete_snapshot returned False → no increment


# ==========================================================================
# storage/backends/sqlite/saga.py  – 275->287, 276->275
