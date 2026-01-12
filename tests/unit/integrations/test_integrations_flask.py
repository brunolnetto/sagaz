"""
Tests for sagaz.integrations.flask module.

These tests require Flask to be installed.
"""

import pytest

# Skip all tests if Flask is not installed
flask_pkg = pytest.importorskip("flask")

from unittest.mock import MagicMock, patch

from sagaz.core.decorators import Saga, action
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


class TestWebhookStatusTracking:
    """Tests for webhook status tracking functionality."""

    def test_get_webhook_status_not_found(self):
        """Test get_webhook_status returns None for unknown ID."""
        from sagaz.integrations.flask import get_webhook_status

        status = get_webhook_status("nonexistent-id")
        assert status is None

    @pytest.mark.asyncio
    async def test_webhook_status_listener_on_complete(self):
        """Test webhook status listener tracks saga completion."""
        from sagaz.integrations.flask import (
            _WebhookStatusListener,
            _webhook_tracking,
            _saga_to_webhook,
        )

        # Setup tracking
        correlation_id = "test-corr-flask-123"
        saga_id = "saga-flask-456"
        _webhook_tracking[correlation_id] = {"status": "processing"}
        _saga_to_webhook[saga_id] = correlation_id

        listener = _WebhookStatusListener()
        await listener.on_saga_complete("test_saga", saga_id, {"key": "value"})

        # Check status was updated
        assert "saga_statuses" in _webhook_tracking[correlation_id]
        assert _webhook_tracking[correlation_id]["saga_statuses"][saga_id] == "completed"

        # Cleanup
        _webhook_tracking.clear()
        _saga_to_webhook.clear()

    @pytest.mark.asyncio
    async def test_webhook_status_listener_on_failed(self):
        """Test webhook status listener tracks saga failure."""
        from sagaz.integrations.flask import (
            _WebhookStatusListener,
            _webhook_tracking,
            _saga_to_webhook,
        )

        # Setup tracking
        correlation_id = "test-corr-flask-789"
        saga_id = "saga-flask-012"
        _webhook_tracking[correlation_id] = {"status": "processing"}
        _saga_to_webhook[saga_id] = correlation_id

        listener = _WebhookStatusListener()
        test_error = Exception("Test Flask error")
        await listener.on_saga_failed("test_saga", saga_id, {"key": "value"}, test_error)

        # Check status was updated
        assert "saga_statuses" in _webhook_tracking[correlation_id]
        assert _webhook_tracking[correlation_id]["saga_statuses"][saga_id] == "failed"
        assert "saga_errors" in _webhook_tracking[correlation_id]
        assert "Test Flask error" in _webhook_tracking[correlation_id]["saga_errors"][saga_id]

        # Cleanup
        _webhook_tracking.clear()
        _saga_to_webhook.clear()

    def test_webhook_blueprint_registration(self):
        """Test webhook blueprint can be registered."""
        from flask import Flask

        app = Flask(__name__)
        saga_ext = SagaFlask(app)

        # Register webhook blueprint with custom prefix
        saga_ext.register_webhook_blueprint("/api/hooks")

        # Check blueprint was registered
        assert "sagaz_webhooks" in app.blueprints

    def test_webhook_endpoint_fires_event(self):
        """Test webhook endpoint fires event on POST."""
        from flask import Flask
        from unittest.mock import AsyncMock, patch

        app = Flask(__name__)
        saga_ext = SagaFlask(app)
        saga_ext.register_webhook_blueprint("/webhooks")

        with app.test_client() as client:
            with patch("sagaz.triggers.fire_event", new_callable=AsyncMock) as mock_fire:
                # Mock fire_event to return a saga_id
                mock_fire.return_value = ["saga-123"]

                response = client.post(
                    "/webhooks/test_event",
                    json={"test": "data"},
                    headers={"Content-Type": "application/json"},
                )

                assert response.status_code == 202  # Accepted
                response_data = response.get_json()
                assert response_data["status"] == "accepted"
                assert "correlation_id" in response_data

    def test_extension_without_app(self):
        """Test SagaFlask extension without app initialization."""
        saga_ext = SagaFlask()

        # Should not raise, app is None
        assert saga_ext.app is None

    def test_middleware_without_blueprint(self):
        """Test SagaFlask can work without webhook blueprint."""
        from flask import Flask

        app = Flask(__name__)
        saga_ext = SagaFlask(app)

        # Don't register blueprint
        # Should still work for correlation ID tracking

        @app.route("/test")
        def test_route():
            from flask import g

            return {"correlation_id": getattr(g, "correlation_id", None)}

        with app.test_client() as client:
            response = client.get("/test")
            data = response.get_json()

            # Should still have correlation ID from middleware
            assert data["correlation_id"] is not None

    def test_context_manager_set_get(self):
        """Test setting and getting context values."""
        SagaContextManager.set("test_key", "test_value")
        assert SagaContextManager.get("test_key") == "test_value"
        SagaContextManager.clear()
