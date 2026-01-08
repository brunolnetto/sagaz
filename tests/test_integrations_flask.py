"""
Tests for sagaz.integrations.flask module.

These tests require Flask to be installed.
"""

import pytest

# Skip all tests if Flask is not installed
flask_pkg = pytest.importorskip("flask")

from unittest.mock import MagicMock, patch

from sagaz.decorators import Saga, action
from sagaz.integrations.flask import (
    SagaContextManager,
    SagaFlask,
)


# Sample saga for use in tests (not prefixed with Test to avoid pytest collection)
class SampleOrderSaga(Saga):
    """Sample saga for unit tests."""

    saga_name = "sample-order"

    @action("create_order")
    async def create_order(self, ctx):
        return {"order_id": "test-123", "user_id": ctx.get("user_id")}


class TestSagaFlask:
    """Tests for SagaFlask extension."""

    def test_init_with_app(self):
        """Test initialization with app."""
        from flask import Flask

        app = Flask(__name__)

        saga_ext = SagaFlask(app)

        assert saga_ext.app is app

    def test_init_app_later(self):
        """Test init_app pattern."""
        from flask import Flask

        app = Flask(__name__)

        saga_ext = SagaFlask()
        saga_ext.init_app(app)

        assert saga_ext.app is app

    def test_before_request_sets_correlation_id(self):
        """Test that before_request sets correlation ID."""
        from flask import Flask, g

        app = Flask(__name__)
        SagaFlask(app)

        @app.route("/test")
        def test_route():
            return {"correlation_id": g.correlation_id}

        with app.test_client() as client:
            response = client.get("/test")
            data = response.get_json()

            # Should have a correlation ID
            assert "correlation_id" in data
            assert len(data["correlation_id"]) > 0

    def test_propagates_incoming_correlation_id(self):
        """Test that incoming correlation ID is propagated."""
        from flask import Flask, g

        app = Flask(__name__)
        SagaFlask(app)

        @app.route("/test")
        def test_route():
            return {"correlation_id": g.correlation_id}

        with app.test_client() as client:
            response = client.get(
                "/test",
                headers={"X-Correlation-ID": "incoming-123"},
            )
            data = response.get_json()

            assert data["correlation_id"] == "incoming-123"

    def test_register_webhook_blueprint(self):
        """Test that webhook blueprint can be registered."""
        from flask import Flask

        app = Flask(__name__)
        saga_ext = SagaFlask(app)

        # Should not raise
        saga_ext.register_webhook_blueprint("/webhooks")

        # Check that routes are registered
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        assert any("/webhooks/" in rule for rule in rules)

    def test_webhook_returns_202(self):
        """Test that webhook endpoint returns 202 Accepted."""
        from flask import Flask

        app = Flask(__name__)
        saga_ext = SagaFlask(app)
        saga_ext.register_webhook_blueprint("/webhooks")

        with app.test_client() as client:
            response = client.post(
                "/webhooks/test",
                json={"event": "test", "data": {}},
            )

            assert response.status_code == 202
            data = response.get_json()
            assert data["status"] == "accepted"
            assert data["source"] == "test"


class TestSagaContextManager:
    """Tests for SagaContextManager from base integration."""

    def test_context_manager_exists(self):
        """Test that SagaContextManager is exported."""
        assert SagaContextManager is not None

    def test_context_manager_set_get(self):
        """Test setting and getting context values."""
        SagaContextManager.set("test_key", "test_value")
        assert SagaContextManager.get("test_key") == "test_value"
        SagaContextManager.clear()
