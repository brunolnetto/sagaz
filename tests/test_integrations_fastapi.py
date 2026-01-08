"""
Tests for sagaz.integrations.fastapi module.

These tests require FastAPI and Starlette to be installed.
"""

import pytest

# Skip all tests if FastAPI is not installed
fastapi = pytest.importorskip("fastapi")
starlette = pytest.importorskip("starlette")

from unittest.mock import AsyncMock, MagicMock, patch

from sagaz.integrations.fastapi import (
    create_lifespan,
    get_config,
    saga_factory,
    run_saga_background,
    SagaContextMiddleware,
    _config,
)
from sagaz.integrations._base import SagaContextManager
from sagaz.config import SagaConfig
from sagaz.decorators import Saga, action


# Test saga for use in tests
class TestOrderSaga(Saga):
    """Test saga for unit tests."""
    
    saga_name = "test-order"
    
    @action("create_order")
    async def create_order(self, ctx):
        return {"order_id": "test-123", "user_id": ctx.get("user_id")}


class TestCreateLifespan:
    """Tests for create_lifespan function."""
    
    @pytest.mark.asyncio
    async def test_lifespan_initializes_config(self):
        """Test that lifespan initializes the config."""
        config = SagaConfig(storage_backend="memory")
        lifespan = create_lifespan(config)
        
        # Mock app
        app = MagicMock()
        
        async with lifespan(app):
            # Config should be accessible
            from sagaz.integrations import fastapi
            assert fastapi._config is config
    
    @pytest.mark.asyncio
    async def test_lifespan_cleans_up(self):
        """Test that lifespan cleans up on exit."""
        config = SagaConfig(storage_backend="memory")
        lifespan = create_lifespan(config)
        
        app = MagicMock()
        
        async with lifespan(app):
            pass
        
        # Config should be cleared
        from sagaz.integrations import fastapi
        assert fastapi._config is None


class TestGetConfig:
    """Tests for get_config dependency."""
    
    @pytest.mark.asyncio
    async def test_get_config_returns_config(self):
        """Test that get_config returns the current config."""
        from sagaz.integrations import fastapi
        
        config = SagaConfig(storage_backend="memory")
        fastapi._config = config
        
        try:
            result = get_config()
            assert result is config
        finally:
            fastapi._config = None
    
    def test_get_config_raises_without_lifespan(self):
        """Test that get_config raises if not initialized."""
        from sagaz.integrations import fastapi
        fastapi._config = None
        
        with pytest.raises(RuntimeError, match="not initialized"):
            get_config()


class TestSagaFactory:
    """Tests for saga_factory dependency."""
    
    @pytest.mark.asyncio
    async def test_saga_factory_creates_instance(self):
        """Test that saga_factory creates saga instances."""
        from sagaz.integrations import fastapi
        
        config = SagaConfig(storage_backend="memory")
        fastapi._config = config
        
        try:
            factory = saga_factory(TestOrderSaga)
            saga = await factory()
            
            assert isinstance(saga, TestOrderSaga)
        finally:
            fastapi._config = None


class TestRunSagaBackground:
    """Tests for run_saga_background function."""
    
    @pytest.mark.asyncio
    async def test_run_saga_background_schedules_task(self):
        """Test that run_saga_background schedules the saga."""
        from fastapi import BackgroundTasks
        
        background_tasks = BackgroundTasks()
        saga = TestOrderSaga()
        
        saga_id = await run_saga_background(
            background_tasks,
            saga,
            {"user_id": "test-user"},
        )
        
        # Should return a saga ID
        import uuid
        uuid.UUID(saga_id)  # Should not raise
        
        # Task should be added
        assert len(background_tasks.tasks) == 1
    
    @pytest.mark.asyncio
    async def test_run_saga_background_with_callbacks(self):
        """Test that callbacks are invoked."""
        from fastapi import BackgroundTasks
        
        background_tasks = BackgroundTasks()
        saga = TestOrderSaga()
        
        success_called = []
        failure_called = []
        
        saga_id = await run_saga_background(
            background_tasks,
            saga,
            {"user_id": "test-user"},
            on_success=lambda r: success_called.append(r),
            on_failure=lambda e: failure_called.append(e),
        )
        
        # Execute the background task
        for task in background_tasks.tasks:
            await task["func"]()
        
        # Success callback should have been called
        assert len(success_called) == 1
        assert success_called[0]["order_id"] == "test-123"


class TestSagaContextMiddleware:
    """Tests for SagaContextMiddleware."""
    
    @pytest.mark.asyncio
    async def test_middleware_sets_correlation_id(self):
        """Test that middleware sets correlation ID."""
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import JSONResponse
        
        async def homepage(request):
            return JSONResponse({"ok": True})
        
        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(SagaContextMiddleware)
        
        client = TestClient(app)
        response = client.get("/")
        
        # Response should have correlation ID header
        assert "X-Correlation-ID" in response.headers
    
    @pytest.mark.asyncio
    async def test_middleware_propagates_incoming_correlation_id(self):
        """Test that middleware propagates incoming correlation ID."""
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import JSONResponse
        
        async def homepage(request):
            return JSONResponse({"ok": True})
        
        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(SagaContextMiddleware)
        
        client = TestClient(app)
        response = client.get(
            "/",
            headers={"X-Correlation-ID": "incoming-123"},
        )
        
        # Should echo back the same correlation ID
        assert response.headers["X-Correlation-ID"] == "incoming-123"
