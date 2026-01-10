# Flask Integration Example

Demonstrates how to integrate Sagaz with Flask using the **native `sagaz.integrations.flask` module**.

## Features

This example showcases:

- **`SagaFlask(app)`** - Flask extension for lifecycle management
- **`@trigger(source="event_type")`** - Event-driven saga triggering
- **`register_webhook_blueprint()`** - Webhook endpoint registration
- **Automatic correlation ID** - Propagated via request hooks

## Prerequisites

⚠️ **This example requires additional dependencies that are not included with Sagaz by default.**

## Quick Start

```bash
# Install dependencies (Flask)
pip install -r requirements.txt

# Run the app
python main.py

# Or from the CLI (recommended)
sagaz examples run integrations/flask_app
```

## Usage

### Webhook Integration

```python
from sagaz.integrations.flask import SagaFlask
from sagaz.triggers import trigger

# Define saga with trigger
class OrderSaga(Saga):
    @trigger(source="order_created", idempotency_key="order_id")
    def handle_order_created(self, event: dict) -> dict | None:
        return {"order_id": event["order_id"], "amount": event["amount"]}

# Create Flask app
app = Flask(__name__)
sagaz = SagaFlask(app)

# Register webhook blueprint
sagaz.register_webhook_blueprint("/webhooks")
# Creates POST /webhooks/{source} endpoint
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/webhooks/<source>` | POST | Trigger saga via webhook event |
| `/webhooks/status/<saga_id>` | GET | Get saga execution status |
| `/orders/<order_id>/diagram` | GET | Get saga Mermaid diagram |

## Example Requests

### Trigger Saga via Webhook

```bash
curl -X POST http://localhost:5000/webhooks/order_created \
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
curl http://localhost:5000/webhooks/status/<saga_id>
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

## Correlation ID

The `SagaFlask` extension automatically:

1. Extracts `X-Correlation-ID` from incoming request headers
2. Generates a new UUID if not present
3. Includes it in response headers
4. Propagates it throughout saga execution

## Notes

- `run_sync()` blocks the request thread - keep sagas short
- For long-running sagas, consider using Celery
- Flask's sync nature means one saga per request thread
