# Idempotency Behavior: Webhook Integration Layer

## Overview

This document explains how the webhook integration layer handles missing idempotency keys, ensuring clients receive immediate, actionable feedback when configuration requirements aren't met.

## Problem Statement

**Question:** "What happens when the developer adds `idempotency_key` to the trigger decorator, but the client forgets to send that field in the webhook request?"

**Answer:** The system returns **HTTP 400 Bad Request** immediately with a clear error message explaining what's missing and how to fix it.

## Architecture

### Three-Layer Validation

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: STARTUP TIME (Registration)                       │
│ When: Application starts, triggers registered              │
│ Check: Is idempotency_key configured?                      │
│ Action: ⚠️  Warn if missing (educational)                   │
└─────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: HTTP REQUEST (Webhook Handler)                    │
│ When: Webhook POST received                                │
│ Check: Does payload contain required idempotency field?    │
│ Action: ❌ Return 400 if missing (immediate feedback)       │
└─────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: TRIGGER ENGINE (Background Processing)            │
│ When: Event fired through trigger engine                   │
│ Check: Extract and validate idempotency key                │
│ Action: ❌ Raise IdempotencyKeyMissingInPayloadError        │
└─────────────────────────────────────────────────────────────┘
```

### Why Layer 2 (HTTP Validation)?

**Problem:** Without HTTP-level validation:
1. Webhook returns `202 Accepted` ✅
2. Client thinks request succeeded ✅
3. Background processing fails ❌
4. Client must poll status endpoint to discover error ❌
5. Poor developer experience ❌

**Solution:** Validate **before accepting** the request:
1. Webhook validates payload upfront
2. Returns `400 Bad Request` if validation fails ❌
3. Client knows immediately what's wrong ✅
4. No background failures ✅
5. Excellent developer experience ✅

## Implementation Details

### FastAPI Integration

```python
# sagaz/integrations/fastapi.py

@router.post("/{source}")
async def webhook_handler(source: str, request: Request, background_tasks: BackgroundTasks):
    """Handle webhook events with upfront validation."""
    payload = await request.json()
    correlation_id = request.headers.get("X-Correlation-ID") or generate_correlation_id()
    
    # ✅ VALIDATE UPFRONT - Before accepting request
    try:
        from sagaz.triggers.registry import TriggerRegistry
        triggers = TriggerRegistry.get_triggers(source)
        
        for trigger in triggers:
            metadata = trigger.metadata
            if metadata.idempotency_key:
                key_name = metadata.idempotency_key if isinstance(metadata.idempotency_key, str) else None
                if key_name and isinstance(payload, dict) and key_name not in payload:
                    raise IdempotencyKeyMissingInPayloadError(
                        saga_name=trigger.saga_class.__name__,
                        source=source,
                        key_name=key_name,
                        payload_keys=list(payload.keys()),
                    )
    except IdempotencyKeyMissingInPayloadError as e:
        # ❌ Return 400 Bad Request immediately
        return JSONResponse(
            status_code=400,
            content={
                "status": "rejected",
                "source": source,
                "error": "missing_idempotency_key",
                "message": f"Required field '{e.key_name}' is missing from payload",
                "details": {
                    "saga": e.saga_name,
                    "required_field": e.key_name,
                    "payload_keys": e.payload_keys,
                },
                "help": f"Include '{e.key_name}' in your request payload to ensure idempotent processing",
            },
        )
    
    # ✅ Validation passed - accept and process in background
    _webhook_tracking[correlation_id] = {"status": "queued", "saga_ids": [], "source": source}
    
    async def process_event():
        saga_ids = await fire_event(source, payload)
        _webhook_tracking[correlation_id]["saga_ids"] = saga_ids
        _webhook_tracking[correlation_id]["status"] = "triggered"
    
    background_tasks.add_task(process_event)
    
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "source": source,
            "message": "Event queued for processing",
            "correlation_id": correlation_id,
        },
    )
```

### Flask & Django Integrations

The Flask and Django integrations follow the **exact same pattern**:
- Validate payload upfront
- Return 400 if validation fails
- Only accept request if validation passes

See `sagaz/integrations/flask.py` and `sagaz/integrations/django.py` for implementations.

## Client Experience

### Scenario 1: Missing Idempotency Key ❌

```bash
# Saga configuration
@trigger(source="order_created", idempotency_key="order_id")
def on_order(self, event):
    return {"order_id": event["order_id"], "amount": event["amount"]}

# Client request (missing order_id)
$ curl -X POST http://localhost:8000/webhooks/order_created \
       -H "Content-Type: application/json" \
       -d '{"amount": 100.0}'

# Response: 400 Bad Request
{
  "status": "rejected",
  "source": "order_created",
  "error": "missing_idempotency_key",
  "message": "Required field 'order_id' is missing from payload",
  "details": {
    "saga": "OrderSaga",
    "required_field": "order_id",
    "payload_keys": ["amount"]
  },
  "help": "Include 'order_id' in your request payload to ensure idempotent processing"
}
```

**Client Action:** Add `order_id` to the request payload.

### Scenario 2: Idempotency Key Present ✅

```bash
# Client request (with order_id)
$ curl -X POST http://localhost:8000/webhooks/order_created \
       -H "Content-Type: application/json" \
       -d '{"order_id": "ORD-123", "amount": 100.0}'

# Response: 202 Accepted
{
  "status": "accepted",
  "source": "order_created",
  "message": "Event queued for processing",
  "correlation_id": "abc-123-xyz"
}

