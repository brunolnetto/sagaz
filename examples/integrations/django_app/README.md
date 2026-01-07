# Django Integration Example

Demonstrates how to integrate Sagaz with Django.

## Features

- **AppConfig Integration**: Initialize Sagaz on Django startup
- **Settings Bridge**: Configure via `settings.SAGAZ`
- **Sync Views**: Run async sagas in sync Django views
- **Correlation IDs**: Request tracing via headers

## Project Structure

```
django_app/
├── manage.py
├── config/
│   ├── __init__.py
│   ├── settings.py     # Django settings + SAGAZ config
│   ├── urls.py
│   └── wsgi.py
└── orders/
    ├── __init__.py
    ├── apps.py          # AppConfig initializes Sagaz
    ├── sagas.py         # Saga definitions
    ├── views.py         # API views
    └── urls.py
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python manage.py runserver 0.0.0.0:8000
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health/` | Health check |
| POST | `/orders/` | Create order |
| GET | `/orders/{id}/diagram/` | Get saga Mermaid diagram |

## Example Request

```bash
curl -X POST http://localhost:8000/orders/ \
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

### AppConfig Initialization

```python
# orders/apps.py
class OrdersConfig(AppConfig):
    name = 'orders'
    
    def ready(self):
        from sagaz import SagaConfig, configure
        from django.conf import settings
        
        sagaz_settings = getattr(settings, 'SAGAZ', {})
        config = SagaConfig(
            metrics=sagaz_settings.get('METRICS', False),
        )
        configure(config)
```

### Settings Configuration

```python
# config/settings.py
SAGAZ = {
    'STORAGE_URL': os.environ.get('SAGAZ_STORAGE_URL', 'memory://'),
    'BROKER_URL': os.environ.get('SAGAZ_BROKER_URL', None),
    'METRICS': True,
    'LOGGING': True,
}
```

### Sync Saga Execution

```python
# orders/views.py
def run_saga_sync(saga, context):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(saga.run(context))
```

## Production Considerations

1. **Use PostgreSQL**: Enable proper storage for production
2. **Celery Integration**: Dispatch long sagas to Celery workers
3. **Transaction Atomicity**: Use `transaction.atomic()` with outbox writes
4. **Gunicorn/uWSGI**: Run with production WSGI server
