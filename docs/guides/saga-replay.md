# Saga Replay & Time-Travel - Getting Started

## Overview

Saga Replay enables you to reproduce failed sagas, test compensation logic, and debug production issues by replaying execution from any checkpoint with modified context.

## Quick Start

### 1. Enable Snapshots

Give the saga's configuration a `ReplayConfig` and a snapshot storage:

```python
from sagaz import ReplayConfig, Saga, SagaConfig, SnapshotStrategy, action, compensate
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage

snapshots = InMemorySnapshotStorage()
config = SagaConfig(
    replay_config=ReplayConfig(
        enable_snapshots=True,
        snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
        retention_days=30,
    ),
    snapshot_storage=snapshots,
)


class OrderSaga(Saga):
    saga_name = "order"

    @action("reserve_inventory")
    async def reserve(self, ctx): ...

    @compensate("reserve_inventory")
    async def release(self, ctx): ...

    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge(self, ctx): ...

    @action("ship_order", depends_on=["charge_payment"])
    async def ship(self, ctx): ...


await OrderSaga(config=config).run({"order_id": "123", "amount": 99.99}, saga_id="order-123")
```

A snapshot holds the saga's context and the steps completed so far, in execution order.
The strategy says when one is taken:

| `snapshot_strategy` | A snapshot is taken |
|---|---|
| `BEFORE_EACH_STEP` | Before each step runs |
| `AFTER_EACH_STEP` | After each step completes |
| `ON_FAILURE` (default) | When a step fails, before compensation |
| `ON_COMPLETION` | When the saga completes |

A snapshot that cannot be saved is logged, and the run goes on. Snapshot storage
identifies a saga by a UUID: a saga id that is not one (`"order-123"`) gets a stable
UUID, and `SagaReplay` and `SagaTimeTravel` take either form.

### 2. Replay from Checkpoint

If the saga fails, replay it from a step, with a corrected context:

```python
from sagaz.core.replay.saga_replay import SagaReplay

replay = SagaReplay(
    "order-123",                                         # the run that failed
    snapshots,
    saga_factory=lambda saga_name: OrderSaga(config=config),
)
result = await replay.from_checkpoint(
    step_name="charge_payment",
    context_override={"payment_token": "corrected_token_xyz"},
)

if result.replay_status == "success":
    print(f"Replay succeeded! New saga ID: {result.new_saga_id}")
else:
    print(f"Replay failed: {result.error_message}")
```

- **A new run:** the replay runs under a new saga id; the original run is not changed.
- **Adopted steps:** the steps the snapshot completed are not run again. If the replay
  fails later, they are compensated with the others.
- **After a rollback:** a run that failed compensated its completed steps, so their
  effects are gone, while the snapshot still lists them as completed. Replaying from the
  failed step adopts them as done. Do that only if those effects still hold; otherwise
  replay from the first step whose effect was undone.
- **What a snapshot holds:** the saga's public context, without the engine's own
  bookkeeping keys.
- **Without `SagaReplay`:** `await saga.run_from_snapshot(snapshot, context_override)`
  does the same from a snapshot you loaded, and returns and raises what `run()` does.
- **The classic engine:** a factory may also return a classic `sagaz.core.saga.Saga`,
  replayed with its `execute_from_snapshot`.

### 3. Query Historical State

Read the saga's state at a point in time:

```python
from datetime import UTC, datetime

from sagaz.core.replay.time_travel import SagaTimeTravel

travel = SagaTimeTravel("order-123", snapshots)
state = await travel.get_state_at(datetime(2024, 12, 15, 10, 30, tzinfo=UTC))

if state:
    print(f"Step: {state.current_step}")
    print(f"Completed steps: {state.completed_steps}")
    print(f"Context at that time: {state.context}")
```

## CLI Usage

The CLI reads the snapshots your sagas wrote: point `--storage` and `--storage-url` at
the same snapshot storage (`redis`, `postgres`, or a `filesystem` directory, the
default `./saga-snapshots`). An in-memory snapshot storage lives in the process that took
the snapshots, so the CLI cannot read it.

### Replay Command

Replaying runs the saga again, so the CLI needs to build it: `--saga module:attribute`
names the saga class, or a factory `(saga_name) -> saga` (sync or async) that adds its
steps.

```bash
# Replay from checkpoint
sagaz replay run 3f2c9a7e-0b1d-4c6e-9a51-6d2f0e8b7c41 \
  --from-step charge_payment \
  --override payment_token=new_token \
  --storage redis \
  --storage-url redis://localhost:6379 \
  --saga myapp.sagas:build_order_saga

# Dry-run mode (validate without executing; no --saga needed)
sagaz replay run 3f2c9a7e-0b1d-4c6e-9a51-6d2f0e8b7c41 \
  --from-step charge_payment \
  --storage-url ./saga-snapshots \
  --dry-run
```

Every command exits non-zero when it fails.

### Time-Travel Query

```bash
# Query state at specific time
sagaz replay time-travel abc-123 \
  --at "2024-12-15T10:30:00Z" \
  --format json

# Output:
# {
#   "saga_id": "abc-123",
#   "status": "executing",
#   "completed_steps": ["reserve_inventory", "charge_payment"],
#   "context": {...}
# }
```

### List State Changes

```bash
# List all state changes for a saga
sagaz replay list-changes abc-123 --limit 50

# Filter by time range
sagaz replay list-changes abc-123 \
  --after "2024-12-15T00:00:00Z" \
  --before "2024-12-15T23:59:59Z"
```

## Storage Backends

### In-Memory (Development)

```python
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage

storage = InMemorySnapshotStorage()
```