# Check status later
$ curl http://localhost:8000/webhooks/order_created/status/abc-123-xyz

# Response: Processing complete
{
  "correlation_id": "abc-123-xyz",
  "source": "order_created",
  "status": "completed",
  "saga_ids": ["17cbf86e-5a16-5029-b416-c385b19f0d8e"],
  "saga_statuses": {
    "17cbf86e-5a16-5029-b416-c385b19f0d8e": "completed"
  },
  "message": "All 1 saga(s) completed successfully"
}
```

### Scenario 3: Duplicate Request (Idempotent) ✅

```bash
# First request
$ curl -X POST http://localhost:8000/webhooks/order_created \
       -d '{"order_id": "ORD-123", "amount": 100.0}'

{
  "status": "accepted",
  "correlation_id": "abc-123-xyz",
  "saga_ids": ["17cbf86e-5a16-5029-b416-c385b19f0d8e"]  # New saga created
}

# Second request (same order_id)
$ curl -X POST http://localhost:8000/webhooks/order_created \
       -d '{"order_id": "ORD-123", "amount": 100.0}'

{
  "status": "accepted",
  "correlation_id": "def-456-uvw",
  "saga_ids": ["17cbf86e-5a16-5029-b416-c385b19f0d8e"]  # Same saga ID (idempotent)
}

# Status check shows existing saga
$ curl http://localhost:8000/webhooks/order_created/status/def-456-uvw

{
  "status": "completed",
  "saga_ids": ["17cbf86e-5a16-5029-b416-c385b19f0d8e"],
  "saga_statuses": {
    "17cbf86e-5a16-5029-b416-c385b19f0d8e": "completed"  # Already completed
  }
}
```

**Behavior:** Same `order_id` → Same saga ID → Idempotent (no duplicate execution)

## Design Principles

### 1. **Fail Fast**
- Validation happens at the earliest possible point (HTTP layer)
- No silent failures or deferred error discovery

### 2. **Clear Feedback**
- Error messages explain exactly what's wrong
- Include actionable guidance on how to fix
- Show available vs. required fields

### 3. **Consistent Behavior**
- All three integrations (FastAPI, Flask, Django) behave identically
- Predictable developer experience across frameworks

### 4. **Non-Breaking**
- Triggers without `idempotency_key` continue to work (with warnings)
- Validation only enforced when developer explicitly configures idempotency

### 5. **Agnostic**
- No business logic (e.g., "financial operations require idempotency")
- Generic validation applies to all use cases
- Framework-agnostic (same behavior across FastAPI/Flask/Django)

## System Behavior Matrix

| Scenario | Trigger Config | Payload | HTTP Response | Saga Execution |
|----------|---------------|---------|---------------|----------------|
| No idempotency configured | `idempotency_key=None` | Any | `202 Accepted` | ✅ Random UUID, executes normally |
| Idempotency configured, field present | `idempotency_key="order_id"` | `{"order_id": "123"}` | `202 Accepted` | ✅ Deterministic UUID5, executes |
| Idempotency configured, field missing | `idempotency_key="order_id"` | `{"amount": 100}` | `400 Bad Request` | ❌ Rejected, no execution |
| Duplicate request (idempotent) | `idempotency_key="order_id"` | `{"order_id": "123"}` (2nd time) | `202 Accepted` | ✅ Returns existing saga, no re-execution |

## Integration Testing

### Test: Missing Idempotency Key Returns 400

```python
import pytest
from fastapi.testclient import TestClient

@pytest.mark.asyncio
async def test_webhook_missing_idempotency_key_returns_400(app):
    """Webhook should return 400 when required idempotency key is missing."""
    client = TestClient(app)
    
    # POST without order_id (required by OrderSaga trigger)
    response = client.post(
        "/webhooks/order_created",
        json={"amount": 100.0},
    )
    
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "rejected"
    assert data["error"] == "missing_idempotency_key"
    assert data["details"]["required_field"] == "order_id"
    assert "help" in data
```

### Test: Valid Request Returns 202

```python
@pytest.mark.asyncio
async def test_webhook_with_idempotency_key_returns_202(app):
    """Webhook should accept request when idempotency key is present."""
    client = TestClient(app)
    
    response = client.post(
        "/webhooks/order_created",
        json={"order_id": "ORD-123", "amount": 100.0},
    )
    
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert "correlation_id" in data
```

## Future Enhancements

1. **Rate Limiting:** Return 429 when idempotency checks detect high duplicate request rates
2. **Detailed Diagnostics:** Include validation history in status endpoint
3. **OpenAPI Schema:** Auto-generate schemas with idempotency requirements
4. **Retry Guidance:** Suggest exponential backoff for failed validations

## Related Documentation

- [ADR-025: Event-Driven Triggers](/docs/architecture/adr/adr-025-event-driven-triggers.md)
- [Idempotency Validation Implementation](/docs/architecture/implementation-plans/idempotency-validation.md)
- [Event Triggers Implementation Plan](/docs/architecture/implementation-plans/event-triggers-implementation-plan.md)

## Summary

The webhook integration layer provides **immediate, actionable feedback** when idempotency requirements aren't met:

✅ **Layer 1 (Startup):** Warn about missing idempotency configuration  
✅ **Layer 2 (HTTP):** Validate and return 400 before accepting request  
✅ **Layer 3 (Engine):** Final validation with clear error propagation  

Result: **Excellent developer experience** with fail-fast validation and clear guidance at every layer.
