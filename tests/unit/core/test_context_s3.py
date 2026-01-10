import asyncio
import pickle
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.core.context import HAS_AIOBOTO3, S3ExternalStorage


@pytest.mark.skipif(not HAS_AIOBOTO3, reason="aioboto3 not installed")
class TestS3Storage:
    @pytest.fixture
    def mock_s3_client(self):
        mock = AsyncMock()
        # Mock context manager
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
        # We patch where it is looked up: sagaz.core.context.aioboto3
        # Ensure we patch the Session class on that module
        with patch("sagaz.core.context.aioboto3.Session", return_value=mock_session):
            yield S3ExternalStorage(bucket="test-bucket")

    @pytest.mark.asyncio
    async def test_store_calls_put_object(self, s3_storage, mock_s3_client):
        value = {"foo": "bar"}
        val_bytes = pickle.dumps(value)

        ref = await s3_storage.store("saga-1", "key", value)

        assert ref.uri.startswith("s3://test-bucket/saga-1/")

        mock_s3_client.put_object.assert_called_once()
        call_args = mock_s3_client.put_object.call_args[1]
        assert call_args["Bucket"] == "test-bucket"
        assert call_args["Body"] == val_bytes
        assert call_args["Metadata"]["saga_id"] == "saga-1"

    @pytest.mark.asyncio
    async def test_load_calls_get_object(self, s3_storage, mock_s3_client):
        value = {"foo": "bar"}
        val_bytes = pickle.dumps(value)

        # Mock response body
        mock_body = AsyncMock()
        mock_body.read.return_value = val_bytes
        mock_body.__aenter__.return_value = mock_body
        mock_body.__aexit__.return_value = None

        mock_s3_client.get_object.return_value = {"Body": mock_body}

        uri = "s3://test-bucket/saga-1/key-123.bin"
        loaded = await s3_storage.load(uri)

        assert loaded == value
        mock_s3_client.get_object.assert_called_with(Bucket="test-bucket", Key="saga-1/key-123.bin")

    @pytest.mark.asyncio
    async def test_load_wrong_bucket_raises_error(self, s3_storage):
        with pytest.raises(ValueError, match="does not match configured bucket"):
            await s3_storage.load("s3://other-bucket/key")

    @pytest.mark.asyncio
    async def test_load_invalid_scheme_raises_error(self, s3_storage):
        with pytest.raises(ValueError, match="Invalid URI scheme"):
            await s3_storage.load("file://test-bucket/key")

    @pytest.mark.asyncio
    async def test_delete_calls_delete_object(self, s3_storage, mock_s3_client):
        uri = "s3://test-bucket/key.bin"
        await s3_storage.delete(uri)

        mock_s3_client.delete_object.assert_called_with(Bucket="test-bucket", Key="key.bin")

    @pytest.mark.asyncio
    async def test_delete_ignores_invalid_and_wrong_bucket(self, s3_storage, mock_s3_client):
        await s3_storage.delete("file://test")
        await s3_storage.delete("s3://other-bucket/key")

        mock_s3_client.delete_object.assert_not_called()
