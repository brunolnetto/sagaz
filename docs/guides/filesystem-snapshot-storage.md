# Filesystem Snapshot Storage - Usage Guide

## Overview

`FilesystemSnapshotStorage` provides local file-based snapshot storage for development, testing, and research purposes. It stores snapshots as JSON files in an organized directory structure.

⚠️ **Not recommended for production** - Use S3, PostgreSQL, or Redis for production deployments.

## Features

- ✅ **Human-readable JSON** - Easy to inspect and debug
- ✅ **Organized structure** - Snapshots grouped by saga_id
- ✅ **Optional compression** - gzip compression for disk space savings
- ✅ **No external dependencies** - Only requires filesystem access
- ✅ **Perfect for local development** - Quick setup, no infrastructure needed
- ✅ **Great for research** - Easy data exploration and analysis
- ✅ **Storage statistics** - Built-in disk usage monitoring

## Quick Start

### Basic Usage

```python
from sagaz import Saga, SagaConfig, ReplayConfig, SnapshotStrategy
from sagaz.storage.backends import FilesystemSnapshotStorage

# Create storage instance
storage = FilesystemSnapshotStorage(
    base_path="./dev-snapshots",     # Local directory
    enable_compression=False,         # Disable for readability
    pretty_json=True                  # Format JSON nicely
)

# Use in saga
class PaymentSaga(Saga):
    async def build(self):
        await self.add_step(
            name="authorize_payment",
            action=self._authorize,
            compensation=self._cancel_authorization
        )

# Execute with snapshots
saga = PaymentSaga(
    context={"amount": 100.0, "currency": "USD"},
    config=SagaConfig(
        replay_config=ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP
        )
    ),
    snapshot_storage=storage
)

result = await saga.execute()
```

### Directory Structure

```
dev-snapshots/
├── snapshots/
│   ├── {saga_id_1}/
│   │   ├── {snapshot_id_1}.json
│   │   ├── {snapshot_id_2}.json
│   │   └── ...
│   ├── {saga_id_2}/
│   │   └── ...
│   └── ...
├── indexes/
│   ├── {saga_id_1}.json  # List of snapshots with timestamps
│   └── ...
└── replays/
    ├── {replay_id_1}.json
    └── ...
```

## Configuration Options

```python
storage = FilesystemSnapshotStorage(
    base_path="./saga-snapshots",    # Where to store files
    enable_compression=False,         # Use gzip compression
    pretty_json=True                  # Indent JSON for readability
)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_path` | `"./saga-snapshots"` | Root directory for storage |
| `enable_compression` | `False` | Enable gzip compression (.json.gz) |
| `pretty_json` | `True` | Pretty-print JSON (indent=2) |

## Use Cases

### 1. Local Development

Perfect for testing without infrastructure:

```python
# Quick setup for development
storage = FilesystemSnapshotStorage(
    base_path="./dev-snapshots",
    enable_compression=False,  # Keep readable
    pretty_json=True
)

# All sagas in development use it
saga = MySaga(
    snapshot_storage=storage,
    config=SagaConfig(
        replay_config=ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.ON_FAILURE
        )
    )
)
```

### 2. Research & Analysis

Inspect snapshots as JSON files:

```python
storage = FilesystemSnapshotStorage(base_path="./research-data")

# Save snapshots
await storage.save_snapshot(snapshot)

# Later, manually inspect:
# cat research-data/snapshots/{saga_id}/{snapshot_id}.json | jq '.'
```

### 3. Testing

Use in test fixtures:

```python
import tempfile
import pytest

@pytest.fixture
async def snapshot_storage():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = FilesystemSnapshotStorage(base_path=tmp_dir)
        yield storage
        # Auto-cleanup on exit
```

### 4. Debugging

Enable full snapshots for debugging:

```python
# Debug mode - snapshot everything
debug_storage = FilesystemSnapshotStorage(
    base_path="./debug-snapshots",
    enable_compression=False,  # Keep readable
    pretty_json=True
)

saga = ProblematicSaga(
    snapshot_storage=debug_storage,
    config=SagaConfig(
        replay_config=ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,  # Every step
            retention_days=7  # Clean up after debugging
        )
    )
)
```

## Advanced Features

### Storage Statistics

Monitor disk usage:

```python
storage = FilesystemSnapshotStorage(base_path="./snapshots")

# Get statistics
info = storage.get_storage_info()
print(info)
# {
#     'storage_type': 'filesystem',
#     'base_path': '/path/to/snapshots',
#     'compression_enabled': False,
#     'total_sagas': 5,
#     'total_snapshots': 23,
#     'total_replays': 3,
#     'total_size_bytes': 145892,
#     'total_size_mb': 0.14
# }
```

### Cleanup Operations

```python
# Clean up all snapshots for a saga
deleted = await storage.cleanup_saga(saga_id)
print(f"Deleted {deleted} snapshots")

# Clean up expired snapshots (retention_until passed)
expired = await storage.delete_expired_snapshots()
print(f"Deleted {expired} expired snapshots")
```

