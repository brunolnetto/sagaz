import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.core.context import HAS_AIOBOTO3, S3ExternalStorage


# 1. Test missing aioboto3
def test_init_raises_if_missing_aioboto3():
    with patch("sagaz.core.context.HAS_AIOBOTO3", False):
        with pytest.raises(ImportError, match="aioboto3 is required"):
            S3ExternalStorage("bucket")


# 2. Test malformed S3 URIs
@pytest.mark.skipif(not HAS_AIOBOTO3, reason="aioboto3 not installed")
class TestS3MalformedURIs:
    @pytest.fixture
    def s3_storage(self):
        # Clean mock without needing full session logic for these simple tests
        return S3ExternalStorage("bucket")

    @pytest.mark.asyncio
    async def test_load_malformed_uri(self, s3_storage):
        # Missing slash separator
        with pytest.raises(ValueError, match="Invalid S3 URI format"):
            await s3_storage.load("s3://bucket_only")

    @pytest.mark.asyncio
    async def test_delete_malformed_uri_ignored(self, s3_storage):
        # Should just return logic
        await s3_storage.delete("s3://bucket_only")


# 3. Test S3 client errors
@pytest.mark.skipif(not HAS_AIOBOTO3, reason="aioboto3 not installed")
class TestS3Errors:
    @pytest.fixture
    def mock_s3_client(self):
        mock = AsyncMock()
        mock.__aenter__.return_value = mock
        mock.__aexit__.return_value = None
        return mock

    @pytest.fixture
    def mock_session(self, mock_s3_client):
        session = MagicMock()
        session.client.return_value = mock_s3_client
        return session

    @pytest.fixture
    def s3_storage(self, mock_session):
        with patch("sagaz.core.context.aioboto3.Session", return_value=mock_session):
            yield S3ExternalStorage("bucket")

    @pytest.mark.asyncio
    async def test_load_nosuchkey_raises_filenotfound(self, s3_storage, mock_s3_client):
        # Simulate AccessDenied or NoSuchKey as generic ClientError
        # In real boto3, this is a ClientError with Error code
        # Here we simulate the Exception message check logic
        mock_s3_client.get_object.side_effect = Exception(
            "An error occurred (NoSuchKey) when calling..."
        )

        with pytest.raises(FileNotFoundError, match="S3 object not found"):
            await s3_storage.load("s3://bucket/key")

    @pytest.mark.asyncio
    async def test_load_other_error_raises(self, s3_storage, mock_s3_client):
        mock_s3_client.get_object.side_effect = Exception("Some other S3 error")

        with pytest.raises(Exception, match="Some other S3 error"):
            await s3_storage.load("s3://bucket/key")
