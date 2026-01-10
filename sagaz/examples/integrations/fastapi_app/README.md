# FastAPI Integration Example

Demonstrates how to integrate Sagaz with FastAPI using the **native `sagaz.integrations.fastapi` module**.

## Features

This example showcases:

- **`sagaz_startup()` / `sagaz_shutdown()`** - Lifespan hooks for resource initialization/cleanup
- **`@trigger(source="event_type")`** - Event-driven saga triggering
- **`create_webhook_router()`** - Webhook endpoint registration
- **Automatic correlation ID** - Propagated throughout the request

## Prerequisites

⚠️ **This example requires additional dependencies that are not included with Sagaz by default.**

## Quick Start

```bash
# Install dependencies (FastAPI, Uvicorn)
pip install -r requirements.txt

# Run the app
uvicorn main:app --reload

# Or from the CLI (recommended)
sagaz examples run integrations/fastapi_app
```

## Usage

### Webhook Integration

```python
from sagaz.integrations.fastapi import (
    create_webhook_router,
    sagaz_startup,
    sagaz_shutdown,
)
from sagaz.triggers import trigger

# Define saga with trigger
class OrderSaga(Saga):
    @trigger(source="order_created", idempotency_key="order_id")
    def handle_order_created(self, event: dict) -> dict | None:
        return {"order_id": event["order_id"], "amount": event["amount"]}

# Create FastAPI app with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    await sagaz_startup()
    yield
    await sagaz_shutdown()

app = FastAPI(lifespan=lifespan)

# Register webhook router
app.include_router(create_webhook_router("/webhooks"))
# Creates POST /webhooks/{source} endpoint
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/webhooks/<source>` | POST | Trigger saga via webhook event |
| `/webhooks/status/<saga_id>` | GET | Get saga execution status |
| `/orders/{order_id}/diagram` | GET | Get saga Mermaid diagram |

## Example Requests

### Trigger Saga via Webhook

```bash
curl -X POST http://localhost:8000/webhooks/order_created \
     -H "Content-Type: application/json" \
     -d '{"order_id": "ORD-001", "amount": 99.99, "user_id": "user-123"}'
```

Response:
```json
{
  "message": "Event queued for processing",
  "source": "order_created",
  "status": "accepted"
}
```

### Check Saga Status

```bash
curl http://localhost:8000/webhooks/status/<saga_id>
```

Response:
```json
{
  "saga_id": "abc123",
  "state": "COMPLETED",
  "context": {"order_id": "ORD-001", ...},
  "completed_steps": ["reserve_inventory", "charge_payment", "ship_order"],
  "failed_step": null,
  "error": null
}
```

## API Docs

When running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
