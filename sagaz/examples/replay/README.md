# Saga Replay Examples

Production-ready examples demonstrating saga replay and time-travel features.

## Quick Start

```bash
# Simple 3-step replay demonstration
python -m sagaz.examples.replay.simple_demo

# Order processing with payment recovery
python -m sagaz.examples.replay.order_recovery

# Time-travel historical queries
python -m sagaz.examples.replay.time_travel
```

## Examples

### 1. Simple Demo (`simple_demo.py`)
**Quickest way to understand replay basics**

- 3-step saga that fails at step 2
- Demonstrates replay from a checkpoint with context override
- Minimal code, easy to understand

**Use case**: Learn replay fundamentals in 5 minutes

### 2. Order Recovery (`order_recovery.py`)
**Production-realistic ecommerce scenario**

- Multi-step order processing (inventory → payment → shipping)
- Payment gateway failure simulation
- Demonstrates replay with backup gateway
- Shows snapshot inspection and audit trail

**Use case**: Recover from payment gateway outages

### 3. Time-Travel (`time_travel.py`)
**Historical state queries for compliance**

- Execute saga with multiple snapshots
- Query saga state at any point in time
- Useful for auditing and debugging

**Use case**: HIPAA/SOC2 compliance audits, incident investigation

##Features Demonstrated

| Feature | Simple | Order Recovery | Time-Travel |
|---------|--------|----------------|-------------|
| Checkpoint replay | ✅ | ✅ | - |
| Context override | ✅ | ✅ | - |
| Snapshot capture | ✅ | ✅ | ✅ |
| Snapshot inspection | - | ✅ | ✅ |
| Historical queries | - | - | ✅ |
| Compensation | ✅ | ✅ | - |

## Advanced Usage

See integration tests for more advanced scenarios:
- `tests/integration/test_saga_replay_integration.py` - Production patterns
- `tests/unit/core/test_replay.py` - Unit test examples

## Configuration

All examples use `ReplayConfig`:

```python
ReplayConfig(
    enable_snapshots=True,
    snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,  # or AFTER_EACH_STEP
    retention_days=30,
    compression=None,  # Optional: "zstd", "gzip"
)
```

## Storage Backends

Examples use in-memory storage. For production:

```python
from sagaz.storage.backends.redis.snapshot import RedisSnapshotStorage
from sagaz.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

# Redis (distributed, TTL support)
storage = RedisSnapshotStorage(redis_url="redis://localhost:6379")

# PostgreSQL (ACID, SQL queries)
storage = PostgreSQLSnapshotStorage(connection_string="postgresql://...")
```

See `docs/guides/replay-storage-backends.md` for full details.
