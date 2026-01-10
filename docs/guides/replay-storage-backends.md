# Saga Replay Storage Backends

## Overview

Sagaz provides multiple storage backends for saga snapshots and replay logs. Choose the backend that best fits your deployment architecture and requirements.

## Available Backends

### 1. InMemorySnapshotStorage

**Use Case:** Development, testing, and single-instance deployments

**Features:**
- No external dependencies
- Fast in-memory operations
- Automatic cleanup on restart

**Example:**
```python
from sagaz.storage.backends import InMemorySnapshotStorage

storage = InMemorySnapshotStorage()
await storage.save_snapshot(snapshot)
```

**Limitations:**
- Data lost on restart
- Not suitable for distributed systems
- Limited by available RAM

---

### 2. RedisSnapshotStorage

**Use Case:** Distributed systems, caching, TTL-based expiration

**Features:**
- Distributed snapshot storage
- Automatic TTL expiration
- Built-in compression (zstd)
- Sorted set indexing for fast queries
- Clustering support

**Requirements:**
```bash
pip install redis zstandard
```

**Example:**
```python
from sagaz.storage.backends import RedisSnapshotStorage

storage = RedisSnapshotStorage(
    redis_url="redis://localhost:6379",
    key_prefix="saga:snapshot:",
    default_ttl=2592000,  # 30 days
    enable_compression=True,
    compression_level=3  # 1-22, higher = better compression
)

async with storage:
    await storage.save_snapshot(snapshot)
    latest = await storage.get_latest_snapshot(saga_id)
```

**Configuration:**
- `redis_url`: Redis connection string
- `key_prefix`: Namespace prefix for keys (default: "snapshot:")
- `default_ttl`: Default TTL in seconds (optional)
- `enable_compression`: Enable zstd compression (default: True)
- `compression_level`: Compression level 1-22 (default: 3)

**Performance:**
- Snapshot save: ~5-10ms
- Snapshot retrieval: ~3-5ms
- Compression ratio: ~70% (10KB → 3KB)

---

### 3. PostgreSQLSnapshotStorage

**Use Case:** ACID compliance, complex queries, audit requirements

**Features:**
- ACID-compliant transactions
- Full SQL querying capabilities
- Referential integrity
- Advanced indexing
- Backup/restore support

**Requirements:**
```bash
pip install asyncpg
```

**Schema:**
The storage backend automatically creates the required tables:

```sql
CREATE TABLE saga_snapshots (
    snapshot_id      UUID PRIMARY KEY,
    saga_id          UUID NOT NULL,
    saga_name        VARCHAR(255) NOT NULL,
    step_name        VARCHAR(255) NOT NULL,
    step_index       INTEGER NOT NULL,
    status           VARCHAR(50) NOT NULL,
    context          JSONB NOT NULL,
    completed_steps  JSONB NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    retention_until  TIMESTAMPTZ
);

CREATE TABLE saga_replay_log (
    replay_id        UUID PRIMARY KEY,
    original_saga_id UUID NOT NULL,
    new_saga_id      UUID NOT NULL,
    checkpoint_step  VARCHAR(255) NOT NULL,
    context_override JSONB,
    initiated_by     VARCHAR(255) NOT NULL,
    replay_status    VARCHAR(50) NOT NULL,
    error_message    TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    completed_at     TIMESTAMPTZ
);
```

**Example:**
```python
from sagaz.storage.backends import PostgreSQLSnapshotStorage

storage = PostgreSQLSnapshotStorage(
    connection_string="postgresql://user:pass@localhost:5432/sagaz",
    pool_min_size=5,
    pool_max_size=20
)

async with storage:
    await storage.save_snapshot(snapshot)
    
    # Complex queries possible via SQL
    snapshots = await storage.list_snapshots(saga_id, limit=100)
```

**Configuration:**
- `connection_string`: PostgreSQL connection URL
- `pool_min_size`: Minimum connection pool size (default: 5)
- `pool_max_size`: Maximum connection pool size (default: 20)

**Performance:**
- Snapshot save: ~20-50ms (with indexes)
- Snapshot retrieval: ~10-30ms
- Batch operations: ~100-500ms (100 snapshots)

---

