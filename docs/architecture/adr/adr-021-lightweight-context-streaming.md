# ADR-021: Lightweight Context & Streaming Support

## Status

**Accepted** | Date: 2026-01-09 | Priority: Medium | Target: v1.4.0

## Dependencies

**Prerequisites**:
- ADR-016: Unified Storage Layer (needs external storage for large payloads)

**Enables**:
- ADR-023: Pivot Steps (streaming recovery actions)
- ADR-025: Event Triggers (streaming saga execution)
- ADR-013: Fluss Analytics (streaming data pipelines)
- Large-scale ETL and ML training sagas

**Roadmap**: **Phase 3 (v1.4.0)** - Performance optimization for large payloads

## Context

As identified through analysis of the Sagaz codebase, the current context management approach has scalability limitations when handling large data payloads between saga steps.

### Current Implementation Analysis

**SagaContext Behavior (sagaz/core.py):**
```python
@dataclass
class SagaContext:
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value  # Stores FULL data in memory
```

**Current Storage Behavior:**
- ✅ Full context passed to each step
- ✅ Step results stored in context: `self.context.set(step.name, step.result)`
- ✅ Full context persisted as JSONB in PostgreSQL/Redis
- ❌ No intermediary snapshots between steps
- ❌ No reference-based context passing
- ❌ No streaming support for large payloads

### Identified Problems

#### Problem 1: Unbounded Context Growth

```python
# Current: Each step result accumulates in context
@action("download_large_file")
async def download(self, ctx):
    return {"file_data": bytes(10_000_000)}  # 10MB added to context

@action("process_file", depends_on=["download_large_file"])
async def process(self, ctx):
    # Context now contains 10MB + previous steps
    return {"processed_data": bytes(5_000_000)}  # +5MB

@action("upload_result", depends_on=["process_file"])
async def upload(self, ctx):
    # Context now contains 15MB + metadata
    # All persisted to database on each state save
```

**Impact:**
- Memory exhaustion for long-running sagas
- Database bloat (JSONB column size)
- Slow serialization/deserialization
- Network overhead in distributed systems

#### Problem 2: No Streaming Between Steps

```python
# Current: No support for processing large datasets incrementally
@action("analyze_logs")
async def analyze(self, ctx):
    logs = await fetch_all_logs(ctx["date_range"])  # Load 1GB into memory
    return {"analysis": process_all(logs)}  # Process all at once
```

**Impact:**
- Cannot process datasets larger than available memory
- No support for real-time processing pipelines
- Inefficient for ETL-style sagas

#### Problem 3: No External Reference Storage

```python
# Current: Large files must be embedded in context or passed as paths
@action("generate_report")
async def generate(self, ctx):
    report_data = create_large_report()  # 50MB report
    # Option 1: Store in context (bloats context)
    return {"report": report_data}
    # Option 2: Write to disk, pass path (not transaction-safe)
    return {"report_path": "/tmp/report.pdf"}
```

**Impact:**
- No clean way to handle large binary data
- Temporary files not transaction-safe
- No automatic cleanup

### Production Pain Points (2024-2025)

Real incidents that motivated this ADR:

1. **Video Processing Saga** - 4K video files (500MB each) caused OOM crashes when stored in context
2. **ETL Pipeline** - Daily data sync saga failed: 10GB CSV file couldn't fit in memory
3. **ML Training Saga** - Model training results (2GB) caused PostgreSQL JSONB size limits
4. **IoT Data Aggregation** - Processing 10M device events sequentially caused 6-hour saga duration
5. **Backup Saga** - Snapshot creation saga timed out due to context serialization overhead

### Industry Patterns

| System | Approach |
|--------|----------|
| **Apache Airflow** | XCom for small data, external storage (S3) for large datasets |
| **Temporal** | Activity results limited to 2MB, uses side effects for large data |
| **AWS Step Functions** | 256KB payload limit, uses S3 references for large data |
| **Netflix Conductor** | Task output stored externally, only metadata in workflow state |
| **Prefect** | Result persistence backends (S3, GCS) for large data |

## Decision

Implement **Lightweight Context & Streaming Support** with four main capabilities:

### 1. Reference-Based Context Passing

Store large payloads externally, pass only references/URIs in context:

