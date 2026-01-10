# Web Framework Integration Examples

⚠️ **These examples require additional dependencies that are not included with Sagaz by default.**

This directory contains examples demonstrating how to integrate Sagaz with popular Python web frameworks, using **event-driven triggers**.

## Prerequisites

Each example has its own `requirements.txt` file with framework-specific dependencies:

```bash
# FastAPI example
cd fastapi_app && pip install -r requirements.txt

# Flask example
cd flask_app && pip install -r requirements.txt

# Django example
cd django_app && pip install -r requirements.txt
```

## Trigger Pattern

All examples use the same pattern:

```
POST /webhooks/{source}
  → fire_event(source, payload)
    → @trigger(source=...) on matching Saga
      → transformer method(payload) → saga context
        → saga.run(context)
```

**The trigger decorator replaces traditional route handlers** - you define triggers on your sagas instead of writing endpoint code.

## Example: FastAPI

```python
from sagaz import Saga, action
from sagaz.triggers import trigger
from sagaz.integrations.fastapi import create_webhook_router

class OrderSaga(Saga):
    @trigger(
        source="order_created",  # POST /webhooks/order_created
        idempotency_key="order_id",
        max_concurrent=10
    )
    def handle_order(self, event: dict) -> dict | None:
        if not event.get("order_id"):
            return None  # Skip invalid events
        return {"order_id": event["order_id"], ...}  # Saga context

    @action("process")
    async def process_order(self, ctx): ...

# In your app
app.include_router(create_webhook_router("/webhooks"))
```

## Available Examples

| Framework | Directory | Webhook Setup |
|-----------|-----------|---------------|
| **FastAPI** | [`fastapi_app/`](fastapi_app/) | `app.include_router(create_webhook_router())` |
| **Flask** | [`flask_app/`](flask_app/) | `sagaz.register_webhook_blueprint()` |
| **Django** | [`django_app/`](django_app/) | `path('webhooks/<source>/', csrf_exempt(sagaz_webhook_view))` |

## Key Features

| Feature | Description |
|---------|-------------|
| **Fire-and-forget** | Webhooks return 202 Accepted immediately |
| **Idempotency** | Duplicate events (same idempotency_key) are skipped |
| **Concurrency limits** | `max_concurrent` controls parallel saga runs |
| **Background processing** | Sagas run asynchronously after webhook returns |

## Running the Examples

### FastAPI

```bash
cd fastapi_app
pip install fastapi uvicorn sagaz
uvicorn main:app --reload

# Test trigger
curl -X POST http://localhost:8000/webhooks/order_created \
  -H "Content-Type: application/json" \
  -d '{"order_id": "ORD-123", "user_id": "USR-1", "amount": 99.99}'
```

### Flask

```bash
cd flask_app
pip install flask sagaz
python main.py

# Test trigger
curl -X POST http://localhost:5000/webhooks/order_created \
  -H "Content-Type: application/json" \
  -d '{"order_id": "ORD-123", "user_id": "USR-1", "amount": 99.99}'
```

### Django

```bash
cd django_app
pip install django sagaz
python manage.py runserver 0.0.0.0:8000

# Test trigger
curl -X POST http://localhost:8000/webhooks/order_created/ \
  -H "Content-Type: application/json" \
  -d '{"order_id": "ORD-123", "user_id": "USR-1", "amount": 99.99}'
```

## Response Format

All webhook endpoints return:

```json
{
  "status": "accepted",
  "source": "order_created",
  "message": "Event queued for processing"
}
```

Status code: `202 Accepted` (the saga runs in background)
