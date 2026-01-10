"""
Example demonstrating the memory validation and warning system.

This example shows:
1. Warning mode (default) - warns on large payloads
2. Strict mode - raises error on exceeding limits
3. Auto-offload mode - automatically stores large data externally
"""

import asyncio
import tempfile
import warnings

from sagaz.core import (
    ConfigurationError,
    FileSystemExternalStorage,
    LargePayloadWarning,
    MemoryFootprintError,
    SagaContext,
)


async def example_1_warning_mode():
    """Example 1: Default behavior - warnings for large payloads"""
    print("\n=== Example 1: Warning Mode (Default) ===\n")

    ctx = SagaContext()
    ctx.configure(
        saga_id="warning-example",
        warn_on_large=True,
        warn_threshold=1_000_000,  # 1MB threshold
    )

    # Small data - no warning
    print("Storing small data (100KB)...")
    small_data = "x" * 100_000  # 100KB
    await ctx.set_async("small_data", small_data)
    print("✓ Stored without warning\n")

    # Large data - warning emitted
    print("Storing large data (2MB)...")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        large_data = "x" * 2_000_000  # 2MB
        await ctx.set_async("large_data", large_data)

        if w:
            print(f"⚠️  Warning: {w[0].message}")
    print()


async def example_2_strict_mode():
    """Example 2: Strict mode - error on exceeding limit"""
    print("\n=== Example 2: Strict Mode ===\n")

    ctx = SagaContext()
    ctx.configure(
        saga_id="strict-example",
        strict_limit=1_000_000,  # 1MB hard limit
        warn_on_large=False,  # Disable warnings
    )

    # Within limit - OK
    print("Storing data within limit (500KB)...")
    ok_data = "x" * 500_000  # 500KB
    await ctx.set_async("ok_data", ok_data)
    print("✓ Stored successfully\n")

    # Exceeds limit - error
    print("Attempting to store data exceeding limit (2MB)...")
    try:
        too_large = "x" * 2_000_000  # 2MB
        await ctx.set_async("too_large", too_large)
    except MemoryFootprintError as e:
        print(f"❌ Error: Context key '{e.key}' exceeds limit")
        print(f"   Size: {e.size_bytes / 1_000_000:.1f}MB")
        print(f"   Limit: {e.limit_bytes / 1_000_000:.1f}MB\n")
        print("Suggested solutions:")
        print("  • Use ctx.store_external()")
        print("  • Use streaming for large datasets")
        print("  • Increase strict_limit in configuration")
    print()


async def example_3_auto_offload():
    """Example 3: Auto-offload - automatically store externally"""
    print("\n=== Example 3: Auto-Offload Mode ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileSystemExternalStorage(tmpdir)

        ctx = SagaContext()
        ctx.configure(
            saga_id="auto-offload-example",
            storage=storage,
            auto_offload=True,
            offload_threshold=500_000,  # 500KB threshold
            warn_on_large=False,  # Disable warnings for clarity
        )

        # Small data - stays in memory
        print("Storing small data (100KB)...")
        small_data = "x" * 100_000  # 100KB
        await ctx.set_async("small_data", small_data)
        print(f"✓ Stored in memory (not offloaded)")
        print(f"  In external refs: {'small_data' in ctx.external_refs}\n")

        # Large data - auto-offloaded
        print("Storing large data (1MB)...")
        large_data = "x" * 1_000_000  # 1MB
        await ctx.set_async("large_data", large_data)
        print(f"✓ Auto-offloaded to external storage")
        print(f"  In external refs: {'large_data' in ctx.external_refs}")
        print(f"  URI: {ctx.external_refs['large_data'].uri}\n")

        # Can still load transparently
        print("Loading large data back...")
        loaded = await ctx.get_async("large_data")
        print(f"✓ Loaded {len(loaded)} bytes transparently from storage\n")


async def example_4_validation_error():
    """Example 4: Configuration validation - auto-offload requires storage"""
    print("\n=== Example 4: Configuration Validation ===\n")

    ctx = SagaContext()

    print("Attempting to enable auto-offload without storage...")
    try:
        ctx.configure(
            saga_id="invalid-example",
            auto_offload=True,  # Requires storage
            storage=None,  # No storage configured!
        )
    except ConfigurationError as e:
        print(f"❌ Configuration Error:\n")
        print(str(e))
    print()


async def example_5_combined_configuration():
    """Example 5: Combined configuration - all features together"""
    print("\n=== Example 5: Combined Configuration ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileSystemExternalStorage(tmpdir)

        ctx = SagaContext()
        ctx.configure(
            saga_id="combined-example",
            storage=storage,
            auto_offload=True,
            offload_threshold=500_000,  # Auto-offload at 500KB
            warn_on_large=True,
            warn_threshold=200_000,  # Warn at 200KB
            strict_limit=2_000_000,  # Error at 2MB
        )

        print("Priority order: strict > warning > auto-offload\n")

        # Test 1: Small (100KB) - No action
        print("1. Storing 100KB data...")
        data_100kb = "x" * 100_000
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await ctx.set_async("small", data_100kb)
            print(f"   Warnings: {len(w)}")
            print(f"   Offloaded: {'small' in ctx.external_refs}")
            print(f"   → Stored in memory\n")

        # Test 2: Medium (300KB) - Warning + offload
        print("2. Storing 300KB data...")
        data_300kb = "x" * 300_000
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await ctx.set_async("medium", data_300kb)
            print(f"   Warnings: {len(w)} (warn threshold exceeded)")
            print(f"   Offloaded: {'medium' in ctx.external_refs} (offload threshold exceeded)")
            print(f"   → Warned and offloaded\n")

        # Test 3: Large (2.5MB) - Error (strict takes precedence)
        print("3. Attempting to store 2.5MB data...")
        try:
            data_2_5mb = "x" * 2_500_000
            await ctx.set_async("large", data_2_5mb)
        except MemoryFootprintError:
            print(f"   Error: Strict limit exceeded")
            print(f"   → Rejected before offload could happen\n")


async def main():
    """Run all examples"""
    print("=" * 70)
    print("Sagaz Context Memory Validation Examples")
    print("=" * 70)

    await example_1_warning_mode()
    await example_2_strict_mode()
    await example_3_auto_offload()
    await example_4_validation_error()
    await example_5_combined_configuration()

    print("=" * 70)
    print("Examples completed!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
