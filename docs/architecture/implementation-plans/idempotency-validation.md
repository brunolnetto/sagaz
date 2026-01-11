# Idempotency Validation Implementation

## Overview

Enhanced the trigger system's idempotency protection with a two-tier validation approach:
1. **Warn** when triggers lack `idempotency_key` (startup time)
2. **Error** when declared `idempotency_key` is missing from payload (runtime)

## Motivation

**Problem:** When developers configure `idempotency_key` on triggers but forget to include that field in webhook payloads, the system silently fell back to random UUIDs, **defeating idempotency protection** without any indication.

**Example of Silent Failure:**
```python
@trigger(source="order_created", idempotency_key="order_id")
def on_order(self, event: dict) -> dict:
    return {"amount": event["amount"]}  # Forgot order_id!
```

**Old Behavior:** Webhook without `order_id` → Random UUID generated → Duplicate sagas executed ❌

**New Behavior:** Webhook without `order_id` → Clear error raised → Developer fixes payload ✅

## Implementation

### 1. Warning on Registration (Startup Time)

When a trigger is registered **without** `idempotency_key`, emit a warning:

**File:** `sagaz/triggers/registry.py`

```python
@classmethod
def register(cls, saga_class, method_name, metadata):
    # ... registration logic ...
    
    if not metadata.idempotency_key:
        logger.warning(
            f"\n{'=' * 70}\n"
            f"⚠️  IDEMPOTENCY WARNING\n"
            f"Trigger: {saga_class.__name__}.{method_name}\n"
            f"Source: {source}\n"
            f"\n"
            f"No idempotency key configured. This trigger may execute\n"
            f"duplicate sagas if the same event is received multiple times.\n"
            # ... helpful guidance ...
        )
```

**Benefits:**
- ✅ Non-breaking: Existing code continues to work
- ✅ Educational: Teaches developers about idempotency
- ✅ Visible: Appears in logs during application startup

### 2. Error on Payload Validation (Runtime)

When trigger declares `idempotency_key` but payload is missing that field, **raise error**:

**File:** `sagaz/core/exceptions.py`

```python
class IdempotencyKeyMissingInPayloadError(SagaError):
    """Raised when trigger declares idempotency_key but payload lacks the field."""
    
    def __init__(self, saga_name, source, key_name, payload_keys):
        message = (
            f"║  Expected field: '{key_name}'                                  ║\n"
            f"║  Payload keys: {', '.join(payload_keys)}                       ║\n"
            # ... error details and solutions ...
        )
        super().__init__(message)
```

**File:** `sagaz/triggers/engine.py`

```python
def _derive_saga_id(self, metadata, payload, saga_class):
    key_logic = metadata.idempotency_key
    
    if not key_logic:
        return None  # No idempotency configured - generate random UUID
    
    key_str = self._extract_key_value(key_logic, payload)
    
    if not key_str:
        # FAIL FAST: Developer declared idempotency but payload lacks field
        raise IdempotencyKeyMissingInPayloadError(
            saga_name=saga_class.__name__,
            source=metadata.source,
            key_name=key_logic if isinstance(key_logic, str) else "<callable>",
            payload_keys=list(payload.keys()) if isinstance(payload, dict) else []
        )
    
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, key_str))
```

**Error Propagation:**

The error is re-raised through the processing chain:
- `_derive_saga_id()` raises it
- `_process_trigger()` re-raises configuration errors (unlike transient errors)
- `fire()` checks results and re-raises if present

**Benefits:**
- ✅ Fail fast: Catches misconfiguration immediately
- ✅ Clear guidance: Error message explains exactly what's wrong
- ✅ Prevents silent bugs: No more duplicate sagas due to missing fields

## Behavior Matrix

