"""
Tests for sagaz.integrations.django module.

These tests require Django to be installed.
"""

import pytest
import os

# Set up Django settings before importing
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tests.django_test_settings')

# Skip all tests if Django is not installed
django = pytest.importorskip("django")

# Configure Django
django.setup()

from unittest.mock import MagicMock, patch

from sagaz.integrations.django import (
    get_sagaz_config,
    run_saga_sync,
    create_saga,
    SagaDjangoMiddleware,
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


class TestRunSagaSync:
    """Tests for run_saga_sync function."""
    
    def test_run_saga_sync_executes(self):
        """Test that run_saga_sync executes a saga."""
        saga = TestOrderSaga()
        
        result = run_saga_sync(saga, {"user_id": "test-user"})
        
        assert result["order_id"] == "test-123"
        assert result["user_id"] == "test-user"
    
    def test_run_saga_sync_with_correlation_id(self):
        """Test that correlation ID is propagated."""
        SagaContextManager.set("correlation_id", "test-correlation")
        
        try:
            saga = TestOrderSaga()
            result = run_saga_sync(saga, {"user_id": "test-user"})
            
            assert result["order_id"] == "test-123"
        finally:
            SagaContextManager.clear()


class TestCreateSaga:
    """Tests for create_saga function."""
    
    def test_create_saga_returns_instance(self):
        """Test that create_saga creates a saga instance."""
        saga = create_saga(TestOrderSaga)
        
        assert isinstance(saga, TestOrderSaga)
    
    def test_create_saga_with_correlation_id(self):
        """Test that create_saga sets correlation ID if available."""
        SagaContextManager.set("correlation_id", "test-123")
        
        try:
            saga = create_saga(TestOrderSaga)
            assert isinstance(saga, TestOrderSaga)
        finally:
            SagaContextManager.clear()


class TestSagaDjangoMiddleware:
    """Tests for SagaDjangoMiddleware."""
    
    def test_middleware_sets_correlation_id(self):
        """Test that middleware sets correlation ID."""
        def get_response(request):
            # Simulate view response
            response = MagicMock()
            response.__setitem__ = MagicMock()
            return response
        
        middleware = SagaDjangoMiddleware(get_response)
        
        # Mock request
        request = MagicMock()
        request.META = {}
        request.path = "/test"
        request.method = "GET"
        
        response = middleware(request)
        
        # Should have set correlation ID on request
        assert hasattr(request, 'saga_correlation_id')
        assert len(request.saga_correlation_id) > 0
    
    def test_middleware_propagates_incoming_correlation_id(self):
        """Test that middleware propagates incoming correlation ID."""
        def get_response(request):
            response = MagicMock()
            response.__setitem__ = MagicMock()
            return response
        
        middleware = SagaDjangoMiddleware(get_response)
        
        # Mock request with correlation ID
        request = MagicMock()
        request.META = {"HTTP_X_CORRELATION_ID": "incoming-123"}
        request.path = "/test"
        request.method = "GET"
        
        response = middleware(request)
        
        assert request.saga_correlation_id == "incoming-123"
    
    def test_middleware_adds_header_to_response(self):
        """Test that middleware adds correlation ID to response."""
        def get_response(request):
            response = {}
            return response
        
        middleware = SagaDjangoMiddleware(get_response)
        
        request = MagicMock()
        request.META = {}
        request.path = "/test"
        request.method = "GET"
        
        response = middleware(request)
        
        assert "X-Correlation-ID" in response
    
    def test_middleware_clears_context(self):
        """Test that middleware clears context after request."""
        SagaContextManager.set("test_key", "test_value")
        
        def get_response(request):
            return {}
        
        middleware = SagaDjangoMiddleware(get_response)
        
        request = MagicMock()
        request.META = {}
        request.path = "/test"
        request.method = "GET"
        
        middleware(request)
        
        # Context should be cleared
        assert SagaContextManager.get("test_key") is None
