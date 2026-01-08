# FastAPI Integration Example

Demonstrates how to integrate Sagaz with FastAPI using the **native `sagaz.integrations.fastapi` module**.

## Features

This example showcases:

- **`create_lifespan(config)`** - Lifespan context manager for resource initialization/cleanup
- **`saga_factory(SagaClass)`** - Dependency injection factory for saga instances
- **`run_saga_background()`** - Fire-and-forget background saga execution
- **`SagaContextMiddleware`** - Automatic correlation ID propagation
- **`get_config()`** - Dependency to access current SagaConfig

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
uvicorn main:app --reload
```

## Usage

### Native Integration Module

```python
from sagaz.integrations.fastapi import (
    create_lifespan,
    saga_factory,
    run_saga_background,
    SagaContextMiddleware,
)

# Create FastAPI app with Sagaz lifespan
app = FastAPI(lifespan=create_lifespan(config))

# Add correlation ID middleware
app.add_middleware(SagaContextMiddleware)

# Use dependency injection in routes
@app.post("/orders")
async def create_order(saga: OrderSaga = Depends(saga_factory(OrderSaga))):
    result = await saga.run({"order_id": "123"})
    return result
```

### Background Saga Execution

```python
@app.post("/orders/async")
async def create_order_async(
    background_tasks: BackgroundTasks,
    saga: OrderSaga = Depends(saga_factory(OrderSaga)),
):
    saga_id = await run_saga_background(
        background_tasks,
        saga,
        {"order_id": "123"},
        on_success=lambda r: print("Completed!"),
        on_failure=lambda e: print(f"Failed: {e}"),
    )
    return {"saga_id": saga_id, "status": "accepted"}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/orders` | POST | Create order synchronously |
| `/orders/async` | POST | Create order in background |
| `/orders/{order_id}/diagram` | GET | Get saga Mermaid diagram |

## API Docs

When running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
