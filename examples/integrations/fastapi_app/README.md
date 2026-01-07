# FastAPI Integration Example

Demonstrates how to integrate Sagaz with FastAPI for building transactional APIs.

## Features

- **Lifespan Management**: Automatic storage initialization/cleanup
- **Dependency Injection**: Clean `Depends()` pattern for saga instances
- **Background Execution**: Fire-and-forget saga execution via `BackgroundTasks`
- **Correlation IDs**: Request tracing with middleware

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload

# Open API docs
open http://localhost:8000/docs
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/orders` | Create order (sync) |
| POST | `/orders/async` | Create order (background) |
| GET | `/orders/{id}/diagram` | Get saga Mermaid diagram |

## Example Request

```bash
curl -X POST http://localhost:8000/orders \
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

### Saga Dependency Injection

```python
from fastapi import Depends

def create_saga(saga_class: type):
    def factory(config: SagaConfig = Depends(get_saga_config)):
        return saga_class(config=config)
    return factory

@app.post("/orders")
async def create_order(saga: OrderSaga = Depends(create_saga(OrderSaga))):
    result = await saga.run(context)
    return {"saga_id": result["saga_id"]}
```

### Background Execution

```python
@app.post("/orders/async")
async def create_order_async(
    background_tasks: BackgroundTasks,
    saga: OrderSaga = Depends(create_saga(OrderSaga)),
):
    saga_id = await run_saga_in_background(background_tasks, saga, context)
    return {"saga_id": saga_id, "status": "accepted"}
```

## Production Considerations

1. **Use StorageManager**: Enable PostgreSQL/Redis storage for persistence
2. **Outbox Worker**: For reliability, use the outbox pattern instead of BackgroundTasks
3. **Timeouts**: Configure appropriate timeouts for saga steps
4. **Monitoring**: Enable Prometheus metrics and OpenTelemetry tracing
