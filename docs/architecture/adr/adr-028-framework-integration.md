# ADR-028: Web Framework Integration (FastAPI, Django, Flask)

**Date**: 2026-01-07  
**Status**: Proposed  
**Target Version**: v1.3.0  
**Priority**: High  
**Complexity**: Medium  
**Effort Estimate**: 4-5 weeks  
**Prerequisites**: ADR-016 (Unified Storage)  
**Enables**: Rapid adoption in web applications, production-grade resource management  

---

## Context and Problem Statement

Most saga executions are triggered from web applications:
- "User clicks Buy" → `OrderSaga`
- "Webhook received" → `ProvisioningSaga`
- "Admin triggers refund" → `RefundSaga`

While `sagaz` is framework-agnostic, integrating it correctly into web frameworks requires careful handling of:

| Concern | What Goes Wrong |
|---------|-----------------|
| **Connection lifecycle** | Forgetting to initialize storage on startup → runtime errors |
| **Resource cleanup** | Not closing pools on shutdown → connection leaks |
| **Dependency injection** | Manual instantiation in every endpoint → code duplication |
| **Request context** | No correlation ID propagation → untraceable logs |
| **Async boundaries** | Blocking sync code in async endpoints → thread exhaustion |
| **Transaction atomicity** | Outbox write outside DB transaction → at-most-once |
| **Long-running sagas** | Blocking request thread → timeouts, poor UX |

Without first-party integration, users implement these inconsistently or incorrectly.

---

## Decision

Provide **first-party integration modules** for the three most popular Python web frameworks:

1. **FastAPI/Starlette** (`sagaz.integrations.fastapi`)
2. **Django** (`sagaz.integrations.django`)
3. **Flask** (`sagaz.integrations.flask`) — lightweight, sync-only

