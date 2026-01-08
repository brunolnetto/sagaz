# Web Framework Integration - Implementation Plan

**Status:** ✅ Complete (Including Unified Logger)
**Created:** 2026-01-07  
**Last Updated:** 2026-01-07  
**Target Version:** v1.3.0  
**ADR:** [ADR-028: Web Framework Integration](../adr/adr-028-framework-integration.md)  
**Estimated Effort:** 4-5 weeks (Phase 1-3 complete, Phase 4 examples done)  

---

## Executive Summary

Provide first-party integrations for FastAPI, Django, and Flask that handle resource lifecycle, dependency injection, and common patterns like background saga execution.

---

## Goals

| Goal | Success Criteria |
|------|------------------|
| Zero-boilerplate FastAPI integration | Working app in < 20 lines of code |
| Django app config integration | Works with standard `INSTALLED_APPS` pattern |
| Correct resource lifecycle | No connection leaks in stress tests |
| Transaction atomicity (Django) | Outbox writes in same DB transaction |
| Test coverage | All integrations have framework-specific tests |

---

## Non-Goals

- **Celery/ARQ/Dramatiq integration**: Separate ADR/feature
- **GraphQL frameworks**: Future consideration
- **Admin UI**: Not in scope
- **Async Django ORM**: Document limitations, don't work around them

---

## Technical Design

### Package Structure

```
sagaz/
└── integrations/
    ├── __init__.py
    ├── _base.py              # Shared utilities
    ├── fastapi.py            # FastAPI/Starlette integration
    ├── django/
    │   ├── __init__.py
    │   ├── apps.py           # Django AppConfig
    │   ├── conf.py           # Settings bridge
    │   ├── storage.py        # Django ORM-aware storage
    │   └── management/
    │       └── commands/
    │           ├── sagaz_worker.py
    │           └── sagaz_list.py
    └── flask.py              # Flask extension
```

### Shared Utilities (`_base.py`)

```python
# sagaz/integrations/_base.py

class SagaContextManager:
    """
    Thread-safe context for request-scoped saga execution.
    
    Holds correlation ID, request metadata, etc.
    """
    _context: contextvars.ContextVar[dict] = contextvars.ContextVar('saga_ctx', default={})
    
    @classmethod
    def get(cls, key: str, default=None):
        return cls._context.get().get(key, default)
    
    @classmethod
    def set(cls, key: str, value):
        ctx = cls._context.get().copy()
        ctx[key] = value
        cls._context.set(ctx)
    
    @classmethod
    @contextmanager
    def scope(cls, **initial):
        """Create a new context scope (e.g., per-request)."""
        token = cls._context.set(initial)
        try:
            yield
        finally:
            cls._context.reset(token)


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for tracing."""
    return str(uuid.uuid4())
```

---

## Implementation Phases

### Phase 1: FastAPI Integration (Week 1-2)

#### Tasks

| Task | Effort | Description |
|------|--------|-------------|
| 1.1 `create_lifespan()` | 1d | Factory for FastAPI lifespan context manager |
| 1.2 `get_config()` dependency | 0.5d | `Depends()` helper for config injection |
| 1.3 `SagaFactory` dependency | 1d | Generic factory: `Depends(saga_factory(OrderSaga))` |
| 1.4 `run_saga_background()` | 1d | Wrapper for `BackgroundTasks` integration |
| 1.5 `SagaContextMiddleware` | 1d | Correlation ID propagation |
| 1.6 Unit tests | 2d | Test each component in isolation |
| 1.7 Integration tests | 2d | `TestClient` tests with real requests |
| 1.8 Documentation | 1d | Quickstart guide, API reference |

#### Code Samples