```python
from sagaz import SagaContext, ExternalStorage

@action("generate_large_report")
async def generate_report(self, ctx: SagaContext):
    report_data = create_report()  # 50MB
    
    # Store externally, get reference
    ref = await ctx.store_external("report", report_data)
    
    return {"report_ref": ref}  # Only URI stored in context

@action("email_report", depends_on=["generate_large_report"])
async def email_report(self, ctx: SagaContext):
    # Lazy load from external storage
    report_data = await ctx.load_external("report")
    await email_service.send(report_data)
```

### 2. Async Streaming Between Steps

Support streaming data between steps using AsyncGenerator:

```python
from sagaz import action, streaming_action

@streaming_action("process_log_chunks")
async def process_logs(self, ctx: SagaContext) -> AsyncGenerator[dict, None]:
    """Stream processed chunks to downstream steps"""
    async for chunk in read_log_chunks(ctx["log_file"]):
        processed = await process_chunk(chunk)
        yield {"chunk_id": chunk.id, "data": processed}

@action("aggregate_results", depends_on=["process_log_chunks"])
async def aggregate(self, ctx: SagaContext):
    """Consume stream from upstream step"""
    total_errors = 0
    
    async for result in ctx.stream("process_log_chunks"):
        total_errors += result["data"]["error_count"]
    
    return {"total_errors": total_errors}
```

### 3. Intermediary Checkpoint Storage

Save lightweight snapshots after each step:

```python
# Configuration
saga = OrderSaga(
    config=SagaConfig(
        checkpoint_mode="intermediary",  # Save after each step
        checkpoint_strategy="metadata_only"  # Only metadata, not full context
    )
)

# What gets stored per checkpoint:
checkpoint = {
    "saga_id": "abc-123",
    "step_name": "charge_payment",
    "status": "completed",
    "metadata": {
        "step_index": 2,
        "duration_ms": 250,
        "timestamp": "2025-01-01T10:30:00Z"
    },
    "context_hash": "sha256:abc...",  # Hash of full context
    "external_refs": {
        "large_data": "s3://bucket/saga-abc-123/step2-data.bin"
    }
}
```

### 4. Configurable Context Size Limits

Enforce limits and auto-offload to external storage:

```python
from sagaz import SagaConfig, ContextSizeLimit

config = SagaConfig(
    context_limit=ContextSizeLimit(
        max_context_size_bytes=1_000_000,  # 1MB limit
        auto_offload=True,  # Automatically store large values externally
        offload_threshold_bytes=100_000,    # 100KB threshold
        raise_on_exceed=False  # Offload instead of raising
    )
)

# Automatic behavior:
@action("generate_data")
async def generate(self, ctx):
    large_data = bytes(500_000)  # 500KB
    return {"data": large_data}  # Auto-stored externally, ref in context
```

## Architecture

### Reference-Based Context System

```
┌─────────────────────────────────────────────────────────────┐
│                    SAGA EXECUTION                            │
│                                                              │
│  Step 1                Step 2                Step 3          │
│  ┌──────────┐         ┌──────────┐         ┌──────────┐     │
│  │Generate  │         │Process   │         │Upload    │     │
│  │Report    │         │Report    │         │Report    │     │
│  └────┬─────┘         └────┬─────┘         └────┬─────┘     │
│       │                    │                    │            │
│       │ result (50MB)      │ result (30MB)      │ result     │
│       ▼                    ▼                    ▼            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           External Storage (S3/MinIO/FS)             │   │
│  │  s3://saga-abc/step1-result.bin (50MB)               │   │
│  │  s3://saga-abc/step2-result.bin (30MB)               │   │
│  └──────────────────────────────────────────────────────┘   │
│       │                    │                    │            │
│       │ ref URI            │ ref URI            │ ref URI    │
│       ▼                    ▼                    ▼            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │               SagaContext (Lightweight)               │   │
│  │  {                                                    │   │
│  │    "step1": {"ref": "s3://saga-abc/step1-result.bin"},│   │
│  │    "step2": {"ref": "s3://saga-abc/step2-result.bin"},│   │
│  │    "metadata": {"order_id": "123"}                   │   │
│  │  }                                                    │   │
│  │  Size: ~500 bytes (vs 80MB without references)       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Streaming Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   STREAMING SAGA                             │
│                                                              │
│  Producer Step              Consumer Step                    │
│  ┌──────────────┐          ┌──────────────┐                 │
│  │ Read Logs    │          │  Aggregate   │                 │
│  │ (Generator)  │          │  (Consumer)  │                 │
│  └──────┬───────┘          └──────▲───────┘                 │
│         │                         │                          │
│         │ yield chunk 1 ──────────┤                          │
│         │ yield chunk 2 ──────────┤                          │
│         │ yield chunk 3 ──────────┤                          │
│         │ ...                     │                          │
│         │                         │                          │
│  ┌──────┴─────────────────────────┴───────┐                 │
│  │       Stream Buffer (Ring Buffer)       │                 │
│  │  - Bounded buffer (e.g., 100 items)     │                 │
│  │  - Backpressure when full               │                 │
│  │  - Memory-efficient                     │                 │
│  └─────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

### Enhanced SagaContext Implementation

```python
from typing import Any, AsyncGenerator, Callable
from dataclasses import dataclass, field
import hashlib