### 4. S3SnapshotStorage

**Use Case:** Large-scale storage, archival, multi-region deployments

**Features:**
- Unlimited scalability
- Built-in compression (zstd)
- Server-side encryption (SSE-S3)
- Lifecycle policies
- Cross-region replication
- Storage classes (STANDARD, STANDARD_IA, GLACIER)

**Requirements:**
```bash
pip install aioboto3 zstandard
```

**Example:**
```python
from sagaz.storage.backends import S3SnapshotStorage

storage = S3SnapshotStorage(
    bucket_name="my-saga-snapshots",
    region_name="us-east-1",
    prefix="production/snapshots/",
    enable_compression=True,
    enable_encryption=True,
    storage_class="STANDARD_IA"  # For infrequent access
)

async with storage:
    await storage.save_snapshot(snapshot)
    snapshot = await storage.get_snapshot(snapshot_id)
```

**Configuration:**
- `bucket_name`: S3 bucket name (required)
- `region_name`: AWS region (default: "us-east-1")
- `prefix`: Object key prefix (default: "snapshots/")
- `enable_compression`: Enable zstd compression (default: True)
- `compression_level`: Compression level 1-22 (default: 3)
- `enable_encryption`: Server-side encryption (default: True)
- `storage_class`: S3 storage class (default: "STANDARD")

**Storage Classes:**
- `STANDARD`: General purpose, low latency
- `STANDARD_IA`: Infrequent access, lower cost
- `GLACIER`: Archive, very low cost, retrieval delay
- `GLACIER_DEEP_ARCHIVE`: Long-term archive, lowest cost

**Performance:**
- Snapshot save: ~100-300ms (with compression)
- Snapshot retrieval: ~50-150ms (depends on storage class)
- Compression ratio: ~70% (10KB → 3KB)

**Cost Optimization:**
Use S3 lifecycle policies to transition old snapshots:
```json
{
  "Rules": [{
    "Id": "ArchiveOldSnapshots",
    "Status": "Enabled",
    "Transitions": [
      {
        "Days": 90,
        "StorageClass": "STANDARD_IA"
      },
      {
        "Days": 365,
        "StorageClass": "GLACIER"
      }
    ]
  }]
}
```

---

## Compression

Redis and S3 backends support zstd compression to reduce storage costs and network bandwidth.

**Compression Levels:**
- Level 1: Fastest, ~50% compression ratio
- Level 3: Balanced (default), ~70% compression ratio
- Level 10: Better compression, ~75% compression ratio
- Level 22: Maximum compression, ~80% compression ratio

**Benchmark (10KB snapshot):**
```
No compression:     10,240 bytes
zstd level 1:        5,120 bytes  (2x faster save/load)
zstd level 3:        3,072 bytes  (balanced)
zstd level 10:       2,560 bytes  (10% slower save)
zstd level 22:       2,048 bytes  (50% slower save)
```

**Recommendation:** Use level 3 for most cases, level 10 for high-volume storage.

---

## Choosing a Backend

| Criteria | InMemory | Redis | PostgreSQL | S3 |
|----------|----------|-------|------------|-----|
| **Setup Complexity** | ⭐ Easy | ⭐⭐ Moderate | ⭐⭐⭐ Complex | ⭐⭐⭐ Complex |
| **Performance** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |
| **Durability** | ❌ None | ⭐⭐⭐ High | ⭐⭐⭐⭐⭐ Very High | ⭐⭐⭐⭐⭐ Very High |
| **Scalability** | ⭐ Limited | ⭐⭐⭐⭐ High | ⭐⭐⭐ Good | ⭐⭐⭐⭐⭐ Unlimited |
| **Cost** | Free | Low | Medium | Low-Medium |
| **ACID** | ❌ No | ❌ No | ✅ Yes | ❌ No |
| **Compression** | ❌ No | ✅ Yes | ❌ No | ✅ Yes |
| **Encryption** | ❌ No | ⚠️ Client-side | ⚠️ TDE | ✅ SSE-S3 |
| **TTL** | ❌ No | ✅ Native | ⚠️ Manual | ⚠️ Lifecycle |

**Recommendations:**