```python
# sagaz/integrations/fastapi.py
from contextlib import asynccontextmanager
from typing import TypeVar, Type, Callable
from fastapi import Depends, Request, BackgroundTasks
from starlette.middleware.base import BaseHTTPMiddleware

from sagaz import SagaConfig, get_config as get_global_config
from sagaz.decorators import Saga

T = TypeVar('T', bound=Saga)

_config: SagaConfig | None = None

def create_lifespan(config: SagaConfig | None = None):
    """
    Create a FastAPI lifespan context manager.
    
    Usage:
        config = SagaConfig.from_env()
        app = FastAPI(lifespan=create_lifespan(config))
    """
    @asynccontextmanager
    async def lifespan(app):
        nonlocal _config
        cfg = config or get_global_config()
        _config = cfg
        
        # Initialize storage manager if present
        if cfg.storage_manager:
            await cfg.storage_manager.initialize()
        
        yield
        
        # Cleanup
        if cfg.storage_manager:
            await cfg.storage_manager.close()
    
    return lifespan


def get_config() -> SagaConfig:
    """Dependency that returns the current SagaConfig."""
    if _config is None:
        raise RuntimeError(
            "Sagaz not initialized. Did you use create_lifespan()?"
        )
    return _config


class SagaFactory:
    """
    Dependency factory for injecting saga instances.
    
    Usage:
        saga_factory = SagaFactory()
        
        @app.post("/orders")
        async def create_order(saga: OrderSaga = Depends(saga_factory(OrderSaga))):
            result = await saga.run({"order_id": "123"})
    """
    def __call__(self, saga_class: Type[T]) -> Callable[[], T]:
        def factory(config: SagaConfig = Depends(get_config)) -> T:
            return saga_class(config=config)
        return factory


async def run_saga_background(
    background_tasks: BackgroundTasks,
    saga: Saga,
    context: dict,
) -> str:
    """
    Schedule saga execution as a background task.
    
    Returns the saga_id immediately. Saga runs after response is sent.
    
    WARNING: Background tasks run in the same process. For true reliability
    with crashes, use the Outbox Worker pattern instead.
    """
    import uuid
    saga_id = str(uuid.uuid4())
    
    async def run_wrapper():
        try:
            await saga.run({**context, "_saga_id": saga_id})
        except Exception as e:
            # Log but don't raise (already returned to client)
            import logging
            logging.error(f"Background saga {saga_id} failed: {e}")
    
    background_tasks.add_task(run_wrapper)
    return saga_id


class SagaContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware for correlation ID propagation.
    
    Reads correlation ID from request header (or generates one),
    makes it available via SagaContextManager.
    """
    def __init__(self, app, header_name: str = "X-Correlation-ID"):
        super().__init__(app)
        self.header_name = header_name
    
    async def dispatch(self, request: Request, call_next):
        from sagaz.integrations._base import SagaContextManager, generate_correlation_id
        
        correlation_id = request.headers.get(
            self.header_name, 
            generate_correlation_id()
        )
        
        with SagaContextManager.scope(correlation_id=correlation_id):
            response = await call_next(request)
            response.headers[self.header_name] = correlation_id
            return response
```

#### Test Plan

```python
# tests/integrations/test_fastapi.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sagaz.integrations.fastapi import create_lifespan, SagaFactory, get_config

@pytest.fixture
def app():
    from sagaz import SagaConfig
    config = SagaConfig()
    
    app = FastAPI(lifespan=create_lifespan(config))
    
    @app.get("/health")
    def health():
        return {"status": "ok"}
    
    return app

@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client

def test_lifespan_initializes_config(client):
    """Config is available after startup."""
    response = client.get("/health")
    assert response.status_code == 200

def test_correlation_id_propagation(app):
    """Middleware propagates correlation ID."""
    from sagaz.integrations.fastapi import SagaContextMiddleware
    app.add_middleware(SagaContextMiddleware)
    
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Correlation-ID": "test-123"})
        assert response.headers["X-Correlation-ID"] == "test-123"
```

---

### Phase 2: Django Integration (Week 2-3)

#### Tasks

| Task | Effort | Description |
|------|--------|-------------|
| 2.1 `apps.py` AppConfig | 1d | Initialize Sagaz on Django startup |
| 2.2 `conf.py` settings bridge | 0.5d | Read from `settings.SAGAZ` |
| 2.3 `sagaz_worker` command | 1d | Management command for worker |
| 2.4 `sagaz_list` command | 0.5d | List configured sagas |
| 2.5 `DjangoPostgreSQLSagaStorage` | 2d | Uses Django's DB connection |
| 2.6 `atomic_saga_start()` | 2d | Transaction-aware outbox write |
| 2.7 Unit tests | 2d | Django test case setup |
| 2.8 Integration tests | 1d | With test database |

#### Transaction Atomicity Detail

The critical feature for Django is ensuring outbox writes happen in the same transaction as ORM writes:

```python
# sagaz/integrations/django/storage.py
from django.db import connection

class DjangoPostgreSQLSagaStorage:
    """
    PostgreSQL saga storage that uses Django's database connection.
    
    This ensures outbox writes are atomic with ORM operations when
    used within @transaction.atomic.
    """
    def __init__(self, alias: str = 'default'):
        self.alias = alias
    
    def _get_connection(self):
        """Get the raw psycopg connection from Django."""
        return connection.connection
    
    # ... implement SagaStorage interface using Django's connection


# sagaz/integrations/django/transactions.py
from django.db import transaction

def atomic_saga_start(
    saga_class: type,
    context: dict,
    *,
    using: str = 'default',
) -> str:
    """
    Start a saga atomically within the current transaction.
    
    MUST be called inside @transaction.atomic. Writes saga start
    and initial outbox event to the database.
    
    Usage:
        with transaction.atomic():
            order = Order.objects.create(...)
            saga_id = atomic_saga_start(OrderSaga, {"order_id": order.id})
    """
    if not transaction.get_connection(using).in_atomic_block:
        raise RuntimeError(
            "atomic_saga_start must be called inside @transaction.atomic"
        )
    
    # ... implementation
```

