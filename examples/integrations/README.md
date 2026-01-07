# Web Framework Integration Examples

This directory contains example applications demonstrating how to integrate Sagaz with popular Python web frameworks.

## Available Examples

| Framework | Directory | Description |
|-----------|-----------|-------------|
| **FastAPI** | [`fastapi_app/`](fastapi_app/) | Async-first integration with dependency injection |
| **Django** | [`django_app/`](django_app/) | AppConfig integration with sync views |
| **Flask** | [`flask_app/`](flask_app/) | Extension pattern with sync wrapper |

## Quick Comparison

| Feature | FastAPI | Django | Flask |
|---------|---------|--------|-------|
| Async Native | ✅ Yes | ⚠️ Partial | ❌ No |
| DI Pattern | `Depends()` | - | Extension |
| Background Tasks | `BackgroundTasks` | Celery | Celery |
| Lifespan | `@asynccontextmanager` | `AppConfig.ready()` | `init_app()` |
| Best For | APIs, Microservices | Full-stack, Enterprise | Simple APIs |

## Architecture Pattern

All examples follow the same core pattern:

```
┌──────────────────────────────────────────┐
│              Web Framework               │
│  (FastAPI / Django / Flask)              │
└──────────────────────────────────────────┘
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
┌─────────────────┐  ┌─────────────────────┐
│  Initialization │  │   Request Handler   │
│  (Lifespan/App) │  │  (Route/View)       │
└─────────────────┘  └─────────────────────┘
         │                     │
         ▼                     ▼
┌──────────────────────────────────────────┐
│           Sagaz SagaConfig               │
│  (Storage, Broker, Metrics, Logging)     │
└──────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────┐
│            Saga Execution                │
│  (OrderSaga, PaymentSaga, etc.)          │
└──────────────────────────────────────────┘
```

## Running the Examples

### FastAPI

```bash
cd fastapi_app
pip install -r requirements.txt
uvicorn main:app --reload
# Visit http://localhost:8000/docs
```

### Django

```bash
cd django_app
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8000
# Visit http://localhost:8000/health/
```

### Flask

```bash
cd flask_app
pip install -r requirements.txt
python main.py
# Visit http://localhost:5000/health
```

## Common API Endpoints

All examples expose the same API:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/orders` | Create an order (runs saga) |
| `GET` | `/orders/{id}/diagram` | Get Mermaid diagram |

### Test Request

```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: test-123" \
  -d '{
    "order_id": "ORD-001",
    "user_id": "USER-123",
    "items": [{"id": "ITEM-1", "name": "Widget", "quantity": 2}],
    "amount": 99.99
  }'
```

## Production Considerations

### Storage Configuration

```python
# Use PostgreSQL for production
SAGAZ_STORAGE_URL=postgresql://user:pass@host:5432/sagaz

# Or Redis
SAGAZ_STORAGE_URL=redis://localhost:6379/0
```

### Reliability

- **Short Sagas**: Execute inline in request handlers
- **Long Sagas**: Use Outbox Pattern + Worker (recommended)
- **Background Tasks**: Only for best-effort scenarios

### Monitoring

```python
config = SagaConfig(
    storage=...,
    metrics=True,     # Prometheus /metrics
    tracing=True,     # OpenTelemetry traces
    logging=True,     # Structured logs
)
```

## Related Documentation

- [ADR-028: Framework Integration](../../docs/architecture/adr/adr-028-framework-integration.md)
- [Implementation Plan](../../docs/architecture/implementation-plans/framework-integration-implementation-plan.md)
- [Sagaz Configuration Guide](../../docs/configuration.md)
