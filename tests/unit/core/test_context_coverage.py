
import asyncio
import os
import shutil
import tempfile
import pickle
from typing import AsyncGenerator

import pytest

from sagaz.core.context import (
    ExternalReference,
    FileSystemExternalStorage,
    SagaContext,
    ExternalStorage,
)


class TestContextCoverage:
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
            saga_id="test-coverage",
            storage=fs_storage,
            auto_offload=True,
            offload_threshold=10, 
        )
        return ctx

    @pytest.mark.asyncio
    async def test_fs_storage_invalid_uri_load(self, fs_storage):
        """Test loading with invalid URI scheme."""
        with pytest.raises(ValueError):
            await fs_storage.load("invalid://path")

    @pytest.mark.asyncio
    async def test_fs_storage_file_not_found(self, fs_storage):
        """Test loading non-existent file."""
        with pytest.raises(FileNotFoundError):
            await fs_storage.load("file:///non/existent/path")

    @pytest.mark.asyncio
    async def test_fs_storage_invalid_uri_delete(self, fs_storage):
        """Test deleting with invalid URI scheme."""
        # Should simple return None/do nothing
        await fs_storage.delete("invalid://path")

    @pytest.mark.asyncio
    async def test_fs_storage_delete_non_existent(self, fs_storage):
        """Test deleting non-existent file (should be safe)."""
        await fs_storage.delete("file:///non/existent/path")

    @pytest.mark.asyncio
    async def test_set_async_without_offload(self):
        """Test set_async when auto-offload is disabled or no backend."""
        ctx = SagaContext()
        # No backend configured
        await ctx.set_async("key", "value")
        # Should be stored in data
        assert ctx.data["key"] == "value"
        assert "key" not in ctx.external_refs

    @pytest.mark.asyncio
    async def test_get_async_stream(self, context):
        """Test get_async returns stream if present."""
        async def my_stream() -> AsyncGenerator[int, None]:
            yield 1

        context.register_stream("stream", my_stream())
        val = await context.get_async("stream")
        assert isinstance(val, AsyncGenerator)

    @pytest.mark.asyncio
    async def test_get_async_ref_load_fallback(self, context, fs_storage):
        """Test get_async loads from standard data if marker present."""
        # Store something externally manually
        ref = await fs_storage.store("test-coverage", "key", "value")
        
        # Manually put marker in data
        context.data["key"] = {"_external_ref": ref.uri}
        
        # get_async should resolve it even if not in external_refs
        val = await context.get_async("key")
        assert val == "value"

    @pytest.mark.asyncio
    async def test_get_async_default(self, context):
        """Test get_async default value."""
        val = await context.get_async("missing", "default")
        assert val == "default"

    @pytest.mark.asyncio
    async def test_store_external_no_backend(self):
        """Test store_external with no backend raises error."""
        ctx = SagaContext()
        with pytest.raises(RuntimeError):
            await ctx.store_external("key", "value")

    @pytest.mark.asyncio
    async def test_load_external_no_backend(self):
        """Test load_external with no backend raises error."""
        ctx = SagaContext()
        with pytest.raises(RuntimeError):
            await ctx.load_external("key")

    @pytest.mark.asyncio
    async def test_load_external_key_not_found(self, context):
        """Test load_external with missing key."""
        with pytest.raises(KeyError):
            await context.load_external("missing")

    @pytest.mark.asyncio
    async def test_should_offload_exception(self, context):
        """Test _should_offload handles exceptions gracefully."""
        
        class Unpicklable:
            def __getstate__(self):
                raise Exception("Cannot pickle")
        
        # Should return False instead of raising
        assert context._should_offload(Unpicklable()) is False

    @pytest.mark.asyncio
    async def test_estimate_size_bytes(self, context):
        """Test _estimate_size with bytes."""
        assert context._estimate_size(b"12345") == 5

    @pytest.mark.asyncio
    async def test_estimate_size_pickle(self, context):
        """Test _estimate_size fallback to pickle."""
        data = {"a": 1} # dict falls back to pickle
        size = len(pickle.dumps(data))
        assert context._estimate_size(data) == size

    @pytest.mark.asyncio
    async def test_estimate_size_str(self, context):
        """Test _estimate_size with string."""
        assert context._estimate_size("abc") == 3

    @pytest.mark.asyncio
    async def test_set_sync_stream(self, context):
        """Test set (sync) correctly registers stream."""
        async def gen(): yield 1
        g = gen()
        context.set("stream_key", g)
        assert "stream_key" in context._streams
        # Should NOT be in data
        assert "stream_key" not in context.data

    @pytest.mark.asyncio
    async def test_set_async_stream(self, context):
        """Test set_async correctly registers stream."""
        async def gen(): yield 1
        g = gen()
        await context.set_async("async_stream", g)
        assert "async_stream" in context._streams

    @pytest.mark.asyncio
    async def test_get_sync_stream(self, context):
        """Test get (sync) returns stream."""
        async def gen(): yield 1
        g = gen()
        context.register_stream("stream_key", g)
        assert context.get("stream_key") is g

    @pytest.mark.asyncio
    async def test_stream_access(self, context):
        """Test stream() method success and failure."""
        async def gen(): yield 1
        g = gen()
        context.register_stream("k", g)
        assert context.stream("k") is g
        
        with pytest.raises(KeyError):
            context.stream("missing")

    @pytest.mark.asyncio
    async def test_has_checks(self, context):
        """Test has() checks all sources."""
        context.data["d"] = 1
        async def gen(): yield 1
        context.register_stream("s", gen())
        # Mock external ref
        context.external_refs["e"] = "ref" 
        
        assert context.has("d")
        assert context.has("s")
        assert context.has("e")
        assert not context.has("missing")

    @pytest.mark.asyncio
    async def test_set_sync_normal(self, context):
        """Test set (sync) with normal value."""
        context.set("key", "value")
        assert context.data["key"] == "value"

    @pytest.mark.asyncio
    async def test_get_sync_normal(self, context):
        """Test get (sync) with normal value."""
        context.data["key"] = "value"
        assert context.get("key") == "value"

    @pytest.mark.asyncio
    async def test_set_async_offload(self, context):
        """Test set_async with offloading enabled."""
        # Threshold is 10 (from fixture)
        large_val = "x" * 20
        await context.set_async("large", large_val)
        
        assert "large" in context.external_refs
        assert context.data["large"]["_external_ref"].startswith("file://")

    @pytest.mark.asyncio
    async def test_get_async_external_ref(self, context):
        """Test get_async with existing external ref."""
        # Store directly first
        large_val = "x" * 20
        await context.set_async("large", large_val)
        
        # Get async
        val = await context.get_async("large")
        assert val == large_val

    @pytest.mark.asyncio
    async def test_load_external_marker_direct(self, context, fs_storage):
        """Test load_external directly when ref is missing but marker exists."""
        # Simulate marker presence without external_ref entry
        ref = await fs_storage.store("test-coverage", "k", "v")
        context.data["k"] = {"_external_ref": ref.uri}
        
        # load_external should find it via marker
        val = await context.load_external("k")
        assert val == "v"

    @pytest.mark.asyncio
    async def test_should_offload_logic(self, context):
        """Test _should_offload logic."""
        # Threshold is 10
        assert context._should_offload("small") is False
        assert context._should_offload("larger_than_ten_chars") is True

