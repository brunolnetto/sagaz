"""
Flask integration for Sagaz.

Provides:
- SagaFlask extension class
- Middleware for correlation ID propagation
- Webhook blueprint registration (async, fire-and-forget)
- Webhook status tracking
"""

import threading
from typing import Any

from sagaz.core.logger import get_logger
from sagaz.integrations._base import (
    SagaContextManager,
    generate_correlation_id,
    get_correlation_id,
)

logger = get_logger(__name__)

__all__ = [
    "SagaContextManager",
    "SagaFlask",
    "get_logger",
    "get_webhook_status",
]

# Global tracking for webhook status (in-memory for demo)
_webhook_tracking: dict[str, dict[str, Any]] = {}


def get_webhook_status(correlation_id: str) -> dict[str, Any] | None:
    """
    Get status of a webhook event by correlation ID.

    Args:
        correlation_id: The correlation ID from the webhook response

    Returns:
        Status dictionary or None if not found

    Example:
        status = get_webhook_status("abc-123-xyz")
        if status:
            print(f"Status: {status['status']}")
            print(f"Saga IDs: {status['saga_ids']}")
    """
    return _webhook_tracking.get(correlation_id)


class SagaFlask:
    """
    Flask extension for Sagaz integration.

    Example:
        from flask import Flask
        from sagaz.integrations.flask import SagaFlask

        app = Flask(__name__)
        saga_flask = SagaFlask(app)

        # Register webhook blueprint
        saga_flask.register_webhook_blueprint("/webhooks")
    """

    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize the extension with a Flask app."""
        self.app = app

        @app.before_request
        def before_request():
            """Set up saga context for each request."""
            from flask import g, request

            # Get or generate correlation ID
            correlation_id = request.headers.get("X-Correlation-ID")
            if not correlation_id:
                correlation_id = generate_correlation_id()

            g.correlation_id = correlation_id
            SagaContextManager.set("correlation_id", correlation_id)

    def register_webhook_blueprint(self, url_prefix: str = "/webhooks"):
        """
        Register a webhook blueprint for event handling (fire-and-forget).

        Events are processed asynchronously in a background thread.
        The webhook returns immediately with 202 Accepted.

        Args:
            url_prefix: URL prefix for webhook endpoints
        """
        try:
            from flask import Blueprint, jsonify, request
        except ImportError:  # pragma: no cover
            msg = "Flask is required. Install with: pip install flask"
            raise ImportError(msg)

        import asyncio

        bp = Blueprint("sagaz_webhooks", __name__, url_prefix=url_prefix)

        @bp.route("/<source>", methods=["POST"])
        def webhook_handler(source: str):
            """
            Handle incoming webhook events (fire-and-forget).

            Returns immediately with 202 Accepted.
            """
            from sagaz.triggers import fire_event

            payload = request.get_json(silent=True) or {}

            # Get or generate correlation ID
            correlation_id = request.headers.get("X-Correlation-ID") or generate_correlation_id()

            # Store initial status
            _webhook_tracking[correlation_id] = {
                "status": "queued",
                "saga_ids": [],
                "source": source,
            }

            # Fire event in background thread (fire-and-forget)
            def process_in_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    _webhook_tracking[correlation_id]["status"] = "processing"
                    saga_ids = loop.run_until_complete(fire_event(source, payload))
                    _webhook_tracking[correlation_id]["saga_ids"] = saga_ids
                    _webhook_tracking[correlation_id]["status"] = "completed"
                    logger.info(f"Webhook {source} triggered sagas: {saga_ids}")
                except Exception as e:
                    _webhook_tracking[correlation_id]["status"] = "failed"
                    _webhook_tracking[correlation_id]["error"] = str(e)
                    logger.error(f"Webhook {source} processing error: {e}")
                finally:
                    loop.close()

            thread = threading.Thread(target=process_in_thread, daemon=True)
            thread.start()

            return jsonify(
                {
                    "status": "accepted",
                    "source": source,
                    "message": "Event queued for processing",
                    "correlation_id": correlation_id,
                }
            ), 202  # Accepted

        @bp.route("/<source>/status/<correlation_id>", methods=["GET"])
        def webhook_status_handler(source: str, correlation_id: str):
            """
            Check status of a webhook event.

            Returns the current status of event processing.
            """
            status = get_webhook_status(correlation_id)

            if not status:
                return jsonify(
                    {
                        "correlation_id": correlation_id,
                        "source": source,
                        "status": "not_found",
                        "message": "No webhook event found with this correlation ID",
                    }
                ), 404

            response_data = {
                "correlation_id": correlation_id,
                "source": source,
                "status": status["status"],
                "saga_ids": status.get("saga_ids", []),
            }

            if "error" in status:
                response_data["error"] = status["error"]

            # Add helpful messages based on status
            if status["status"] == "queued":
                response_data["message"] = "Event is queued for processing"
            elif status["status"] == "processing":
                response_data["message"] = "Event is currently being processed"
            elif status["status"] == "completed":
                response_data["message"] = (
                    f"Event processed successfully, triggered {len(status['saga_ids'])} saga(s)"
                )
            elif status["status"] == "failed":
                response_data["message"] = "Event processing failed"

            return jsonify(response_data)

        self.app.register_blueprint(bp)
