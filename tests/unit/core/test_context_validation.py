"""
Tests for context memory validation and warning system.
"""

import tempfile
import warnings
from pathlib import Path

import pytest

from sagaz.core.context import (
    ConfigurationError,
    FileSystemExternalStorage,
    LargePayloadWarning,
    MemoryFootprintError,
    SagaContext,
)


class TestConfigurationValidation:
    """Test configuration validation rules"""

    def test_auto_offload_without_storage_raises_error(self):
        """Auto-offload=True without storage should raise ConfigurationError"""
        ctx = SagaContext()

        with pytest.raises(ConfigurationError) as exc_info:
            ctx.configure(
                saga_id="test-saga",
                auto_offload=True,  # Requires storage
                storage=None,  # No storage provided
            )

        assert "auto_offload=True requires a storage backend" in str(exc_info.value)
        assert "FileSystemExternalStorage" in str(exc_info.value)
        assert "S3ExternalStorage" in str(exc_info.value)

    def test_auto_offload_with_storage_succeeds(self):
        """Auto-offload=True with storage should work"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileSystemExternalStorage(tmpdir)
            ctx = SagaContext()

            # Should not raise
            ctx.configure(
                saga_id="test-saga",
                auto_offload=True,
                storage=storage,
                offload_threshold=100,
            )

            assert ctx._auto_offload_enabled is True
            assert ctx._storage_backend is storage

    def test_storage_without_auto_offload_succeeds(self):
        """Storage configured but auto-offload=False should work"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileSystemExternalStorage(tmpdir)
            ctx = SagaContext()

            ctx.configure(
                saga_id="test-saga",
                auto_offload=False,  # Explicit disable
                storage=storage,  # Storage available for manual use
            )

            assert ctx._auto_offload_enabled is False
            assert ctx._storage_backend is storage

    def test_default_configuration(self):
        """Default configuration should have warnings enabled, no auto-offload"""
        ctx = SagaContext()
        ctx.configure(saga_id="test-saga")

        assert ctx._auto_offload_enabled is False
        assert ctx._storage_backend is None
        assert ctx._warn_on_large_payloads is True
        assert ctx._warn_threshold_bytes == 10_000_000  # 10MB
        assert ctx._strict_limit_bytes is None


class TestWarningSystem:
    """Test warning emission for large payloads"""

    @pytest.mark.asyncio
    async def test_large_payload_emits_warning(self):
        """Large payload should emit LargePayloadWarning"""
        ctx = SagaContext()
        ctx.configure(
            saga_id="test-saga",
            warn_on_large=True,
            warn_threshold=100,  # 100 bytes threshold for testing
        )

        large_value = "x" * 200  # 200 bytes

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await ctx.set_async("large_key", large_value)

            # Check warning was emitted
            assert len(w) == 1
            assert issubclass(w[0].category, LargePayloadWarning)
            assert "large_key" in str(w[0].message)
            assert "0.0MB" in str(w[0].message)  # Shows size
            assert "ctx.store_external()" in str(w[0].message)

    @pytest.mark.asyncio
    async def test_small_payload_no_warning(self):
        """Small payload should not emit warning"""
        ctx = SagaContext()
        ctx.configure(
            saga_id="test-saga",
            warn_on_large=True,
            warn_threshold=1000,  # 1KB threshold
        )

        small_value = "x" * 50  # 50 bytes

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await ctx.set_async("small_key", small_value)

            # No warnings
            assert len(w) == 0

    @pytest.mark.asyncio
    async def test_warnings_disabled(self):
        """Warnings should not be emitted when disabled"""
        ctx = SagaContext()
        ctx.configure(
            saga_id="test-saga",
            warn_on_large=False,  # Warnings disabled
            warn_threshold=100,
        )

        large_value = "x" * 200

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await ctx.set_async("large_key", large_value)

            # No warnings
            assert len(w) == 0


class TestStrictMode:
    """Test strict memory limits"""

    @pytest.mark.asyncio
    async def test_strict_limit_raises_error(self):
        """Exceeding strict limit should raise MemoryFootprintError"""
        ctx = SagaContext()
        ctx.configure(
            saga_id="test-saga",
            strict_limit=100,  # 100 bytes hard limit
        )

        large_value = "x" * 200  # 200 bytes

        with pytest.raises(MemoryFootprintError) as exc_info:
            await ctx.set_async("large_key", large_value)

        error = exc_info.value
        assert error.key == "large_key"
        assert error.size_bytes > 100
        assert error.limit_bytes == 100
        assert "exceeds strict memory limit" in str(error)
        assert "ctx.store_external" in str(error)
        assert "streaming" in str(error)

    @pytest.mark.asyncio
    async def test_strict_limit_allows_small_values(self):
        """Values under strict limit should be allowed"""
        ctx = SagaContext()
        ctx.configure(
            saga_id="test-saga",
            strict_limit=1000,  # 1KB limit
        )

        small_value = "x" * 50  # 50 bytes

        # Should not raise
        await ctx.set_async("small_key", small_value)
        assert ctx.data["small_key"] == small_value

    @pytest.mark.asyncio
    async def test_no_strict_limit_by_default(self):
        """By default, no strict limit should be enforced"""
        ctx = SagaContext()
        ctx.configure(saga_id="test-saga")

        # Very large value
        large_value = "x" * 1_000_000  # 1MB

        # Should not raise (only warning)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            await ctx.set_async("large_key", large_value)

        assert ctx.data["large_key"] == large_value