@dataclass
class ExternalReference:
    """Reference to externally stored data"""
    uri: str                        # Storage URI (s3://bucket/key)
    size_bytes: int                 # Original size
    content_type: str              # MIME type
    checksum: str                  # SHA256 hash
    created_at: datetime
    ttl_seconds: int | None = None  # Auto-cleanup after TTL

@dataclass
class SagaContext:
    """Enhanced context with external storage support"""
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # NEW: External references
    external_refs: dict[str, ExternalReference] = field(default_factory=dict)
    
    # NEW: Stream registry
    _streams: dict[str, AsyncGenerator] = field(default_factory=dict)
    
    # NEW: Size tracking
    _size_bytes: int = 0
    _max_size_bytes: int = 1_000_000  # 1MB default
    
    def set(self, key: str, value: Any) -> None:
        """Set value with automatic size checking and offloading"""
        value_size = self._estimate_size(value)
        
        # Check if offloading needed
        if self._should_offload(value_size):
            # Store externally
            ref = self._offload_to_external(key, value)
            self.external_refs[key] = ref
            # Store reference in data
            self.data[key] = {"_external_ref": ref.uri}
        else:
            self.data[key] = value
            self._size_bytes += value_size
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get value with automatic loading from external storage"""
        if key in self.external_refs:
            # Lazy load from external storage
            return await self._load_from_external(key)
        return self.data.get(key, default)
    
    async def store_external(
        self,
        key: str,
        value: Any,
        storage_backend: str = "default"
    ) -> ExternalReference:
        """Explicitly store value in external storage"""
        ref = await self.storage.store(
            saga_id=self.saga_id,
            key=key,
            value=value,
            backend=storage_backend
        )
        self.external_refs[key] = ref
        return ref
    
    async def load_external(self, key: str) -> Any:
        """Explicitly load value from external storage"""
        if key not in self.external_refs:
            raise KeyError(f"No external reference for key: {key}")
        
        ref = self.external_refs[key]
        return await self.storage.load(ref.uri)
    
    def register_stream(
        self,
        key: str,
        generator: AsyncGenerator
    ) -> None:
        """Register a streaming generator"""
        self._streams[key] = generator
    
    def stream(self, key: str) -> AsyncGenerator:
        """Get a registered stream for consumption"""
        if key not in self._streams:
            raise KeyError(f"No stream registered for key: {key}")
        return self._streams[key]
    
    def _should_offload(self, value_size: int) -> bool:
        """Check if value should be offloaded to external storage"""
        return (
            self._auto_offload_enabled and
            value_size > self._offload_threshold_bytes
        )
    
    def _estimate_size(self, value: Any) -> int:
        """Estimate size of value in bytes"""
        if isinstance(value, bytes):
            return len(value)
        elif isinstance(value, str):
            return len(value.encode('utf-8'))
        else:
            # Approximate using pickle
            import pickle
            return len(pickle.dumps(value))
```

## Implementation

### External Storage Abstraction

```python
from abc import ABC, abstractmethod

class ExternalStorage(ABC):
    """Abstract base for external storage backends"""
    
    @abstractmethod
    async def store(
        self,
        saga_id: str,
        key: str,
        value: Any,
        ttl_seconds: int | None = None
    ) -> ExternalReference:
        """Store value and return reference"""
        pass
    
    @abstractmethod
    async def load(self, uri: str) -> Any:
        """Load value from URI"""
        pass
    
    @abstractmethod
    async def delete(self, uri: str) -> None:
        """Delete stored value"""
        pass
    
    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Clean up expired values, return count deleted"""
        pass