### With Compression

Save disk space with gzip:

```python
# Enable compression
storage = FilesystemSnapshotStorage(
    base_path="./compressed-snapshots",
    enable_compression=True  # Creates .json.gz files
)

# Savings: typically 60-80% for JSON data
```

### Context Manager

Proper resource cleanup:

```python
async with FilesystemSnapshotStorage(base_path="./snapshots") as storage:
    await storage.save_snapshot(snapshot)
    snapshots = await storage.list_snapshots(saga_id)
# Auto-cleanup
```

## Comparison with Other Backends

| Feature | Filesystem | InMemory | S3 | PostgreSQL | Redis |
|---------|-----------|----------|-----|------------|-------|
| Setup complexity | ⭐ Very easy | ⭐ Very easy | ⭐⭐⭐ Moderate | ⭐⭐⭐⭐ Complex | ⭐⭐⭐ Moderate |
| Production ready | ❌ No | ❌ No | ✅ Yes | ✅ Yes | ⚠️ Maybe |
| Persistence | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes | ⚠️ Configurable |
| Human readable | ✅ Yes | ❌ No | ❌ No | ❌ No | ❌ No |
| Query performance | ⭐⭐ Slow | ⭐⭐⭐⭐⭐ Fast | ⭐⭐⭐ Good | ⭐⭐⭐⭐ Fast | ⭐⭐⭐⭐⭐ Very fast |
| Scalability | ❌ Single node | ❌ Single node | ✅ Excellent | ⭐⭐⭐⭐ Good | ⭐⭐⭐⭐ Good |
| Cost | Free | Free | $ Low | $$ Medium | $$ Medium |
| Best for | Development, Research | Testing | Production | Production | Caching |

## Limitations

⚠️ **Not for production use:**
- Single-node only (no distribution)
- Slower than in-memory or database solutions
- Manual scaling required
- No built-in replication
- Limited query performance

✅ **Perfect for:**
- Local development
- Research and data exploration
- Testing and debugging
- Prototyping
- Learning and experimentation

## Migration Path

When moving to production, switch to S3:

```python
# Development
from sagaz.storage.backends import FilesystemSnapshotStorage

dev_storage = FilesystemSnapshotStorage(base_path="./dev-snapshots")

# Production
from sagaz.storage.backends import S3SnapshotStorage

prod_storage = S3SnapshotStorage(
    bucket_name="company-saga-snapshots",
    region_name="us-east-1",
    enable_compression=True,
    enable_encryption=True
)

# Same interface - no code changes needed!
```

## Example: Full Workflow

```python
from sagaz import Saga, action, compensate
from sagaz.storage.backends import FilesystemSnapshotStorage
from sagaz import SagaConfig, ReplayConfig, SnapshotStrategy

# Setup storage
storage = FilesystemSnapshotStorage(
    base_path="./research-snapshots",
    enable_compression=False,
    pretty_json=True
)

# Define saga
class ResearchSaga(Saga):
    @action(name="step1")
    async def process_data(self, ctx):
        return {"processed": True}
    
    @compensate(for_step="step1")
    async def rollback_processing(self, result, ctx):
        pass

# Execute with full snapshots
saga = ResearchSaga(
    context={"experiment_id": "exp-001"},
    config=SagaConfig(
        replay_config=ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
            retention_days=30
        )
    ),
    snapshot_storage=storage
)

result = await saga.execute()

# Analyze snapshots
info = storage.get_storage_info()
print(f"Captured {info['total_snapshots']} snapshots")
print(f"Storage size: {info['total_size_mb']} MB")

# List snapshots
snapshots = await storage.list_snapshots(saga.saga_id)
for snapshot in snapshots:
    print(f"Step: {snapshot.step_name}, Status: {snapshot.status}")
```

## Troubleshooting

### Permission Errors

```python
# Ensure directory is writable
import os
os.makedirs("./snapshots", exist_ok=True)
os.chmod("./snapshots", 0o755)
```

### Disk Space Issues

```python
# Enable compression
storage = FilesystemSnapshotStorage(
    base_path="./snapshots",
    enable_compression=True  # 60-80% savings
)

# Or clean up regularly
await storage.delete_expired_snapshots()
```

### Performance Concerns

```python
# For better performance, use InMemory for tests
from sagaz.storage.backends import InMemorySnapshotStorage

test_storage = InMemorySnapshotStorage()  # Much faster

# Or upgrade to Redis/PostgreSQL for production
```

## Summary

✅ **Use FilesystemSnapshotStorage when:**
- Developing locally
- Conducting research
- Debugging issues
- Learning the framework
- Need human-readable snapshots

❌ **Don't use for:**
- Production deployments
- High-performance requirements
- Distributed systems
- When you need replication

🚀 **Production migration:**
Switch to S3SnapshotStorage when ready - same interface!