| Scenario | `idempotency_key` | Payload Has Field | Behavior |
|----------|-------------------|-------------------|----------|
| No idempotency configured | `None` | N/A | ⚠️ **Warn** on registration, generate random UUID |
| String key, field present | `"order_id"` | ✅ Yes | ✅ Derive deterministic UUID5 |
| String key, field missing | `"order_id"` | ❌ No | ❌ **Raise** `IdempotencyKeyMissingInPayloadError` |
| Callable key, returns value | `lambda e: e['id']` | ✅ Yes | ✅ Derive deterministic UUID5 |
| Callable key, returns None | `lambda e: e.get('missing')` | ❌ No | ❌ **Raise** `IdempotencyKeyMissingInPayloadError` |

## Testing

**Warning Tests:**
- `tests/unit/test_idempotency_enforcement.py::TestIdempotencyWarnings`
  - Triggers without `idempotency_key` emit warnings
  - Triggers with `idempotency_key` don't emit warnings
  - Warning messages contain helpful guidance

**Error Tests:**
- `tests/unit/test_idempotency_enforcement.py::TestIdempotencyKeyMissing`
  - Missing string key field raises error
  - Callable returning None raises error
  - Empty payload raises error
  - Correct payload succeeds

**Updated Tests:**
- `tests/unit/triggers/test_triggers.py::TestIdempotency`
  - Changed `test_idempotency_missing_key_field_generates_random_id` to expect error

## Developer Experience

### Good Pattern ✅

```python
@trigger(source="order_created", idempotency_key="order_id")
def on_order(self, event: dict) -> dict:
    return {
        "order_id": event["order_id"],  # ✅ Include idempotency field
        "amount": event["amount"]
    }

# Webhook payload:
POST /webhooks/order_created
{"order_id": "ORD-123", "amount": 100.0}  # ✅ Has order_id
```

### Bad Pattern (Caught) ❌

```python
@trigger(source="order_created", idempotency_key="order_id")
def on_order(self, event: dict) -> dict:
    return {"amount": event["amount"]}  # ❌ Missing order_id

# Webhook payload:
POST /webhooks/order_created
{"amount": 100.0}  # ❌ Missing order_id

# Error raised:
╔══════════════════════════════════════════════════════════════╗
║  IDEMPOTENCY KEY MISSING IN PAYLOAD                          ║
╠══════════════════════════════════════════════════════════════╣
║  Saga: OrderSaga                                             ║
║  Trigger Source: order_created                                ║
║                                                              ║
║  Expected field: 'order_id'                                  ║
║  Payload keys: amount                                        ║
║                                                              ║
║  Solutions:                                                  ║
║  1. Include 'order_id' in the webhook payload                ║
║  2. Update the idempotency_key to match available fields    ║
║  3. Remove idempotency_key if not needed (triggers warning) ║
╚══════════════════════════════════════════════════════════════╝
```

## Backward Compatibility

**Breaking Change:** Yes, but **safe by default**

**Who's Affected:**
- Code with `idempotency_key` configured but payloads missing that field
- Previously: Silent fallback to random UUIDs (buggy behavior)
- Now: Clear error with actionable guidance (correct behavior)

**Migration:** Fix the configuration:
1. Add the field to payloads, OR
2. Update `idempotency_key` to match available fields, OR  
3. Remove `idempotency_key` (will trigger warning)

**Not Affected:**
- Triggers without `idempotency_key` (just get warning)
- Triggers with correct payload structure (continue working)

## Design Principles

1. **Agnostic:** No business logic (e.g., "FINANCIAL operations require idempotency")
2. **Educational:** Warnings teach best practices
3. **Fail Fast:** Configuration errors caught immediately
4. **Developer-Friendly:** Clear error messages with solutions
5. **Non-Invasive:** Warnings are informative, not blocking

## Future Enhancements

1. **Idempotency Key Validation:** Check if key values are truly unique (optional)
2. **Automatic Key Detection:** Suggest idempotency keys based on payload structure
3. **Metrics:** Track duplicate prevention rate
4. **Documentation:** Add idempotency best practices guide