**Pros:** No setup, fast  
**Cons:** Data lost on restart, not distributed

### Redis (Production)

```python
from sagaz.core.storage.backends.redis import RedisSnapshotStorage

storage = RedisSnapshotStorage(
    redis_url="redis://localhost:6379",
    default_ttl=2592000,  # 30 days
    enable_compression=True
)
```

**Pros:** Distributed, automatic TTL, compression  
**Cons:** Requires Redis server

See [Storage Backends Guide](replay-storage-backends.md) for more options.

## Common Patterns

### Pattern 1: Debug Production Failures

**Scenario:** Payment gateway fails for 1,500 orders during outage.

```python
# Find failed sagas
failed_sagas = await snapshot_storage.list_snapshots(
    saga_id_prefix="order_",
    status="failed"
)

# Replay each with backup gateway
for snapshot in failed_sagas:
    replay = SagaReplay(snapshot.saga_id, snapshot_storage)
    await replay.from_checkpoint(
        step_name="charge_payment",
        context_override={
            "payment_gateway": "backup_gateway_url"
        }
    )
```

### Pattern 2: Test Compensation Logic

**Scenario:** Need to verify rollback behavior without production impact.

```python
# Replay and force failure to trigger compensation
result = await replay.from_checkpoint(
    step_name="ship_order",
    force_failure=True,  # Will trigger compensations
    context_override={"test_mode": True}
)

# Verify compensations executed correctly
assert await inventory_service.check_released(order_id)
assert await payment_service.check_refunded(order_id)
```

### Pattern 3: Compliance Audit

**Scenario:** HIPAA auditor asks for patient consent saga state on specific date.

```python
# Time-travel to audit date
state = await SagaTimeTravel.get_state_at(
    saga_id="patient-consent-789",
    timestamp=datetime(2024, 7, 15, 14, 30, tzinfo=timezone.utc),
    snapshot_storage=snapshot_storage
)

# Generate audit report
audit_report = {
    "saga_id": state.saga_id,
    "timestamp": state.created_at,
    "status": state.status,
    "patient_id": state.context["patient_id"],
    "consent_given": state.context["consent_status"],
    "hipaa_compliance": True
}
```

## Advanced Features

### Dry-Run Validation

Test replay without executing:

```python
result = await replay.from_checkpoint(
    step_name="charge_payment",
    dry_run=True  # Only validate, don't execute
)

if result.status == "valid":
    # Proceed with actual replay
    pass
```

### Context Encryption

Protect sensitive data in snapshots:

```python
from sagaz.core import ComplianceConfig, ComplianceManager

compliance_config = ComplianceConfig(
    enable_encryption=True,
    sensitive_fields=["credit_card", "ssn", "password"],
    encryption_key="your-encryption-key"  # Use KMS in production
)

# Snapshots will automatically encrypt sensitive fields
```

### Async Saga Factory

For complex saga instantiation:

```python
async def create_order_saga(context: dict) -> OrderSaga:
    # Load dependencies, validate input, etc.
    inventory = await InventoryService.connect()
    payment = await PaymentGateway.connect()
    
    return OrderSaga(
        context=context,
        inventory=inventory,
        payment=payment
    )

# Use in replay
result = await replay.from_checkpoint(
    step_name="charge_payment",
    saga_factory=create_order_saga  # Async factory function
)
```

## Best Practices

### 1. Snapshot Strategy

- **Development/Testing:** `"before_each_step"` for maximum replay flexibility
- **Production:** `"before_each_step"` for critical sagas, `"on_failure"` for others

### 2. Retention Policy

- **HIPAA/SOC2:** 7 years (2,555 days)
- **Standard:** 30-90 days
- **Development:** 7 days

### 3. Context Overrides

Only override fields that need correction:

```python
# Good: Surgical override
context_override={"payment_token": "new_token"}

# Bad: Full context replacement (loses other data)
context_override={...full_context...}
```

### 4. Error Handling

Always check replay result:

```python
result = await replay.from_checkpoint(...)

if result.status != "success":
    logger.error(
        f"Replay failed: {result.error_message}",
        saga_id=result.original_saga_id,
        step_name=step_name
    )
    # Alert ops team, retry, or escalate
```

## Troubleshooting

### "Snapshot not found"

**Cause:** Snapshots may have been deleted or expired.

**Solution:**
```python
# Check if snapshots exist
snapshots = await snapshot_storage.list_snapshots(saga_id)
if not snapshots:
    # Saga too old or snapshots disabled
    pass
```

### "Context override failed"

**Cause:** Invalid context data type or missing required fields.

**Solution:**
```python
# Validate context before replay
result = await replay.from_checkpoint(
    step_name="charge_payment",
    dry_run=True  # Validate first
)
```

### "Replay succeeded but saga still failing"

**Cause:** Original issue may still exist (e.g., external service down).

**Solution:** Verify external dependencies before replay:
```python
# Check dependencies first
if not await payment_gateway.health_check():
    raise Exception("Payment gateway still unavailable")

# Then replay
result = await replay.from_checkpoint(...)
```

## Next Steps

- [Storage Backends Guide](replay-storage-backends.md) - Choose the right backend
- CLI Reference - Full CLI documentation
- Time-Travel Queries - Advanced historical queries
- [ADR-024](../architecture/adr/adr-024-saga-replay.md) - Design decisions

## Examples

See full examples in the repository:

- `examples/replay/payment_failure_recovery.py` - Production debugging
- `examples/replay/compliance_audit.py` - HIPAA audit scenario
- `examples/replay/compensation_testing.py` - Safe rollback testing
- `examples/replay/batch_replay.py` - Process multiple failed sagas