All integrations are **optional dependencies** and follow the same principles:
- Zero-config sensible defaults
- Explicit over implicit
- Framework-native patterns (don't fight the framework)

---

## Detailed Design

### 1. FastAPI Integration (`sagaz.integrations.fastapi`)

#### Lifespan Management

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sagaz import SagaConfig
from sagaz.integrations.fastapi import create_lifespan

config = SagaConfig.from_env()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize storage pools, brokers, etc.
    await config.initialize()
    yield
    # Cleanup
    await config.close()

app = FastAPI(lifespan=create_lifespan(config))
# Or just: app = FastAPI(lifespan=create_lifespan())  # Uses global config
```

#### Dependency Injection

```python
from fastapi import Depends
from sagaz.integrations.fastapi import get_config, SagaFactory

# Get the global config
@app.post("/orders")
async def create_order(config: SagaConfig = Depends(get_config)):
    saga = OrderSaga(config=config)
    result = await saga.run({"order_id": "123"})
    return {"saga_id": result.saga_id, "status": result.status.value}

# Or use the factory for cleaner injection
saga_factory = SagaFactory()

@app.post("/orders")
async def create_order(saga: OrderSaga = Depends(saga_factory(OrderSaga))):
    result = await saga.run({"order_id": "123"})
    return {"saga_id": result.saga_id}
```

#### Background Execution (Fire-and-Forget)

For long-running sagas that shouldn't block the HTTP response:

```python
from fastapi import BackgroundTasks
from sagaz.integrations.fastapi import run_saga_background

@app.post("/orders")
async def create_order(
    background_tasks: BackgroundTasks,
    saga: OrderSaga = Depends(saga_factory(OrderSaga))
):
    # Returns immediately, saga runs in background
    saga_id = await run_saga_background(
        background_tasks, 
        saga, 
        context={"order_id": "123"}
    )
    return {"saga_id": saga_id, "status": "accepted"}
```

**Caveat**: Background tasks run in the same process. For true reliability, use the Outbox Worker pattern or a task queue (Celery, ARQ).

#### Request Context Middleware

Optional middleware for correlation ID propagation:

```python
from sagaz.integrations.fastapi import SagaContextMiddleware

app.add_middleware(
    SagaContextMiddleware,
    header_name="X-Correlation-ID",  # Or "X-Request-ID"
    propagate_to_context=True,        # Add to saga context automatically
)
```

### 2. Django Integration (`sagaz.integrations.django`)

#### App Configuration

```python
# settings.py
INSTALLED_APPS = [
    ...
    'sagaz.integrations.django',
]

SAGAZ = {
    'STORAGE_URL': os.environ.get('SAGAZ_STORAGE_URL', 'memory://'),
    'BROKER_URL': os.environ.get('SAGAZ_BROKER_URL', None),
    'METRICS': True,
    'LOGGING': True,
}
```

```python
# sagaz.integrations.django/apps.py
class SagazConfig(AppConfig):
    name = 'sagaz.integrations.django'
    
    def ready(self):
        from sagaz import configure, SagaConfig
        from django.conf import settings
        
        sagaz_settings = getattr(settings, 'SAGAZ', {})
        config = SagaConfig(
            storage=create_storage(sagaz_settings.get('STORAGE_URL', 'memory://')),
            # ... other settings
        )
        configure(config)
```

#### Management Commands

```bash
# List all discovered sagas (if using project structure)
python manage.py sagaz_list

# Run the outbox worker
python manage.py sagaz_worker --concurrency 4

# Check saga health
python manage.py sagaz_check
```

#### Transaction Integration (Critical)

The hardest problem: ensuring saga start + outbox event are atomic with Django ORM writes.

```python
from django.db import transaction
from sagaz.integrations.django import atomic_saga_start, saga_context

# Approach 1: Explicit
with transaction.atomic():
    order = Order.objects.create(...)
    
    # This writes to outbox table in SAME transaction
    saga_id = atomic_saga_start(
        OrderSaga,
        context={"order_id": order.id},
        connection=transaction.get_connection(),  # Reuse Django's connection
    )

# Approach 2: Decorator
@transaction.atomic
@saga_context  # Automatically captures the transaction
def create_order(request):
    order = Order.objects.create(...)
    saga = OrderSaga()
    saga.run_deferred({"order_id": order.id})  # Publishes to outbox on commit
    return JsonResponse({"order_id": order.id})
```

**Important**: This requires the saga storage and Django ORM to use the **same database connection**. For PostgreSQL, we provide `DjangoPostgreSQLSagaStorage` that wraps Django's connection.

#### Async Django Support

For Django 4.1+ async views:

```python
from sagaz.integrations.django import async_saga_factory

@api_view(['POST'])
async def create_order(request):
    saga = await async_saga_factory(OrderSaga)
    result = await saga.run({"order_id": request.data['order_id']})
    return Response({"saga_id": result.saga_id})
```

### 3. Flask Integration (`sagaz.integrations.flask`)

Lightweight, sync-only integration:

```python
from flask import Flask
from sagaz.integrations.flask import SagazExtension

app = Flask(__name__)
sagaz = SagazExtension(app, storage_url="postgresql://...")

@app.route("/orders", methods=["POST"])
def create_order():
    saga = sagaz.create_saga(OrderSaga)
    # Note: Flask is sync, so we use sync wrapper
    result = sagaz.run_sync(saga, {"order_id": "123"})
    return {"saga_id": result.saga_id}
```

---

## API Summary

| Framework | Initialization | DI | Background | Transaction |
|-----------|---------------|-----|------------|-------------|
| FastAPI | `create_lifespan()` | `SagaFactory` | `run_saga_background()` | N/A (use storage directly) |
| Django | AppConfig `ready()` | N/A | Celery integration | `atomic_saga_start()` |
| Flask | `SagazExtension(app)` | `sagaz.create_saga()` | No (use Celery) | N/A |

---

## Consequences

### Positive
- **5-minute integration**: From zero to working saga in any framework.
- **Correct by default**: Resource lifecycle handled correctly.
- **Framework-native**: Uses `Depends()`, AppConfig, Extensions as users expect.

### Negative
- **Framework version coupling**: Must track FastAPI/Django/Flask releases.
- **Increased surface area**: More code to maintain and test.
- **Optional dependency complexity**: `pip install sagaz[fastapi]` vs `sagaz[django]`.

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| FastAPI DI changes break integration | Low | Medium | Pin compatible versions, integration tests |
| Django async support is immature | Medium | Low | Provide sync fallback, document limitations |
| Users expect "magic" that we don't provide | Medium | Medium | Clear docs on what IS and ISN'T handled |

---

## Alternatives Considered

### 1. Documentation Only
- Provide "How to integrate with FastAPI" docs.
- **Pros**: Zero code maintenance.
- **Cons**: Copy-paste errors, divergent implementations.
- **Decision**: Rejected—poor DX.

### 2. Generic ASGI/WSGI Middleware
- Framework-agnostic middleware.
- **Pros**: One implementation.
- **Cons**: Can't use framework-specific features (DI, lifecycle hooks).
- **Decision**: Rejected—lowest common denominator is too limiting.

### 3. Only FastAPI
- FastAPI is the future; skip Django/Flask.
- **Pros**: Focused effort.
- **Cons**: Alienates large existing Django user base.
- **Decision**: Rejected—Django is still dominant in enterprises.

---

## Implementation Roadmap

### Phase 1: FastAPI (v1.3.0) — 2 weeks
- `create_lifespan()`, `get_config()`, `SagaFactory`
- `run_saga_background()`
- Integration tests with `TestClient`
- Documentation

### Phase 2: Django (v1.3.0) — 2 weeks
- AppConfig integration
- Management commands (`sagaz_worker`, `sagaz_list`)
- `atomic_saga_start()` for transaction integration
- Tests with Django test client

### Phase 3: Flask & Polish (v1.3.1) — 1 week
- `SagazExtension`
- Example applications for all three frameworks
- Cross-framework documentation page

---

## Example Project Structure

**Status**: ✅ Implemented

See [`examples/integrations/`](../../../examples/integrations/) for working examples:

```
examples/integrations/
├── README.md                   # Overview and comparison
├── fastapi_app/
│   ├── main.py                 # Full FastAPI integration
│   ├── requirements.txt
│   └── README.md
├── django_app/
│   ├── manage.py
│   ├── config/
│   │   ├── settings.py         # SAGAZ config
│   │   └── urls.py
│   ├── orders/
│   │   ├── apps.py             # AppConfig
│   │   ├── sagas.py            # OrderSaga
│   │   ├── views.py            # API views
│   │   └── urls.py
│   ├── requirements.txt
│   └── README.md
└── flask_app/
    ├── main.py                 # Flask extension pattern
    ├── requirements.txt
    └── README.md
```

---

## Open Questions

1. **Celery integration**: Should we provide `SagaCeleryTask` for true background execution?
2. **GraphQL**: Any interest in Strawberry/Ariadne integration?
3. **Request scoped storage**: Should sagas automatically inherit request transaction in Django?
