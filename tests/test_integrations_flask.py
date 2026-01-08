"""
Tests for sagaz.integrations.flask module.

These tests require Flask to be installed.
"""

import pytest

# Skip all tests if Flask is not installed
flask_pkg = pytest.importorskip("flask")

from unittest.mock import MagicMock, patch

from sagaz.integrations.flask import (
    SagaFlask,
    run_saga_sync,
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


class TestSagaFlask:
    """Tests for SagaFlask extension."""
    
    def test_init_with_app(self):
        """Test initialization with app."""
        from flask import Flask
        
        app = Flask(__name__)
        config = SagaConfig(storage_backend="memory")
        
        saga_ext = SagaFlask(app, config)
        
        assert 'sagaz' in app.extensions
        assert app.extensions['sagaz'] is saga_ext
    
    def test_init_app_later(self):
        """Test init_app pattern."""
        from flask import Flask
        
        app = Flask(__name__)
        config = SagaConfig(storage_backend="memory")
        
        saga_ext = SagaFlask(config=config)
        saga_ext.init_app(app)
        
        assert 'sagaz' in app.extensions
    
    def test_run_sync_executes_saga(self):
        """Test run_sync executes a saga synchronously."""
        from flask import Flask
        
        app = Flask(__name__)
        config = SagaConfig(storage_backend="memory")
        saga_ext = SagaFlask(app, config)
        
        saga = TestOrderSaga()
        
        with app.app_context():
            result = saga_ext.run_sync(saga, {"user_id": "test-user"})
        
        assert result["order_id"] == "test-123"
        assert result["user_id"] == "test-user"
    
    def test_before_request_sets_correlation_id(self):
        """Test that before_request sets correlation ID."""
        from flask import Flask
        
        app = Flask(__name__)
        config = SagaConfig(storage_backend="memory")
        SagaFlask(app, config)
        
        @app.route("/test")
        def test_route():
            from flask import g
            return {"correlation_id": g.saga_correlation_id}
        
        with app.test_client() as client:
            response = client.get("/test")
            data = response.get_json()
            
            # Should have a correlation ID
            assert "correlation_id" in data
            assert len(data["correlation_id"]) > 0
    
    def test_propagates_incoming_correlation_id(self):
        """Test that incoming correlation ID is propagated."""
        from flask import Flask
        
        app = Flask(__name__)
        config = SagaConfig(storage_backend="memory")
        SagaFlask(app, config)
        
        @app.route("/test")
        def test_route():
            from flask import g
            return {"correlation_id": g.saga_correlation_id}
        
        with app.test_client() as client:
            response = client.get(
                "/test",
                headers={"X-Correlation-ID": "incoming-123"},
            )
            data = response.get_json()
            
            assert data["correlation_id"] == "incoming-123"
    
    def test_response_includes_correlation_id(self):
        """Test that response includes correlation ID header."""
        from flask import Flask
        
        app = Flask(__name__)
        config = SagaConfig(storage_backend="memory")
        SagaFlask(app, config)
        
        @app.route("/test")
        def test_route():
            return {"ok": True}
        
        with app.test_client() as client:
            response = client.get("/test")
            
            assert "X-Correlation-ID" in response.headers
    
    def test_create_saga_injects_correlation_id(self):
        """Test that create_saga injects correlation ID."""
        from flask import Flask
        
        app = Flask(__name__)
        config = SagaConfig(storage_backend="memory")
        saga_ext = SagaFlask(app, config)
        
        @app.route("/test")
        def test_route():
            saga = saga_ext.create_saga(TestOrderSaga)
            return {"created": True}
        
        with app.test_client() as client:
            response = client.get(
                "/test",
                headers={"X-Correlation-ID": "test-123"},
            )
            
            assert response.status_code == 200


class TestRunSagaSync:
    """Tests for run_saga_sync function."""
    
    def test_run_saga_sync_executes(self):
        """Test that run_saga_sync executes a saga."""
        saga = TestOrderSaga()
        
        result = run_saga_sync(saga, {"user_id": "test-user"})
        
        assert result["order_id"] == "test-123"
        assert result["user_id"] == "test-user"
    
    def test_run_saga_sync_multiple_times(self):
        """Test running multiple sagas."""
        results = []
        
        for i in range(3):
            saga = TestOrderSaga()
            result = run_saga_sync(saga, {"user_id": f"user-{i}"})
            results.append(result)
        
        assert len(results) == 3
        assert results[0]["user_id"] == "user-0"
        assert results[1]["user_id"] == "user-1"
        assert results[2]["user_id"] == "user-2"
