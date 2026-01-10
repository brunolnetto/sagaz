# Saga Replay & Time-Travel - Getting Started

## Overview

Saga Replay enables you to reproduce failed sagas, test compensation logic, and debug production issues by replaying execution from any checkpoint with modified context.

## Quick Start

### 1. Enable Snapshots

Configure your saga to capture snapshots:

```python
from sagaz import Saga, SagaConfig, ReplayConfig
from sagaz.storage.backends import InMemorySnapshotStorage

# Configure replay
config = SagaConfig(
    replay_config=ReplayConfig(
        enable_snapshots=True,
        snapshot_strategy="before_each_step",  # Capture before each step
        retention_days=30
    )
)

# Create snapshot storage
snapshot_storage = InMemorySnapshotStorage()

# Use in saga
class OrderSaga(Saga):
    async def build(self):
        await self.add_step(
            name="reserve_inventory",
            action=self._reserve,
            compensation=self._release
        )
        await self.add_step(
            name="charge_payment",
            action=self._charge,
            compensation=self._refund
        )
        await self.add_step(
            name="ship_order",
            action=self._ship
        )

# Execute with snapshot capture
async with snapshot_storage:
    saga = OrderSaga(
        context={"order_id": "123", "amount": 99.99},
        config=config,
        snapshot_storage=snapshot_storage
    )
    await saga.execute()
```

### 2. Replay from Checkpoint

If the saga fails, replay from any step:

```python
from sagaz.core import SagaReplay

# Create replay instance
replay = SagaReplay(
    saga_id="original-saga-id-that-failed",
    snapshot_storage=snapshot_storage
)

# Replay from failed step with corrected data
result = await replay.from_checkpoint(
    step_name="charge_payment",
    context_override={
        "payment_token": "corrected_token_xyz",
        "retry_attempt": 2
    }
)

if result.status == "success":
    print(f"Replay succeeded! New saga ID: {result.new_saga_id}")
else:
    print(f"Replay failed: {result.error_message}")
```

### 3. Query Historical State

Retrieve saga state at any point in time:

```python
from sagaz.core import SagaTimeTravel
from datetime import datetime, timezone

# Query state at specific timestamp
state = await SagaTimeTravel.get_state_at(
    saga_id="abc-123",
    timestamp=datetime(2024, 12, 15, 10, 30, tzinfo=timezone.utc),
    snapshot_storage=snapshot_storage
)

if state:
    print(f"Status: {state.status}")
    print(f"Completed steps: {state.completed_steps}")
    print(f"Context at that time: {state.context}")
```

## CLI Usage

### Replay Command

```bash
# Replay from checkpoint
sagaz replay run abc-123 \
  --from-step charge_payment \
  --override payment_token=new_token \
  --storage redis \
  --storage-url redis://localhost:6379

# Dry-run mode (validate without executing)
sagaz replay run abc-123 \
  --from-step charge_payment \
  --dry-run
```

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
from sagaz.storage.backends import InMemorySnapshotStorage

storage = InMemorySnapshotStorage()
```

**Pros:** No setup, fast  
**Cons:** Data lost on restart, not distributed

### Redis (Production)

```python
from sagaz.storage.backends import RedisSnapshotStorage

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
- [CLI Reference](replay-cli.md) - Full CLI documentation
- [Time-Travel Queries](time-travel-queries.md) - Advanced historical queries
- [ADR-024](../architecture/adr/adr-024-saga-replay.md) - Design decisions

## Examples

See full examples in the repository:

- `examples/replay/payment_failure_recovery.py` - Production debugging
- `examples/replay/compliance_audit.py` - HIPAA audit scenario
- `examples/replay/compensation_testing.py` - Safe rollback testing
- `examples/replay/batch_replay.py` - Process multiple failed sagas
