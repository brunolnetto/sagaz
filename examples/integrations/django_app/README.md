# Django Integration Example

Demonstrates how to integrate Sagaz with Django using the **native `sagaz.integrations.django` module**.

## Features

This example showcases:

- **`SagaDjangoMiddleware`** - Automatic correlation ID propagation
- **`run_saga_sync(saga, context)`** - Synchronous wrapper for async sagas
- **`create_saga(SagaClass)`** - Create saga with correlation ID injected
- **`get_sagaz_config()`** - Read config from Django settings

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python manage.py runserver
```

## Usage

### Settings Configuration

```python
# settings.py

INSTALLED_APPS = [
    ...
    'orders',  # Your app using sagas
]

MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
    'sagaz.integrations.django.SagaDjangoMiddleware',  # <-- Native middleware!
]

# Sagaz configuration
SAGAZ = {
    'STORAGE_BACKEND': 'postgresql',
    'STORAGE_DSN': 'postgresql://user:pass@localhost/sagaz',
    'METRICS': True,
    'LOGGING': True,
}
```

### Views

```python
# views.py
from sagaz.integrations.django import run_saga_sync, create_saga
from sagaz.integrations._base import SagaContextManager

def create_order(request):
    # Correlation ID is set by middleware
    correlation_id = SagaContextManager.get("correlation_id")
    
    # Create saga with correlation ID injected
    saga = create_saga(OrderSaga)
    
    # Run async saga synchronously
    result = run_saga_sync(saga, {
        "order_id": "123",
        "correlation_id": correlation_id,
    })
    
    return JsonResponse(result)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health/` | GET | Health check |
| `/orders/` | POST | Create order |
| `/orders/<order_id>/` | GET | Get saga diagram |

## Correlation ID

The `SagaDjangoMiddleware` automatically:

1. Extracts `X-Correlation-ID` from incoming request headers
2. Generates a new UUID if not present
3. Stores it in `SagaContextManager` and on `request.saga_correlation_id`
4. Includes it in response headers
5. Clears context after each request

## Project Structure

```
django_app/
├── config/
│   ├── __init__.py
│   ├── settings.py      # Django settings with SAGAZ config
│   ├── urls.py          # URL routing
│   └── wsgi.py
├── orders/
│   ├── __init__.py
│   ├── apps.py          # App configuration
│   ├── sagas.py         # OrderSaga definition
│   ├── urls.py          # Order URLs
│   └── views.py         # Views using native module
├── manage.py
└── requirements.txt
```

## Notes

- Django is synchronous by default, so `run_saga_sync()` is required
- The middleware clears context after each request for isolation
- For async Django (ASGI), consider using `async def` views with `await saga.run()`