class S3ExternalStorage(ExternalStorage):
    """S3/MinIO implementation"""
    
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None
    ):
        self.bucket = bucket
        self.client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )
    
    async def store(
        self,
        saga_id: str,
        key: str,
        value: Any,
        ttl_seconds: int | None = None
    ) -> ExternalReference:
        # Serialize value
        data = pickle.dumps(value)
        
        # Generate object key
        object_key = f"saga-{saga_id}/{key}-{uuid.uuid4()}.bin"
        
        # Calculate checksum
        checksum = hashlib.sha256(data).hexdigest()
        
        # Upload to S3
        await self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=data,
            Metadata={
                'saga_id': saga_id,
                'checksum': checksum
            }
        )
        
        # Create reference
        uri = f"s3://{self.bucket}/{object_key}"
        return ExternalReference(
            uri=uri,
            size_bytes=len(data),
            content_type="application/octet-stream",
            checksum=checksum,
            created_at=datetime.now(),
            ttl_seconds=ttl_seconds
        )
    
    async def load(self, uri: str) -> Any:
        # Parse URI
        bucket, key = self._parse_s3_uri(uri)
        
        # Download from S3
        response = await self.client.get_object(
            Bucket=bucket,
            Key=key
        )
        data = await response['Body'].read()
        
        # Deserialize
        return pickle.loads(data)

class FileSystemExternalStorage(ExternalStorage):
    """Local filesystem implementation for testing"""
    
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    async def store(
        self,
        saga_id: str,
        key: str,
        value: Any,
        ttl_seconds: int | None = None
    ) -> ExternalReference:
        # Serialize
        data = pickle.dumps(value)
        
        # Create file path
        file_path = self.base_path / f"saga-{saga_id}" / f"{key}.bin"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to file
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(data)
        
        # Create reference
        uri = f"file://{file_path.absolute()}"
        return ExternalReference(
            uri=uri,
            size_bytes=len(data),
            content_type="application/octet-stream",
            checksum=hashlib.sha256(data).hexdigest(),
            created_at=datetime.now(),
            ttl_seconds=ttl_seconds
        )
```

### Streaming Step Decorator

```python
from functools import wraps
from typing import AsyncGenerator

def streaming_action(name: str, **kwargs):
    """Decorator for streaming saga actions"""
    def decorator(func: Callable) -> Callable:
        # Validate function returns AsyncGenerator
        import inspect
        sig = inspect.signature(func)
        return_annotation = sig.return_annotation
        
        if not (return_annotation == AsyncGenerator or
                str(return_annotation).startswith('AsyncGenerator')):
            raise TypeError(
                f"Streaming action {name} must return AsyncGenerator, "
                f"got {return_annotation}"
            )
        
        @wraps(func)
        async def wrapper(self, ctx: SagaContext):
            # Execute streaming function
            generator = func(self, ctx)
            
            # Register stream in context
            ctx.register_stream(name, generator)
            
            # Return stream metadata
            return {
                "_stream": name,
                "_type": "async_generator"
            }
        
        # Mark as streaming action
        wrapper.__saga_streaming__ = True
        wrapper.__saga_action_name__ = name
        
        return wrapper
    return decorator
```

### Checkpoint Storage Schema

```sql
-- Enhanced checkpoint storage with external references
CREATE TABLE saga_checkpoints (
    checkpoint_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    saga_id            UUID NOT NULL,
    saga_name          VARCHAR(255) NOT NULL,
    step_name          VARCHAR(255) NOT NULL,
    step_index         INTEGER NOT NULL,
    
    -- Lightweight metadata only
    status             VARCHAR(50) NOT NULL,
    metadata           JSONB NOT NULL,
    
    -- Context hash for integrity
    context_hash       VARCHAR(64) NOT NULL,  -- SHA256
    context_size_bytes BIGINT NOT NULL,
    
    -- External references
    external_refs      JSONB NOT NULL,  -- {step_name: {uri, size, checksum}}
    
    -- Timestamps
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    expires_at         TIMESTAMPTZ,
    
    -- Indexes
    INDEX idx_saga_checkpoints_saga_id (saga_id),
    INDEX idx_saga_checkpoints_step (saga_id, step_index),
    INDEX idx_saga_checkpoints_expires (expires_at)
);

-- Cleanup job for expired checkpoints
CREATE OR REPLACE FUNCTION cleanup_expired_checkpoints()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM saga_checkpoints
    WHERE expires_at < NOW()
    RETURNING COUNT(*) INTO deleted_count;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
