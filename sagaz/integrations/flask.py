"""
Flask integration for Sagaz.

Provides:
- SagaFlask extension class
- Middleware for correlation ID propagation
- Webhook blueprint registration (async, fire-and-forget)
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
]


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

            # Generate a correlation ID for this event
            correlation_id = generate_correlation_id()

            # Store saga IDs for status tracking
            saga_ids_container = []

            # Fire event in background thread (fire-and-forget)
            def process_in_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    saga_ids = loop.run_until_complete(fire_event(source, payload))
                    saga_ids_container.extend(saga_ids)
                    logger.debug(f"Webhook {source} triggered sagas: {saga_ids}")
                except Exception as e:  # pragma: no cover
                    logger.error(f"Webhook {source} processing error: {e}")  # pragma: no cover
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

        self.app.register_blueprint(bp)