---

### Phase 3: Flask Integration (Week 4)

#### Tasks

| Task | Effort | Description |
|------|--------|-------------|
| 3.1 `SagazExtension` | 1d | Flask extension pattern |
| 3.2 `run_sync()` helper | 0.5d | Sync wrapper for async saga |
| 3.3 Request context integration | 0.5d | `g.sagaz_context` |
| 3.4 Tests | 1d | Flask test client |

#### Code Sample

```python
# sagaz/integrations/flask.py
from flask import Flask, g
from sagaz import SagaConfig, Saga
import asyncio

class SagazExtension:
    """
    Flask extension for Sagaz.
    
    Usage:
        app = Flask(__name__)
        sagaz = SagazExtension(app, storage_url="postgresql://...")
    """
    def __init__(self, app: Flask | None = None, **config_kwargs):
        self.config: SagaConfig | None = None
        self._config_kwargs = config_kwargs
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app: Flask):
        self.config = SagaConfig(**self._config_kwargs)
        
        @app.before_first_request
        def initialize():
            # Note: Flask 2.3+ deprecated before_first_request
            # Use alternative initialization for newer Flask
            asyncio.run(self.config.storage_manager.initialize())
        
        @app.teardown_appcontext
        def cleanup(exception):
            # Cleanup per-request resources if any
            pass
        
        app.extensions['sagaz'] = self
    
    def create_saga(self, saga_class: type) -> Saga:
        """Create a saga instance with current config."""
        return saga_class(config=self.config)
    
    def run_sync(self, saga: Saga, context: dict):
        """
        Run a saga synchronously (for sync Flask routes).
        
        WARNING: This blocks the request thread. Fine for short sagas,
        but consider Celery for long-running work.
        """
        return asyncio.run(saga.run(context))
```

---

### Phase 4: Examples & Documentation (Week 5) — ✅ EXAMPLES COMPLETED

#### Tasks

| Task | Effort | Status | Description |
|------|--------|--------|-------------|
| 4.1 FastAPI example app | 1d | ✅ Done | [`examples/integrations/fastapi_app/`](../../../examples/integrations/fastapi_app/) |
| 4.2 Django example app | 1d | ✅ Done | [`examples/integrations/django_app/`](../../../examples/integrations/django_app/) |
| 4.3 Flask example app | 0.5d | ✅ Done | [`examples/integrations/flask_app/`](../../../examples/integrations/flask_app/) |
| 4.4 Integration docs page | 1d | ✅ Done | [`examples/integrations/README.md`](../../../examples/integrations/README.md) |
| 4.5 Migration guide | 0.5d | Pending | "Migrating from manual setup" |
| 4.6 Final review | 1d | Pending | Cross-framework consistency check |

---

## Test Strategy

### Per-Framework Tests

| Framework | Test Type | Tools |
|-----------|-----------|-------|
| FastAPI | Unit + Integration | `pytest`, `TestClient` |
| Django | Unit + Integration | `pytest-django`, `TransactionTestCase` |
| Flask | Unit + Integration | `pytest`, `test_client` |

### Stress Tests

- 100 concurrent requests, verify no connection leaks
- Startup/shutdown cycle 10x, verify clean cleanup

### CI Matrix

```yaml
# .github/workflows/integrations.yml
jobs:
  test:
    strategy:
      matrix:
        framework: [fastapi, django, flask]
        python: ["3.11", "3.12"]
```

---

## Dependencies to Add

```toml
# pyproject.toml
[project.optional-dependencies]
fastapi = [
    "fastapi>=0.100.0",
    "starlette>=0.27.0",
]
django = [
    "django>=4.2",
]
flask = [
    "flask>=2.0",
]
integrations = [
    "sagaz[fastapi,django,flask]",
]
```

---

## Success Criteria

| Metric | Target |
|--------|--------|
| FastAPI quickstart LoC | < 25 lines |
| Django config lines | < 10 settings |
| Connection leak tests | 0 leaks in 1000 requests |
| Test coverage (integrations) | > 90% |
| Documentation completeness | All public APIs documented |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| FastAPI lifespan API changes | Low | Medium | Pin version, monitor changelogs |
| Django async support incomplete | Medium | Low | Document sync-only for now |
| Flask 2.3 deprecations | Medium | Low | Support both old and new patterns |
| Users expect "magic" we don't provide | Medium | Medium | Clear docs on scope |

---

## Open Questions

1. **Celery integration**: Should `run_saga_background` optionally use Celery if installed?
2. **Request scoping**: Should Django sagas auto-inherit the request's DB transaction?
3. **Health endpoints**: Should we provide `/sagaz/health` endpoints automatically?