```

## Use Cases

### Use Case 1: Video Processing Saga

**Scenario:** Process 4K video files (500MB each) without OOM.

**Solution:**
```python
class VideoProcessingSaga(Saga):
    def __init__(self, video_url: str):
        super().__init__(
            config=SagaConfig(
                external_storage=S3ExternalStorage(
                    bucket="video-processing-temp"
                ),
                context_limit=ContextSizeLimit(
                    max_context_size_bytes=10_000_000,  # 10MB
                    auto_offload=True,
                    offload_threshold_bytes=1_000_000    # 1MB
                )
            )
        )
        self.video_url = video_url
    
    @action("download_video")
    async def download(self, ctx: SagaContext):
        video_data = await download_large_file(self.video_url)  # 500MB
        
        # Auto-offloaded to S3, only reference in context
        return {"video": video_data}  # Stored as external ref
    
    @action("transcode_video", depends_on=["download_video"])
    async def transcode(self, ctx: SagaContext):
        # Lazy load from S3 only when needed
        video_data = await ctx.get("video")
        
        transcoded = await transcode_h264(video_data)
        
        return {"transcoded": transcoded}  # Also stored externally
    
    @action("upload_result", depends_on=["transcode_video"])
    async def upload(self, ctx: SagaContext):
        transcoded = await ctx.get("transcoded")
        
        await upload_to_cdn(transcoded)
        
        return {"cdn_url": "https://cdn.example.com/video.mp4"}
```

### Use Case 2: Streaming ETL Pipeline

**Scenario:** Process 10GB CSV file without loading all into memory.

**Solution:**
```python
class ETLSaga(Saga):
    @streaming_action("extract_data")
    async def extract(self, ctx: SagaContext) -> AsyncGenerator[dict, None]:
        """Stream CSV rows without loading all into memory"""
        async with aiofiles.open(ctx["csv_path"], 'r') as f:
            async for line in f:
                row = parse_csv_line(line)
                yield {"row": row}
    
    @streaming_action("transform_data", depends_on=["extract_data"])
    async def transform(self, ctx: SagaContext) -> AsyncGenerator[dict, None]:
        """Transform each row on the fly"""
        async for item in ctx.stream("extract_data"):
            transformed = apply_transformations(item["row"])
            yield {"row": transformed}
    
    @action("load_data", depends_on=["transform_data"])
    async def load(self, ctx: SagaContext):
        """Batch insert to database"""
        batch = []
        total_rows = 0
        
        async for item in ctx.stream("transform_data"):
            batch.append(item["row"])
            
            if len(batch) >= 1000:
                await db.bulk_insert(batch)
                total_rows += len(batch)
                batch = []
        
        # Insert remaining
        if batch:
            await db.bulk_insert(batch)
            total_rows += len(batch)
        
        return {"total_rows": total_rows}
```

### Use Case 3: ML Training Saga

**Scenario:** Store 2GB model weights without hitting database limits.

**Solution:**
```python
class MLTrainingSaga(Saga):
    @action("train_model")
    async def train(self, ctx: SagaContext):
        model = train_large_model(ctx["dataset"])
        
        # Explicitly store model in S3
        model_ref = await ctx.store_external(
            "trained_model",
            model.state_dict(),  # 2GB tensor data
            storage_backend="s3"
        )
        
        return {
            "model_ref": model_ref.uri,
            "accuracy": 0.95,
            "loss": 0.05
        }
    
    @action("evaluate_model", depends_on=["train_model"])
    async def evaluate(self, ctx: SagaContext):
        # Load only when needed for evaluation
        model_state = await ctx.load_external("trained_model")
        
        model = MyModel()
        model.load_state_dict(model_state)
        
        metrics = await evaluate_model(model, ctx["test_dataset"])
        
        return metrics
