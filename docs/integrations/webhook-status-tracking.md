# Webhook Status Tracking

## Overview

All Sagaz web framework integrations (FastAPI, Flask, Django) provide automatic status tracking for webhook-triggered sagas. Each webhook invocation receives a unique **correlation ID** that can be used to query the status and outcome of triggered sagas.

## Architecture

```
┌─────────────┐
│  Webhook    │ POST /webhooks/order_created
│  Request    │ {"order_id": "ORD-001", ...}
└──────┬──────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│  1. Generate correlation_id                       │
│  2. Return 202 Accepted immediately               │
│  3. Process event in background                   │
└──────┬───────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│  Background Processing:                           │
│  • Fire event via trigger engine                  │
│  • Map correlation_id → saga_id(s)                │
│  • Check if saga already exists (idempotency)     │
│  • Start new sagas or return existing saga_ids    │
└──────┬───────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│  Saga Execution:                                  │
│  • Sagas run asynchronously in background         │
│  • Listeners track outcomes (complete/fail)       │
│  • Status updates stored in webhook tracking      │
└───────────────────────────────────────────────────┘
```

## Status Lifecycle

Webhook events progress through these statuses:

1. **`queued`** - Event received, queued for processing
2. **`processing`** - Event being processed to trigger sagas
3. **`triggered`** - Sagas started in background (still running)
4. **Final states:**
   - **`completed`** - All triggered sagas succeeded
   - **`completed_with_failures`** - Some sagas succeeded, some failed
   - **`failed`** - All sagas failed or webhook processing error

## API Usage

### Trigger Webhook

```bash
curl -X POST http://localhost:8000/webhooks/order_created \
  -H "Content-Type: application/json" \
  -d '{"order_id": "ORD-001", "amount": 99.99}'
```

**Response** (202 Accepted):
```json
{
  "status": "accepted",
  "source": "order_created",
  "message": "Event queued for processing",
  "correlation_id": "abc-123-xyz-456"
}
```

### Check Status

```bash
curl http://localhost:8000/webhooks/order_created/status/abc-123-xyz-456
```

**Response** (while running):
```json
{
  "correlation_id": "abc-123-xyz-456",
  "source": "order_created",
  "status": "triggered",
  "saga_ids": ["17cbf86e-5a16-5029-b416-c385b19f0d8e"],
  "message": "Event triggered 1 saga(s), waiting for completion"
}
```

**Response** (after completion):
```json
{
  "correlation_id": "abc-123-xyz-456",
  "source": "order_created",
  "status": "completed",
  "saga_ids": ["17cbf86e-5a16-5029-b416-c385b19f0d8e"],
  "saga_statuses": {
    "17cbf86e-5a16-5029-b416-c385b19f0d8e": "completed"
  },
  "message": "All 1 saga(s) completed successfully"
}
```

**Response** (after failure):
```json
{
  "correlation_id": "def-456-uvw-789",
  "source": "order_created",
  "status": "failed",
  "saga_ids": ["17cbf86e-5a16-5029-b416-c385b19f0d8e"],
  "saga_statuses": {
    "17cbf86e-5a16-5029-b416-c385b19f0d8e": "failed"
  },
  "saga_errors": {
    "17cbf86e-5a16-5029-b416-c385b19f0d8e": "Payment declined: $1500.0 exceeds limit"
  },
  "message": "Saga execution failed"
}
```

## Idempotency Handling

When a saga is configured with an `idempotency_key`, multiple webhook invocations with the same key will NOT create duplicate sagas:

```python
@trigger(
    source="order_created",
    idempotency_key="order_id",  # Deduplication based on order_id
    max_concurrent=10,
)
def handle_order_created(self, event: dict) -> dict | None:
    return {"order_id": event["order_id"], ...}
```

**Behavior:**
- First webhook with `order_id="ORD-001"` → Creates saga with deterministic saga_id
- Second webhook with `order_id="ORD-001"` → Returns existing saga_id, does NOT run again
- Each webhook gets a unique correlation_id for tracking
- Status endpoint immediately shows the existing saga's current/final state

**Example:**

```bash
# First request
curl -X POST http://localhost:8000/webhooks/order_created \
  -d '{"order_id": "ORD-001", "amount": 99.99}'
# → Returns correlation_id: "aaa-111"
# → Creates and runs saga

# Check status
curl http://localhost:8000/webhooks/order_created/status/aaa-111
# → status: "completed" (after saga finishes)

# Second request (SAME order_id)
curl -X POST http://localhost:8000/webhooks/order_created \
  -d '{"order_id": "ORD-001", "amount": 99.99}'
# → Returns correlation_id: "bbb-222" (NEW correlation_id)
# → Returns SAME saga_id (no duplicate saga created)

# Check status
curl http://localhost:8000/webhooks/order_created/status/bbb-222
# → status: "completed" (immediately shows existing saga's status)
# → saga_ids: ["<same-saga-id>"]
```

## Custom Correlation IDs

Provide your own correlation ID for distributed tracing:

```bash
curl -X POST http://localhost:8000/webhooks/order_created \
  -H "X-Correlation-ID: my-trace-123" \
  -d '{"order_id": "ORD-001", "amount": 99.99}'
```

The provided correlation ID will be:
- Returned in the response
- Used for status lookups
- Propagated through saga execution
- Available in logs for tracing

## See Also

- Event Triggers Guide
- Idempotency Patterns  
- Distributed Tracing
- Production Deployment
