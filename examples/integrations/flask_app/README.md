# Flask Integration Example

Demonstrates how to integrate Sagaz with Flask using the extension pattern.

## Features

- **Extension Pattern**: Standard Flask extension initialization
- **Sync Wrapper**: `run_sync()` for blocking saga execution
- **Correlation IDs**: Request tracing via headers
- **Simple Structure**: Minimal boilerplate

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
flask run --reload

# Or directly
python main.py
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/orders` | Create order |
| GET | `/orders/{id}/diagram` | Get saga Mermaid diagram |

## Example Request

```bash
curl -X POST http://localhost:5000/orders \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: my-trace-123" \
  -d '{
    "order_id": "ORD-001",
    "user_id": "USER-123",
    "items": [{"id": "ITEM-1", "name": "Widget", "quantity": 2}],
    "amount": 99.99
  }'
```

## Key Patterns

### Extension Initialization

```python
from flask import Flask
from main import SagazExtension

app = Flask(__name__)
app.config["SAGAZ_STORAGE_URL"] = "postgresql://..."

sagaz = SagazExtension(app)
```

### Sync Saga Execution

```python
@app.route("/orders", methods=["POST"])
def create_order():
    saga = sagaz.create_saga(OrderSaga)
    result = sagaz.run_sync(saga, context)  # Blocking call
    return jsonify({"saga_id": result["saga_id"]})
```

## Limitations

- **Sync Only**: Flask is typically sync; async sagas are wrapped
- **Blocking**: Long sagas block request threads
- **No BackgroundTasks**: Use Celery or similar for async workloads

## Production Considerations

1. **Use Celery**: For long-running sagas, dispatch to Celery workers
2. **Connection Pools**: Enable PostgreSQL/Redis connection pooling
3. **Gunicorn**: Run with multiple workers for concurrency