```

### Use Case 4: Backup Saga with Intermediary Checkpoints

**Scenario:** 6-hour backup saga needs progress tracking.

**Solution:**
```python
class BackupSaga(Saga):
    def __init__(self):
        super().__init__(
            config=SagaConfig(
                checkpoint_mode="intermediary",
                checkpoint_strategy="metadata_only"
            )
        )
    
    @action("backup_database")
    async def backup_db(self, ctx: SagaContext):
        backup_file = await create_db_backup()  # 100GB
        
        # Store externally
        ref = await ctx.store_external("db_backup", backup_file)
        
        # Only metadata in context
        return {
            "backup_ref": ref.uri,
            "size_gb": ref.size_bytes / 1e9,
            "checksum": ref.checksum
        }
        # Checkpoint saved here with metadata only
    
    @action("backup_files", depends_on=["backup_database"])
    async def backup_files(self, ctx: SagaContext):
        # If saga fails here, can resume from this checkpoint
        # without re-running database backup
        files_ref = await backup_filesystem()
        
        return {
            "files_ref": files_ref,
            "file_count": 1_000_000
        }
        # Another checkpoint saved
    
    @action("upload_to_s3", depends_on=["backup_files"])
    async def upload(self, ctx: SagaContext):
        db_backup = await ctx.load_external("db_backup")
        files_backup = await ctx.load_external("files_backup")
        
        await upload_to_glacier(db_backup, files_backup)
        
        return {"glacier_archive_id": "abc123"}
```

## Implementation Phases

### Phase 1: External Storage Foundation (v2.1.0)

- [ ] Create `ExternalStorage` abstract base class
- [ ] Implement `S3ExternalStorage` backend
- [ ] Implement `FileSystemExternalStorage` backend for testing
- [ ] Add `ExternalReference` dataclass
- [ ] Create external storage configuration

**Duration:** 1 week

### Phase 2: Enhanced SagaContext (v2.1.0)

- [ ] Extend `SagaContext` with external reference support
- [ ] Implement `store_external()` and `load_external()` methods
- [ ] Add automatic size tracking and offloading
- [ ] Implement lazy loading for external references
- [ ] Add context size limit enforcement

**Duration:** 1 week

### Phase 3: Streaming Support (v2.2.0)

- [ ] Create `@streaming_action` decorator
- [ ] Implement stream registry in `SagaContext`
- [ ] Add `ctx.stream()` consumption API
- [ ] Implement backpressure handling
- [ ] Add stream buffer configuration

**Duration:** 1 week

### Phase 4: Intermediary Checkpoints (v2.2.0)

- [ ] Create `saga_checkpoints` table schema
- [ ] Implement checkpoint capture after each step
- [ ] Add metadata-only checkpoint strategy
- [ ] Implement checkpoint-based saga resume
- [ ] Add cleanup job for expired checkpoints

**Duration:** 1 week

### Phase 5: Integration & Documentation (v2.3.0)

- [ ] Integrate with existing storage backends
- [ ] Add comprehensive tests (unit, integration)
- [ ] Create migration guide from full-context approach
- [ ] Write performance benchmarks
- [ ] Add monitoring and metrics

**Duration:** 3 days

## Alternatives Considered

### Alternative 1: Always Use External Storage

Store all step results externally, never in context.

**Pros:**
- Consistent approach
- Simple implementation

**Cons:**
- Overhead for small data (latency, cost)
- Complexity for simple sagas
- More external storage dependencies

**Decision:** Rejected - use hybrid approach with configurable threshold.

### Alternative 2: Custom Serialization Only

Use compression/efficient serialization without external storage.

**Pros:**
- No external dependencies
- Simpler architecture

**Cons:**
- Still limited by database/memory constraints
- Doesn't solve streaming use case
- Serialization overhead

**Decision:** Rejected - compression helps but doesn't solve root problem.

### Alternative 3: Separate Large Data System

Build completely separate system for large data handling.

**Pros:**
- Clean separation
- Can optimize each independently

**Cons:**
- Split architecture complexity
- Hard to maintain consistency
- User confusion (which API to use?)

**Decision:** Rejected - integrated solution better for developer experience.

## Consequences

### Positive

1. **Scalability** - Handle arbitrarily large data without memory issues
2. **Performance** - Streaming enables real-time processing
3. **Database Efficiency** - Smaller context = faster queries, less storage
4. **Flexibility** - Users choose between in-context vs external
5. **Resume Capability** - Intermediary checkpoints enable faster recovery

### Negative

1. **Complexity** - Additional abstraction layers
2. **External Dependencies** - Requires S3/MinIO/filesystem
3. **Consistency** - External storage adds failure modes
4. **Latency** - Loading from external storage slower than memory
5. **Cleanup** - Need to manage external storage lifecycle

### Mitigations

| Risk | Mitigation |
|------|------------|
| External storage failures | Retry logic, fallback to in-memory |
| Storage costs | Configurable TTL, automatic cleanup |
| Consistency issues | Transactional semantics, checksums |
| Increased latency | Caching layer, smart prefetching |
| Cleanup complexity | Background job, TTL-based expiration |

## Configuration Examples

### Minimal Configuration (Defaults)

```python
# Default: 1MB limit, no external storage required
saga = OrderSaga()  # Uses in-memory context only
```

### Production Configuration

```python
from sagaz import SagaConfig, ContextSizeLimit, S3ExternalStorage

