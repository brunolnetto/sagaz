# Flask Integration Example

Demonstrates how to integrate Sagaz with Flask using the **native `sagaz.integrations.flask` module**.

## Features

This example showcases:

- **`SagaFlask(app, config)`** - Flask extension for lifecycle management
- **`run_saga_sync(saga, context)`** - Synchronous wrapper for async sagas
- **Automatic correlation ID** - Propagated via request hooks
- **`create_saga(SagaClass)`** - Create saga with correlation ID injected

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
flask run --reload

# Or directly
python main.py
```

## Usage

### Native Integration Module

```python
from sagaz.integrations.flask import SagaFlask, run_saga_sync

# Create Flask app with Sagaz extension
app = Flask(__name__)
config = SagaConfig(metrics=True, logging=True)
sagaz = SagaFlask(app, config)  # <-- Native extension!

@app.route("/orders", methods=["POST"])
def create_order():
    saga = sagaz.create_saga(OrderSaga)
    result = sagaz.run_sync(saga, {"order_id": "123"})
    return jsonify(result)
```

### Standalone Function

```python
from sagaz.integrations.flask import run_saga_sync

# Works without the extension
saga = OrderSaga()
result = run_saga_sync(saga, {"order_id": "123"})
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/orders` | POST | Create order using extension |
| `/orders/standalone` | POST | Create order using standalone function |
| `/orders/<order_id>/diagram` | GET | Get saga Mermaid diagram |

## Correlation ID

The `SagaFlask` extension automatically:

1. Extracts `X-Correlation-ID` from incoming request headers
2. Generates a new UUID if not present
3. Stores it in `flask.g.saga_correlation_id`
4. Includes it in response headers
5. Injects it into sagas created via `create_saga()`

## Notes

- `run_sync()` blocks the request thread - keep sagas short
- For long-running sagas, consider using Celery
- Flask's sync nature means one saga per request thread
