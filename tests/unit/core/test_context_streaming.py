
import asyncio
import os
import pickle
import shutil
import tempfile
from typing import AsyncGenerator

import pytest

from sagaz.core.context import (
    ExternalReference,
    FileSystemExternalStorage,
    SagaContext,
)


class TestContextStreaming:
    @pytest.fixture
    def temp_storage_path(self):
        path = tempfile.mkdtemp()
        yield path
        shutil.rmtree(path)

    @pytest.fixture
    def fs_storage(self, temp_storage_path):
        return FileSystemExternalStorage(temp_storage_path)

    @pytest.fixture
    def context(self, fs_storage):
        ctx = SagaContext()
        ctx.configure(
            saga_id="test-saga-123",
            storage=fs_storage,
            auto_offload=True,
            offload_threshold=100,  # Small threshold for testing
        )
        return ctx

    @pytest.mark.asyncio
    async def test_external_storage_manual(self, context, fs_storage):
        """Test manual storage of external references."""
        large_data = b"x" * 1024  # 1KB
        
        # Store
        ref = await context.store_external("manual_key", large_data)
        
        assert isinstance(ref, ExternalReference)
        assert ref.size_bytes == len(pickle.dumps(large_data))
        assert ref.uri.startswith("file://")
        assert "manual_key" in context.external_refs
        
        # Load
        loaded_data = await context.load_external("manual_key")
        assert loaded_data == large_data

    @pytest.mark.asyncio
    async def test_auto_offload(self, context):
        """Test automatic offloading of large values."""
        # Small value - should stay in memory
        small_val = "small"
        await context.set_async("small_key", small_val)
        assert context.data["small_key"] == "small"
        assert "small_key" not in context.external_refs
        
        # Large value - should offload (threshold is 100 bytes)
        large_val = "x" * 200
        await context.set_async("large_key", large_val)
        
        # Check it was offloaded
        assert "large_key" in context.external_refs
        assert isinstance(context.data["large_key"], dict)
        assert "_external_ref" in context.data["large_key"]
        
        # Check transparent retrieval
        retrieved_val = await context.get_async("large_key")
        assert retrieved_val == large_val

    @pytest.mark.asyncio
    async def test_streaming_generator(self, context):
        """Test passing async generators via context."""
        
        async def my_stream() -> AsyncGenerator[int, None]:
            for i in range(5):
                yield i
                await asyncio.sleep(0.01)

        # Register stream
        gen = my_stream()
        context.set("numbers", gen)
        
        # Verify stored in streams but not data
        assert "numbers" in context._streams
        assert "numbers" not in context.data
        
        # Consume stream
        stream = context.stream("numbers")
        results = []
        async for item in stream:
            results.append(item)
            
        assert results == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_mixed_access_patterns(self, context):
        """Test mix of direct access, external access, and defaults."""
        context.set("a", 1)
        
        # Standard get
        assert context.get("a") == 1
        
        # Missing key default
        assert context.get("missing", "default") == "default"
        
        # Missing external key
        with pytest.raises(KeyError):
            await context.load_external("missing_ref")
            
        # Missing stream
        with pytest.raises(KeyError):
            context.stream("missing_stream")

    @pytest.mark.asyncio
    async def test_filesystem_storage_invalid_uri(self, fs_storage):
        """Test error handling for invalid URIs."""
        with pytest.raises(ValueError):
            await fs_storage.load("s3://bucket/key")

    @pytest.mark.asyncio
    async def test_filesystem_storage_delete(self, fs_storage):
        """Test deleting external files."""
        # Store something manually
        ref = await fs_storage.store("saga-1", "key", "value")
        path = ref.uri[7:]
        assert os.path.exists(path)
        
        # Delete
        await fs_storage.delete(ref.uri)
        assert not os.path.exists(path)

