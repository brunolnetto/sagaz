"""
Tests for sagaz.integrations.fastapi module.

These tests require FastAPI and Starlette to be installed.
"""

import pytest

# Skip all tests if FastAPI is not installed
fastapi = pytest.importorskip("fastapi")
starlette = pytest.importorskip("starlette")

from unittest.mock import AsyncMock, MagicMock, patch

from sagaz.decorators import Saga, action
from sagaz.integrations.fastapi import (
    SagaContextManager,
    create_webhook_router,
    generate_correlation_id,
    get_correlation_id,
    get_logger,
    sagaz_shutdown,
    sagaz_startup,
)


# Sample saga for use in tests (not prefixed with Test to avoid pytest collection)
class SampleOrderSaga(Saga):
    """Sample saga for unit tests."""

    saga_name = "sample-order"

    @action("create_order")
    async def create_order(self, ctx):
        return {"order_id": "test-123", "user_id": ctx.get("user_id")}


class TestSagaLifecycle:
    """Tests for sagaz_startup and sagaz_shutdown hooks."""

    @pytest.mark.asyncio
    async def test_startup_shutdown_no_errors(self):
        """Test that startup and shutdown can be called without errors."""
        # These are simple logging hooks, they should not raise
        await sagaz_startup()
        await sagaz_shutdown()


class TestCorrelationId:
    """Tests for correlation ID utilities."""

    def test_generate_correlation_id(self):
        """Test that generate_correlation_id returns a valid ID."""
        cid = generate_correlation_id()
        assert cid is not None
        assert len(cid) > 0

    def test_get_correlation_id_returns_generated(self):
        """Test that get_correlation_id works."""
        # When not in a context, it should return None or generate
        result = get_correlation_id()
        # Result could be None if no context is set
        assert result is None or isinstance(result, str)


class TestCreateWebhookRouter:
    """Tests for create_webhook_router function."""

    def test_creates_router(self):
        """Test that create_webhook_router returns an APIRouter."""
        from fastapi import APIRouter

        router = create_webhook_router()
        assert isinstance(router, APIRouter)
        assert router.prefix == "/webhooks"

    def test_creates_router_with_custom_prefix(self):
        """Test that create_webhook_router accepts custom prefix."""
        router = create_webhook_router("/api/hooks")
        assert router.prefix == "/api/hooks"

    @pytest.mark.asyncio
    async def test_webhook_endpoint_exists(self):
        """Test that the webhook endpoint is registered."""
        router = create_webhook_router()
        routes = router.routes

        # Should have at least one route
        assert len(routes) >= 1

        # Find the POST route
        post_route = None
        for route in routes:
            if hasattr(route, "methods") and "POST" in route.methods:
                post_route = route
                break

        assert post_route is not None


class TestWebhookIntegration:
    """Integration tests for webhook endpoint."""

    @pytest.mark.asyncio
    async def test_webhook_returns_202_accepted(self):
        """Test that webhook returns 202 Accepted."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(create_webhook_router())

        client = TestClient(app)
        response = client.post(
            "/webhooks/test",
            json={"event": "test_event", "data": {"key": "value"}}
        )

        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        assert response.json()["source"] == "test"

    @pytest.mark.asyncio
    async def test_webhook_handles_empty_body(self):
        """Test that webhook handles empty/invalid JSON body."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(create_webhook_router())

        client = TestClient(app)
        # Send invalid JSON
        response = client.post(
            "/webhooks/test",
            content="not json",
            headers={"Content-Type": "application/json"}
        )

        # Should still return 202 (empty payload will be used)
        assert response.status_code == 202


class TestSagaContextManager:
    """Tests for SagaContextManager from base integration."""

    def test_context_manager_exists(self):
        """Test that SagaContextManager is exported."""
        assert SagaContextManager is not None


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """Test that get_logger returns a logger instance."""
        logger = get_logger()
        assert logger is not None
