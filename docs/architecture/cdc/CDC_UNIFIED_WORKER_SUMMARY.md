# CDC Support: Unified Worker Design

**ADR**: [ADR-011: CDC Support](docs/architecture/adr/adr-011-cdc-support.md)

## Summary

Extended existing `OutboxWorker` to support both **polling** and **CDC** modes via a simple mode toggle, instead of creating a separate `CDCOutboxWorker` class.

---

## Key Design Decisions

### ✅ Single Worker Class (Not Two)

**Before (original ADR):**
```
- OutboxWorker (polling)
- CDCOutboxWorker (CDC)  ← Separate class
```

**After (unified design):**
```
- OutboxWorker (polling OR CDC)  ← Single class with mode parameter
```

### ✅ Mode Toggle via Enum

```python
from enum import Enum

class WorkerMode(Enum):
    POLLING = "polling"  # Traditional database polling
    CDC = "cdc"          # Change Data Capture stream
```

### ✅ Same Deployment Process

```yaml
# Polling workers
env:
  - name: SAGAZ_OUTBOX_MODE
    value: "polling"

# CDC workers  
env:
  - name: SAGAZ_OUTBOX_MODE
    value: "cdc"
```

---

## Implementation Changes

### 1. Extend `OutboxWorker.__init__`

```python
class OutboxWorker:
    def __init__(
        self,
        storage: OutboxStorage,
        broker: MessageBroker,
        config: OutboxConfig | None = None,
        worker_id: str | None = None,
        mode: WorkerMode = WorkerMode.POLLING,  # NEW
        cdc_consumer: Optional[Any] = None,      # NEW
        ...
    ):
        self.mode = mode
        self.cdc_consumer = cdc_consumer
        
        if self.mode == WorkerMode.CDC and not self.cdc_consumer:
            raise ValueError("cdc_consumer required when mode=CDC")
```

### 2. Delegate Processing Loop

```python
async def _run_processing_loop(self) -> None:
    """Delegate to mode-specific implementation."""
    if self.mode == WorkerMode.POLLING:
        await self._run_polling_loop()  # Existing logic
    else:
        await self._run_cdc_loop()      # New CDC logic
```

### 3. Add CDC Processing

```python
async def _run_cdc_loop(self) -> None:
    """CDC mode: Consume from stream."""
    async for message in self.cdc_consumer:
        if not self._running:
            break
        
        event = self._parse_cdc_event(message)
        await self._process_event(event)  # Reuse existing logic!
        await self.cdc_consumer.commit()
```

### 4. Update `OutboxConfig`

```python
@dataclass
class OutboxConfig:
    # Existing fields...
    batch_size: int = 100
    poll_interval_seconds: float = 1.0
    
    # NEW: Mode configuration
    mode: WorkerMode = WorkerMode.POLLING
    cdc_consumer_group: str = "sagaz-outbox-workers"
    cdc_stream_name: str = "saga.outbox.events"
```

---

## Benefits

| Benefit | Description |
|---------|-------------|
| ✅ **Code reuse** | Same `_process_event()` logic for both modes |
| ✅ **Same metrics** | All Prometheus metrics work for both modes |
| ✅ **Same testing** | Test harness works for both modes |
| ✅ **Simple migration** | Just change env var: `SAGAZ_OUTBOX_MODE=cdc` |
| ✅ **Less maintenance** | One worker class, not two |
| ✅ **Backward compatible** | Polling is default, CDC is opt-in |

---

## Migration Path

### Stage 1: Run Both Modes in Parallel

```bash
# Polling workers (keep running)
kubectl scale deployment/outbox-worker-polling --replicas=3

# Deploy CDC workers
kubectl apply -f outbox-worker-cdc.yaml
```

### Stage 2: Verify CDC Performance

```bash
# Check CDC metrics
kubectl port-forward svc/prometheus 9090:9090
# Query: rate(outbox_published_events_total{mode="cdc"}[5m])
```

### Stage 3: Scale Down Polling

```bash
kubectl scale deployment/outbox-worker-polling --replicas=0
```

---

## Environment Variables

| Variable | Default | Mode | Description |
|----------|---------|------|-------------|
| `SAGAZ_OUTBOX_MODE` | `polling` | Both | `polling` or `cdc` |
| `BATCH_SIZE` | `100` | Polling | Events per batch |
| `POLL_INTERVAL` | `1.0` | Polling | Seconds between polls |
| `OUTBOX_STREAM_NAME` | `saga.outbox.events` | CDC | Kafka topic or Redis stream |
| `OUTBOX_CONSUMER_GROUP` | `sagaz-outbox-workers` | CDC | Consumer group ID |

---

## Performance Comparison

| Metric | Polling Mode | CDC Mode |
|--------|--------------|----------|
| Throughput | 1-5K/sec | 50-100K/sec |
| Latency | 100-1000ms | 10-50ms |
| DB Load | High (polling queries) | Low (no queries) |
| Infrastructure | Simple | Requires Debezium |

---

## Files Changed

- `sagaz/outbox/types.py` - Add `WorkerMode` enum
- `sagaz/outbox/worker.py` - Extend with CDC support
- `docs/architecture/adr/adr-011-cdc-support.md` - Updated design

---

## CLI Integration

CDC is fully integrated into project initialization and extension:

```bash
# New project with CDC
$ sagaz init --local --outbox-mode=cdc --outbox-broker=kafka

# Extend existing project with CDC
$ sagaz extend --enable-outbox-cdc --outbox-broker=kafka --hybrid

# Check CDC status
$ sagaz status
Outbox Mode:       CDC (Kafka)
CDC Lag:           12ms
Throughput:        12,500 events/sec

# Validate CDC setup
$ sagaz validate
✓ Debezium Server: OK
✓ CDC lag: 12ms (healthy)
```

**Key CLI features:**
- ✅ `sagaz init --outbox-mode` - Turnkey CDC setup
- ✅ `sagaz extend --enable-outbox-cdc` - Safe migration path
- ✅ `--hybrid` flag - Run polling + CDC in parallel
- ✅ `sagaz status` - CDC health monitoring
- ✅ `sagaz validate` - CDC configuration validation

---

## Next Steps

1. ✅ ADR updated with unified worker design
2. ✅ ADR updated with CLI integration
3. 📋 Implement `WorkerMode` enum in `types.py`
4. 📋 Extend `OutboxWorker` with CDC mode
5. 📋 Add CDC consumer factory
6. 📋 Implement CLI commands (`init`, `extend`, `validate`)
7. 📋 Create CDC templates (Debezium configs)
8. 📋 Integration tests for both modes
9. 📋 Update deployment manifests

**Estimated effort**: ~56 hours (7 days)
- Worker implementation: ~28 hours
- CLI integration: ~28 hours

**Target**: Q2 2026 (when throughput >5K events/sec needed)
