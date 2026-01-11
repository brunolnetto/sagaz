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

from sagaz.core.listeners import SagaListener
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
_saga_to_webhook: dict[str, str] = {}  # saga_id -> correlation_id mapping


class _WebhookStatusListener(SagaListener):
    """Internal listener to track saga outcomes for webhook status."""

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        """Mark saga as successful in webhook tracking."""
        correlation_id = _saga_to_webhook.get(saga_id)
        if correlation_id and correlation_id in _webhook_tracking:
            if "saga_statuses" not in _webhook_tracking[correlation_id]:
                _webhook_tracking[correlation_id]["saga_statuses"] = {}
            _webhook_tracking[correlation_id]["saga_statuses"][saga_id] = "completed"

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        """Mark saga as failed in webhook tracking."""
        correlation_id = _saga_to_webhook.get(saga_id)
        if correlation_id and correlation_id in _webhook_tracking:
            if "saga_statuses" not in _webhook_tracking[correlation_id]:
                _webhook_tracking[correlation_id]["saga_statuses"] = {}
            _webhook_tracking[correlation_id]["saga_statuses"][saga_id] = "failed"
            _webhook_tracking[correlation_id]["saga_errors"] = _webhook_tracking[
                correlation_id
            ].get("saga_errors", {})
            _webhook_tracking[correlation_id]["saga_errors"][saga_id] = str(error)


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
        from sagaz.core.config import get_config

        self.app = app

        # Add webhook status listener to config
        config = get_config()
        if _WebhookStatusListener not in [type(listener) for listener in config.listeners]:
            config._listeners.append(_WebhookStatusListener())
        logger.info("Sagaz Flask initialized with webhook status tracking")

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

                    # Map saga IDs to correlation ID for status tracking
                    for saga_id in saga_ids:
                        _saga_to_webhook[saga_id] = correlation_id

                    # Check if any saga_ids already have completion status (idempotent case)
                    from sagaz.core.config import get_config

                    config = get_config()
                    if config.storage and saga_ids:
                        for saga_id in saga_ids:
                            try:
                                state = loop.run_until_complete(
                                    config.storage.load_saga_state(saga_id)
                                )
                                if state:
                                    # Saga already exists - populate status immediately
                                    if "saga_statuses" not in _webhook_tracking[correlation_id]:
                                        _webhook_tracking[correlation_id]["saga_statuses"] = {}

                                    from sagaz.core.types import SagaStatus

                                    status_val = state.get("status")
                                    if status_val == SagaStatus.COMPLETED:
                                        _webhook_tracking[correlation_id]["saga_statuses"][
                                            saga_id
                                        ] = "completed"
                                    elif status_val in (SagaStatus.FAILED, SagaStatus.ROLLED_BACK):
                                        _webhook_tracking[correlation_id]["saga_statuses"][
                                            saga_id
                                        ] = "failed"
                                        if state.get("error"):
                                            if (
                                                "saga_errors"
                                                not in _webhook_tracking[correlation_id]
                                            ):
                                                _webhook_tracking[correlation_id][
                                                    "saga_errors"
                                                ] = {}
                                            _webhook_tracking[correlation_id]["saga_errors"][
                                                saga_id
                                            ] = state["error"]
                            except Exception:
                                pass  # status will be tracked via listener

                    # Mark as triggered (outcomes tracked by listener for new sagas)
                    _webhook_tracking[correlation_id]["status"] = "triggered"
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

            # Compute overall status based on individual saga statuses
            saga_statuses = status.get("saga_statuses", {})
            saga_ids = status.get("saga_ids", [])
            overall_status = status["status"]

            # If triggered, check if all sagas have finished
            if overall_status == "triggered" and saga_ids:
                finished_count = sum(
                    1 for s in saga_statuses.values() if s in ("completed", "failed")
                )
                if finished_count == len(saga_ids):
                    # All sagas finished - determine overall outcome
                    failed_count = sum(1 for s in saga_statuses.values() if s == "failed")
                    if failed_count == len(saga_ids):
                        # All sagas failed
                        overall_status = "failed"
                    elif failed_count > 0:
                        # Some failed, some succeeded
                        overall_status = "completed_with_failures"
                    else:
                        # All succeeded
                        overall_status = "completed"

            response_data = {
                "correlation_id": correlation_id,
                "source": source,
                "status": overall_status,
                "saga_ids": saga_ids,
            }

            # Add saga details if available
            if saga_statuses:
                response_data["saga_statuses"] = saga_statuses

            if "saga_errors" in status:
                response_data["saga_errors"] = status["saga_errors"]

            if "error" in status:
                response_data["error"] = status["error"]

            # Add helpful messages based on status
            if overall_status == "queued":
                response_data["message"] = "Event is queued for processing"
            elif overall_status == "processing":
                response_data["message"] = "Event is currently being processed"
            elif overall_status == "triggered":
                response_data["message"] = (
                    f"Event triggered {len(saga_ids)} saga(s), waiting for completion"
                )
            elif overall_status == "completed":
                response_data["message"] = f"All {len(saga_ids)} saga(s) completed successfully"
            elif overall_status == "completed_with_failures":
                failed_count = sum(1 for s in saga_statuses.values() if s == "failed")
                response_data["message"] = f"{failed_count} of {len(saga_ids)} saga(s) failed"
            elif overall_status == "failed":
                if len(saga_ids) == 1:
                    response_data["message"] = "Saga execution failed"
                else:
                    response_data["message"] = f"All {len(saga_ids)} saga(s) failed"

            return jsonify(response_data)

        self.app.register_blueprint(bp)