class TestAutoOffloadBehavior:
    """Test automatic offloading behavior"""

    @pytest.mark.asyncio
    async def test_auto_offload_stores_externally(self):
        """Large values should be auto-offloaded when threshold exceeded"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileSystemExternalStorage(tmpdir)
            ctx = SagaContext()
            ctx.configure(
                saga_id="test-saga",
                auto_offload=True,
                storage=storage,
                offload_threshold=100,  # 100 bytes
                warn_on_large=False,  # Disable warnings for this test
            )

            large_value = "x" * 200  # 200 bytes, exceeds threshold

            await ctx.set_async("large_key", large_value)

            # Should be stored externally
            assert "large_key" in ctx.external_refs
            assert isinstance(ctx.data["large_key"], dict)
            assert "_external_ref" in ctx.data["large_key"]

            # Verify we can load it back
            loaded = await ctx.get_async("large_key")
            assert loaded == large_value

    @pytest.mark.asyncio
    async def test_auto_offload_keeps_small_values_in_memory(self):
        """Small values should stay in memory even with auto-offload enabled"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileSystemExternalStorage(tmpdir)
            ctx = SagaContext()
            ctx.configure(
                saga_id="test-saga",
                auto_offload=True,
                storage=storage,
                offload_threshold=1000,  # 1KB
            )

            small_value = "x" * 50  # 50 bytes, under threshold

            await ctx.set_async("small_key", small_value)

            # Should be in memory
            assert ctx.data["small_key"] == small_value
            assert "small_key" not in ctx.external_refs

    @pytest.mark.asyncio
    async def test_strict_limit_takes_precedence_over_auto_offload(self):
        """Strict limit should raise error before auto-offload kicks in"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileSystemExternalStorage(tmpdir)
            ctx = SagaContext()
            ctx.configure(
                saga_id="test-saga",
                auto_offload=True,
                storage=storage,
                offload_threshold=100,  # Would offload at 100 bytes
                strict_limit=50,  # But strict limit is 50 bytes
            )

            value = "x" * 75  # Between strict limit and offload threshold

            # Should raise error, not offload
            with pytest.raises(MemoryFootprintError):
                await ctx.set_async("key", value)


class TestPriorityOrder:
    """Test validation priority: strict > warning > auto-offload"""

    @pytest.mark.asyncio
    async def test_all_features_enabled_priority(self):
        """Test priority order when all features enabled"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileSystemExternalStorage(tmpdir)
            ctx = SagaContext()
            ctx.configure(
                saga_id="test-saga",
                auto_offload=True,
                storage=storage,
                offload_threshold=100,  # Offload at 100 bytes
                warn_on_large=True,
                warn_threshold=50,  # Warn at 50 bytes
                strict_limit=200,  # Error at 200 bytes
            )

            # Value 1: Under all thresholds (60 bytes)
            small = "x" * 60
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                await ctx.set_async("small", small)
                assert len(w) == 1  # Warning only
                assert ctx.data["small"] == small  # In memory

            # Value 2: Exceeds warn and offload thresholds (150 bytes)
            medium = "x" * 150
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                await ctx.set_async("medium", medium)
                assert len(w) == 1  # Warning
                assert "medium" in ctx.external_refs  # Offloaded

            # Value 3: Exceeds all thresholds including strict (250 bytes)
            large = "x" * 250
            with pytest.raises(MemoryFootprintError):
                await ctx.set_async("large", large)


class TestEdgeCases:
    """Test edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_size_estimation_failure_stores_normally(self):
        """If size estimation fails, should store without validation"""
        ctx = SagaContext()
        ctx.configure(saga_id="test-saga", strict_limit=100)

        # Mock object that breaks pickle
        class UnpicklableObject:
            def __reduce__(self):
                msg = "Cannot pickle"
                raise TypeError(msg)

        obj = UnpicklableObject()

        # Should not raise, stores normally despite estimation failure
        await ctx.set_async("unpicklable", obj)
        assert ctx.data["unpicklable"] is obj

    @pytest.mark.asyncio
    async def test_async_generator_bypasses_validation(self):
        """AsyncGenerators should bypass size validation"""

        async def my_generator():
            yield 1
            yield 2

        ctx = SagaContext()
        ctx.configure(saga_id="test-saga", strict_limit=10)

        gen = my_generator()
        await ctx.set_async("stream", gen)

        # Should be registered as stream, not validated
        assert "stream" in ctx._streams
        assert "stream" not in ctx.data