### 3. HTTP Error Response (Integration Layer)

When webhooks receive requests missing required idempotency fields, the integration layer returns **400 Bad Request** immediately:

**Files:** `sagaz/integrations/fastapi.py`, `flask.py`, `django.py`

```python
@router.post("/{source}")
async def webhook_handler(source: str, request: Request):
    """Validate idempotency BEFORE accepting request."""
    payload = await request.json()
    
    # Validate idempotency requirements upfront
    try:
        from sagaz.triggers.registry import TriggerRegistry
        triggers = TriggerRegistry.get_triggers(source)
        
        for trigger in triggers:
            if trigger.metadata.idempotency_key:
                key_name = trigger.metadata.idempotency_key
                if isinstance(payload, dict) and key_name not in payload:
                    raise IdempotencyKeyMissingInPayloadError(...)
                    
    except IdempotencyKeyMissingInPayloadError as e:
        # Return 400 Bad Request with clear guidance
        return JSONResponse(
            status_code=400,
            content={
                "status": "rejected",
                "error": "missing_idempotency_key",
                "message": f"Required field '{e.key_name}' is missing from payload",
                "details": {
                    "saga": e.saga_name,
                    "required_field": e.key_name,
                    "payload_keys": e.payload_keys,
                },
                "help": f"Include '{e.key_name}' in your request payload"
            }
        )
    
    # If validation passes, accept and process in background
    # ... normal webhook processing ...
```

**Benefits:**
- ✅ **Immediate feedback:** Client knows instantly what went wrong
- ✅ **No background failures:** Validation happens before accepting the request
- ✅ **Clear error messages:** API consumers understand how to fix the issue
- ✅ **Consistent UX:** All three integrations (FastAPI, Flask, Django) behave identically

**Example Client Experience:**

```bash
# ❌ Missing idempotency key
$ curl -X POST http://localhost:8000/webhooks/order_created \
       -H "Content-Type: application/json" \
       -d '{"amount": 100.0}'

HTTP/1.1 400 Bad Request
{
  "status": "rejected",
  "error": "missing_idempotency_key",
  "message": "Required field 'order_id' is missing from payload",
  "details": {
    "saga": "OrderSaga",
    "required_field": "order_id",
    "payload_keys": ["amount"]
  },
  "help": "Include 'order_id' in your request payload to ensure idempotent processing"
}

# ✅ With idempotency key
$ curl -X POST http://localhost:8000/webhooks/order_created \
       -H "Content-Type: application/json" \
       -d '{"order_id": "ORD-123", "amount": 100.0}'

HTTP/1.1 202 Accepted
{
  "status": "accepted",
  "source": "order_created",
  "message": "Event queued for processing",
  "correlation_id": "abc-123-xyz"
}
```

## Files Changed

- ✅ `sagaz/core/exceptions.py` - Added `IdempotencyKeyMissingInPayloadError`
- ✅ `sagaz/triggers/registry.py` - Warning on registration (already existed)
- ✅ `sagaz/triggers/engine.py` - Error on missing payload field, propagation logic
- ✅ `sagaz/integrations/fastapi.py` - Upfront validation, 400 error response
- ✅ `sagaz/integrations/flask.py` - Upfront validation, 400 error response
- ✅ `sagaz/integrations/django.py` - Upfront validation, 400 error response
- ✅ `tests/unit/test_idempotency_enforcement.py` - Comprehensive test suite
- ✅ `tests/unit/triggers/test_triggers.py` - Updated behavior test

## Summary

This implementation provides **three-layer protection**:
1. **First layer (Startup):** Warn developers about missing idempotency configuration
2. **Second layer (Runtime):** Catch payload mismatches in trigger engine
3. **Third layer (HTTP):** Return 400 Bad Request for webhook clients with clear guidance

Result: **Fail fast at every level with clear guidance** while maintaining library agnosticity and excellent developer experience.