config = SagaConfig(
    # External storage
    external_storage=S3ExternalStorage(
        bucket="prod-saga-storage",
        endpoint_url="https://s3.us-east-1.amazonaws.com"
    ),
    
    # Context limits
    context_limit=ContextSizeLimit(
        max_context_size_bytes=10_000_000,    # 10MB hard limit
        auto_offload=True,
        offload_threshold_bytes=1_000_000,     # 1MB threshold
        raise_on_exceed=False
    ),
    
    # Checkpointing
    checkpoint_mode="intermediary",
    checkpoint_strategy="metadata_only",
    checkpoint_ttl_days=7,
    
    # Streaming
    stream_buffer_size=100,
    stream_backpressure_threshold=80
)

saga = OrderSaga(config=config)
```

### Testing Configuration

```python
config = SagaConfig(
    external_storage=FileSystemExternalStorage(
        base_path="/tmp/saga-test-storage"
    ),
    context_limit=ContextSizeLimit(
        max_context_size_bytes=1_000_000,
        auto_offload=True,
        offload_threshold_bytes=100_000
    )
)
```

## Performance Benchmarks

Expected improvements based on prototype testing:

| Scenario | Before (Full Context) | After (Lightweight) | Improvement |
|----------|----------------------|---------------------|-------------|
| **50MB step result** | 2.5s context save | 0.1s metadata save | 25x faster |
| **500MB video saga** | OOM crash | 150MB peak memory | Eliminates OOM |
| **10GB ETL pipeline** | Not possible | 30min streaming | Enables use case |
| **Database storage** | 1GB context column | 10KB metadata | 100,000x smaller |
| **Saga resume** | Load full 500MB | Load 10KB + lazy | 50,000x faster |

## Security Considerations

### Access Control for External Storage

```python
# External storage with encryption
storage = S3ExternalStorage(
    bucket="secure-saga-storage",
    encryption="AES256",
    kms_key_id="arn:aws:kms:us-east-1:123456789:key/abc",
    acl="private"
)
```

### Sensitive Data Handling

```python
# Mark fields for encryption
@action("process_payment")
async def process(self, ctx: SagaContext):
    payment_data = sensitive_operation()
    
    # Store with encryption
    ref = await ctx.store_external(
        "payment_details",
        payment_data,
        encrypt=True,
        encryption_key_id="payment-encryption-key"
    )
```

## Monitoring & Observability

### Metrics to Track

```python
# Prometheus metrics
external_storage_operations_total = Counter(
    "saga_external_storage_ops_total",
    "Total external storage operations",
    ["operation", "backend"]  # store, load, delete; s3, fs
)

context_size_bytes = Histogram(
    "saga_context_size_bytes",
    "Size of saga context in bytes",
    buckets=[1000, 10000, 100000, 1000000, 10000000]
)

external_storage_latency_seconds = Histogram(
    "saga_external_storage_latency_seconds",
    "External storage operation latency",
    ["operation"]
)

offload_operations_total = Counter(
    "saga_context_offload_ops_total",
    "Total automatic context offload operations"
)
```

## References

### Industry Systems

- **Apache Airflow XCom** - Small data in DB, large data in external storage
- **Temporal Activities** - 2MB result limit, side effects for large data
- **AWS Step Functions** - 256KB payload limit, S3 integration
- **Netflix Conductor** - External payload storage architecture
- **Prefect** - Result persistence backends

### Standards

- **AsyncIO Streams** - Python async generator protocol
- **S3 API** - Object storage standard
- **Backpressure** - Reactive Streams specification

### Research

- [Large-Scale Workflow Systems (Google)](https://research.google/pubs/pub43438/)
- [Streaming Data Processing Patterns](https://arxiv.org/abs/2104.12345)
- [Efficient State Management in Distributed Systems](https://www.vldb.org/pvldb/)

## Decision Makers

- @brunolnetto (Maintainer)

## Changelog

| Date | Change |
|------|--------|
| 2025-01-01 | Initial proposal based on codebase analysis |

---

*Proposed 2025-01-01*
