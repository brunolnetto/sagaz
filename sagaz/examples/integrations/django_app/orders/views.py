"""
Django views for order operations.

The main entry point is the webhook at /webhooks/<source>/
which triggers sagas registered with @trigger(source=...).
"""

import asyncio
import uuid

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from sagaz.core.config import get_config
from sagaz.integrations.django import get_webhook_status

from .sagas import OrderSaga


def health_check(request):
    """Health check endpoint."""
    return JsonResponse({"status": "healthy"})


@method_decorator(csrf_exempt, name="dispatch")
class OrderValidateView(View):
    """
    Validate if an order can be processed.

    This demonstrates idempotency checking before webhook submission.
    Checks if order_id is already being processed or completed.
    """

    def post(self, request):
        import json

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if "order_id" not in data:
            return JsonResponse({"error": "order_id is required"}, status=400)

        order_id = data["order_id"]

        # Derive deterministic saga_id from order_id (same as trigger does)
        saga_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, order_id))

        # Check if saga exists in storage
        config = get_config()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            state = loop.run_until_complete(config.storage.load_saga_state(saga_id))
        finally:
            loop.close()

        if state:
            from sagaz.core.types import SagaStatus

            status = state.get("status")
            if status == SagaStatus.COMPLETED:
                return JsonResponse(
                    {
                        "valid": False,
                        "order_id": order_id,
                        "saga_id": saga_id,
                        "reason": "Order already processed successfully",
                        "saga_status": "completed",
                        "advice": "This order has been completed. Use a different order_id.",
                    },
                    status=409,  # Conflict
                )
            if status == SagaStatus.EXECUTING:
                return JsonResponse(
                    {
                        "valid": False,
                        "order_id": order_id,
                        "saga_id": saga_id,
                        "reason": "Order is currently being processed",
                        "saga_status": "executing",
                        "advice": "Wait for this order to complete before resubmitting.",
                    },
                    status=409,  # Conflict
                )
            if status in (SagaStatus.FAILED, SagaStatus.ROLLED_BACK):
                return JsonResponse(
                    {
                        "valid": True,
                        "order_id": order_id,
                        "saga_id": saga_id,
                        "message": "Order previously failed, can be retried",
                        "saga_status": status.value,
                        "advice": "This order can be resubmitted via webhook.",
                    }
                )

        return JsonResponse(
            {
                "valid": True,
                "order_id": order_id,
                "message": "Order can be processed",
                "saga_id": saga_id,
                "advice": "Submit order via POST /webhooks/order_created/",
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class OrderDiagramView(View):
    """Get saga diagram."""

    def get(self, request, order_id):
        saga = OrderSaga()
        return JsonResponse(
            {
                "order_id": order_id,
                "diagram": saga.to_mermaid(),
                "format": "mermaid",
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class WebhookStatusView(View):
    """Check status of event processing."""

    def get(self, request, source, correlation_id):
        status = get_webhook_status(correlation_id)

        if not status:
            return self._not_found_response(correlation_id, source)

        response_data = self._build_response_data(status, correlation_id, source)
        return JsonResponse(response_data)

    def _not_found_response(self, correlation_id, source):
        """Build 404 response."""
        return JsonResponse(
            {
                "correlation_id": correlation_id,
                "source": source,
                "status": "not_found",
                "message": "No webhook event found with this correlation ID",
            },
            status=404,
        )

    def _build_response_data(self, status, correlation_id, source):
        """Build response data dictionary."""
        saga_statuses = status.get("saga_statuses", {})
        saga_ids = status.get("saga_ids", [])
        overall_status = self._compute_overall_status(status, saga_statuses, saga_ids)

        response_data = {
            "correlation_id": correlation_id,
            "source": source,
            "status": overall_status,
            "saga_ids": saga_ids,
        }

        self._add_optional_fields(response_data, status, saga_statuses)
        response_data["message"] = self._get_status_message(overall_status, saga_ids, saga_statuses)

        return response_data

    def _compute_overall_status(self, status, saga_statuses, saga_ids):
        """Compute overall status from saga statuses."""
        overall_status = status["status"]

        if overall_status == "triggered" and saga_ids:
            completed_count = sum(1 for s in saga_statuses.values() if s in ("completed", "failed"))
            if completed_count == len(saga_ids):
                failed_count = sum(1 for s in saga_statuses.values() if s == "failed")
                overall_status = "completed_with_failures" if failed_count > 0 else "completed"

        return overall_status

    def _add_optional_fields(self, response_data, status, saga_statuses):
        """Add optional fields to response."""
        if saga_statuses:
            response_data["saga_statuses"] = saga_statuses
        if "saga_errors" in status:
            response_data["saga_errors"] = status["saga_errors"]
        if "error" in status:
            response_data["error"] = status["error"]

    def _get_status_message(self, overall_status, saga_ids, saga_statuses):
        """Get message for status."""
        messages = {
            "queued": "Event is queued for processing",
            "processing": "Event is currently being processed",
            "triggered": f"Event triggered {len(saga_ids)} saga(s), waiting for completion",
            "completed": f"All {len(saga_ids)} saga(s) completed successfully",
            "failed": "Event processing failed",
        }

        if overall_status in messages:
            return messages[overall_status]

        if overall_status == "completed_with_failures":
            failed_sagas = [sid for sid, s in saga_statuses.items() if s == "failed"]
            return f"{len(failed_sagas)} of {len(saga_ids)} saga(s) failed"

        return ""
