# CDC Integration: Design Comparison

## Original Proposal vs. Unified Design

### ❌ Original (Separate Classes)

```
sagaz/outbox/
├── worker.py           # OutboxWorker (polling only)
├── cdc_worker.py       # CDCOutboxWorker (CDC only) ← New file
└── types.py
```

**Problems:**
- Code duplication (`_process_event` logic duplicated)
- Different deployment manifests
- Different test suites
- Harder to maintain
- More complex migration path

---

### ✅ Unified (Mode Toggle)

```
sagaz/outbox/
├── worker.py           # OutboxWorker (polling OR CDC) ← Extended
└── types.py            # WorkerMode enum ← New enum
```

**Benefits:**
- ✅ Zero code duplication
- ✅ Same deployment manifests (just change env var)
- ✅ Same test suite
- ✅ Single class to maintain
- ✅ Simple migration (toggle `SAGAZ_OUTBOX_MODE`)

---

## Code Comparison

### Original Approach

```python
# worker.py
class OutboxWorker:
    def __init__(self, storage, broker):
        ...
    
    async def _run_processing_loop(self):
        # Polling logic only
        while self._running:
            await self.process_batch()

# cdc_worker.py (NEW FILE)
class CDCOutboxWorker:  # ← Duplicate class
    def __init__(self, cdc_consumer, broker):
        ...
    
    async def _run_processing_loop(self):
        # CDC logic
        async for message in self.cdc_consumer:
            await self._process_event(event)  # ← DUPLICATED
```

### Unified Approach

```python
# worker.py (EXTENDED)
class WorkerMode(Enum):
    POLLING = "polling"
    CDC = "cdc"

class OutboxWorker:
    def __init__(
        self, 
        storage, 
        broker,
        mode: WorkerMode = WorkerMode.POLLING,  # ← NEW
        cdc_consumer: Optional[Any] = None,     # ← NEW
    ):
        self.mode = mode
        self.cdc_consumer = cdc_consumer
    
    async def _run_processing_loop(self):
        if self.mode == WorkerMode.POLLING:
            await self._run_polling_loop()  # Existing
        else:
            await self._run_cdc_loop()      # New
    
    async def _run_polling_loop(self):
        # Existing polling logic
        ...
    
    async def _run_cdc_loop(self):
        # New CDC logic
        async for message in self.cdc_consumer:
            event = self._parse_cdc_event(message)
            await self._process_event(event)  # ← REUSED!
```

---

## Deployment Comparison

### Original (Two Separate Workers)

```yaml
# outbox-worker-polling.yaml
kind: Deployment
metadata:
  name: outbox-worker-polling
spec:
  template:
    spec:
      containers:
        - name: worker
          image: sagaz/outbox-worker:latest
          # Polling-specific config

---
# outbox-worker-cdc.yaml (NEW FILE)
kind: Deployment
metadata:
  name: outbox-worker-cdc
spec:
  template:
    spec:
      containers:
        - name: cdc-worker  # ← Different image?
          image: sagaz/cdc-worker:latest
          # CDC-specific config
```

### Unified (Same Worker, Different Config)

```yaml
# outbox-worker-polling.yaml
kind: Deployment
metadata:
  name: outbox-worker-polling
spec:
  template:
    spec:
      containers:
        - name: worker
          image: sagaz/outbox-worker:latest
          env:
            - name: SAGAZ_OUTBOX_MODE
              value: "polling"  # ← Just change this!

---
# outbox-worker-cdc.yaml
kind: Deployment
metadata:
  name: outbox-worker-cdc
spec:
  template:
    spec:
      containers:
        - name: worker
          image: sagaz/outbox-worker:latest  # ← Same image!
          env:
            - name: SAGAZ_OUTBOX_MODE
              value: "cdc"  # ← Just change this!
```

---

## Testing Comparison

### Original

```python
# test_outbox_worker.py
def test_polling_worker():
    worker = OutboxWorker(storage, broker)
    ...

# test_cdc_worker.py (NEW FILE)
def test_cdc_worker():
    worker = CDCOutboxWorker(cdc_consumer, broker)
    ...  # ← Duplicate tests
```

### Unified

```python
# test_outbox_worker.py (EXTENDED)
@pytest.mark.parametrize("mode", [WorkerMode.POLLING, WorkerMode.CDC])
def test_worker_modes(mode):
    if mode == WorkerMode.POLLING:
        worker = OutboxWorker(storage, broker, mode=mode)
    else:
        worker = OutboxWorker(storage, broker, mode=mode, cdc_consumer=consumer)
    
    # Same test logic for both! ← DRY
```

---

## Summary

| Aspect | Original (Separate) | Unified (Toggle) |
|--------|---------------------|------------------|
| **Files to create** | 2+ new files | 1 enum |
| **Code duplication** | High | None |
| **Deployment complexity** | 2 manifests | 1 manifest |
| **Testing effort** | 2x | 1x |
| **Migration path** | Deploy new worker type | Change env var |
| **Maintenance** | 2 classes to maintain | 1 class |
| **Learning curve** | "Which worker do I use?" | "What mode do I need?" |

**Winner:** ✅ Unified design with mode toggle