1. **Development/Testing:** InMemorySnapshotStorage
2. **Production (small-medium scale):** RedisSnapshotStorage
3. **Compliance/Audit:** PostgreSQLSnapshotStorage
4. **Large-scale/Archive:** S3SnapshotStorage

**Hybrid Approach:**
Use Redis for recent snapshots (hot data) and S3 for archival (cold data):

```python
from datetime import datetime, timedelta

# Hot data: Redis (last 7 days)
redis_storage = RedisSnapshotStorage(default_ttl=604800)

# Cold data: S3 (archive)
s3_storage = S3SnapshotStorage(
    storage_class="GLACIER",
    prefix="archive/snapshots/"
)

# Save to both
await redis_storage.save_snapshot(snapshot)
if snapshot.created_at < datetime.now() - timedelta(days=7):
    await s3_storage.save_snapshot(snapshot)
```

---

## Migration Between Backends

Use the storage transfer service to migrate snapshots:

```python
from sagaz.storage.backends import RedisSnapshotStorage, S3SnapshotStorage

# Source
redis_storage = RedisSnapshotStorage()

# Target
s3_storage = S3SnapshotStorage(bucket_name="snapshots-archive")

async with redis_storage, s3_storage:
    # Migrate all snapshots for a saga
    snapshots = await redis_storage.list_snapshots(saga_id)
    for snapshot in snapshots:
        await s3_storage.save_snapshot(snapshot)
```

---

## Monitoring & Metrics

All backends expose metrics for monitoring:

```python
# Get storage health
health = await storage.health_check()
print(f"Status: {health.status}")
print(f"Snapshots: {health.snapshot_count}")
print(f"Size: {health.total_size_bytes}")

# Backend-specific metrics
if isinstance(storage, RedisSnapshotStorage):
    info = await storage._get_redis().info("memory")
    print(f"Redis memory used: {info['used_memory_human']}")
```

---

## Best Practices

1. **Always use context managers** for proper connection cleanup:
   ```python
   async with storage:
       await storage.save_snapshot(snapshot)
   ```

2. **Set retention policies** to avoid unbounded growth:
   ```python
   config = ReplayConfig(retention_days=2555)  # 7 years for HIPAA
   ```

3. **Enable compression** for Redis and S3 to reduce costs:
   ```python
   storage = S3SnapshotStorage(enable_compression=True)
   ```

4. **Use connection pooling** for PostgreSQL:
   ```python
   storage = PostgreSQLSnapshotStorage(
       pool_min_size=10,
       pool_max_size=50
   )
   ```

5. **Monitor storage size** and implement cleanup:
   ```python
   deleted = await storage.delete_expired_snapshots()
   print(f"Cleaned up {deleted} expired snapshots")
   ```

---

## Troubleshooting

### Redis Connection Issues
```python
from sagaz.core.exceptions import MissingDependencyError

try:
    storage = RedisSnapshotStorage()
except MissingDependencyError as e:
    print(f"Install dependencies: pip install {e.package}")
```

### PostgreSQL Schema Issues
```python
# Manually create tables if needed
async with storage._get_pool().acquire() as conn:
    await conn.execute(PostgreSQLSnapshotStorage.CREATE_TABLES_SQL)
```

### S3 Permissions
Ensure your AWS credentials have these permissions:
- `s3:PutObject`
- `s3:GetObject`
- `s3:DeleteObject`
- `s3:ListBucket`

---

## Security Considerations

### Redis
- Use TLS: `redis_url="rediss://..."`
- Enable authentication: Include password in URL
- Network isolation: Deploy in private subnet

### PostgreSQL
- Use SSL: `sslmode=require` in connection string
- Enable TDE (Transparent Data Encryption)
- Row-level security for multi-tenancy

### S3
- Enable SSE-S3 or SSE-KMS encryption
- Use bucket policies to restrict access
- Enable versioning for audit trail
- Configure CORS if accessing from web UI

---

## See Also

- [ADR-024: Saga Replay & Time-Travel](../docs/architecture/adr/adr-024-saga-replay.md)
- [Snapshot Storage Interface](sagaz/storage/interfaces/snapshot.py)
- [Replay CLI Commands](sagaz/cli/replay.py)
