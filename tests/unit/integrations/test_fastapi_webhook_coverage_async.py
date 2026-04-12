"""
Comprehensive tests covering missing lines in sagaz/integrations/fastapi.py.
Uses httpx.AsyncClient + ASGITransport so that async handlers run in the same
event loop as the test — meaning coverage.py can trace every line.

Missing lines: 48-53, 59-68, 103-110, 117, 148-150, 162-278, 295-366
"""

import pytest

fastapi_mod = pytest.importorskip("fastapi")
httpx_mod = pytest.importorskip("httpx")

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI
from httpx._transports.asgi import ASGITransport

from sagaz.integrations.fastapi import (
    _saga_to_webhook,
    _webhook_tracking,
    _WebhookStatusListener,
    create_webhook_router,
    get_webhook_status,
    sagaz_shutdown,
    sagaz_startup,
)


@pytest.fixture(autouse=True)
def clear_tracking():
    """Clear webhook tracking state before each test."""
    _webhook_tracking.clear()
    _saga_to_webhook.clear()
    yield
    _webhook_tracking.clear()
    _saga_to_webhook.clear()


def _make_app(prefix="/webhooks"):
    app = FastAPI()
    app.include_router(create_webhook_router(prefix))
    return app


async def _post(app, path, json=None, headers=None):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(path, json=json, headers=headers or {})


async def _get(app, path):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


# =============================================================================
# Lifecycle hooks (lines 103-110, 117)
# =============================================================================


class TestSagaLifecycleHooks:
    """Test sagaz_startup and sagaz_shutdown hooks."""

    async def test_sagaz_startup_adds_listener(self):
        """Lines 103-110: sagaz_startup adds _WebhookStatusListener to config."""
        mock_config = MagicMock()
        mock_config.listeners = []
        mock_config._listeners = []

        with patch("sagaz.core.config.get_config", return_value=mock_config):
            await sagaz_startup()

        assert any(isinstance(l, _WebhookStatusListener) for l in mock_config._listeners)

    async def test_sagaz_startup_does_not_duplicate_listener(self):
        """Lines 103-110: sagaz_startup won't add listener if already present."""
        existing = _WebhookStatusListener()
        mock_config = MagicMock()
        mock_config.listeners = [existing]
        mock_config._listeners = [existing]

        with patch("sagaz.core.config.get_config", return_value=mock_config):
            await sagaz_startup()

        count = sum(1 for l in mock_config._listeners if isinstance(l, _WebhookStatusListener))
        assert count == 1

    async def test_sagaz_shutdown(self):
        """Line 117: sagaz_shutdown runs without error."""
        await sagaz_shutdown()  # smoke test


# =============================================================================
# _WebhookStatusListener (lines 48-53, 59-68)
# =============================================================================


class TestWebhookStatusListener:
    """Test the internal SagaListener that tracks saga outcomes."""

    async def test_on_saga_complete_tracked(self):
        """Lines 48-53: on_saga_complete updates tracking dict."""
        _webhook_tracking["corr-1"] = {
            "status": "triggered",
            "saga_ids": ["saga-xyz"],
            "source": "orders",
        }
        _saga_to_webhook["saga-xyz"] = "corr-1"

        listener = _WebhookStatusListener()
        await listener.on_saga_complete("order_saga", "saga-xyz", {})

        assert _webhook_tracking["corr-1"]["saga_statuses"]["saga-xyz"] == "completed"

    async def test_on_saga_complete_existing_saga_statuses(self):
        """Line 51->53: Branch where saga_statuses ALREADY exists."""
        _webhook_tracking["corr-exist"] = {
            "status": "triggered",
            "saga_ids": ["saga-a", "saga-b"],
            "source": "orders",
            "saga_statuses": {"saga-a": "completed"},  # already has saga_statuses
        }
        _saga_to_webhook["saga-b"] = "corr-exist"

        listener = _WebhookStatusListener()
        await listener.on_saga_complete("order_saga", "saga-b", {})

        # saga_b should now be marked completed too
        assert _webhook_tracking["corr-exist"]["saga_statuses"]["saga-b"] == "completed"

    async def test_on_saga_complete_noop_when_not_tracked(self):
        """Lines 48-53: on_saga_complete is a noop if saga_id unknown."""
        listener = _WebhookStatusListener()
        await listener.on_saga_complete("order_saga", "unknown-saga-id", {})  # no error

    async def test_on_saga_failed_tracked(self):
        """Lines 59-68: on_saga_failed updates tracking dict."""
        _webhook_tracking["corr-2"] = {
            "status": "triggered",
            "saga_ids": ["saga-abc"],
            "source": "payments",
        }
        _saga_to_webhook["saga-abc"] = "corr-2"

        listener = _WebhookStatusListener()
        await listener.on_saga_failed("payment_saga", "saga-abc", {}, RuntimeError("oops"))

        assert _webhook_tracking["corr-2"]["saga_statuses"]["saga-abc"] == "failed"
        assert "oops" in _webhook_tracking["corr-2"]["saga_errors"]["saga-abc"]

    async def test_on_saga_failed_existing_saga_statuses(self):
        """Line 62->64: Branch where saga_statuses ALREADY exists."""
        _webhook_tracking["corr-fail-exist"] = {
            "status": "triggered",
            "saga_ids": ["saga-p", "saga-q"],
            "source": "payments",
            "saga_statuses": {"saga-p": "failed"},  # already populated
        }
        _saga_to_webhook["saga-q"] = "corr-fail-exist"

        listener = _WebhookStatusListener()
        await listener.on_saga_failed("payment_saga", "saga-q", {}, RuntimeError("err"))

        assert _webhook_tracking["corr-fail-exist"]["saga_statuses"]["saga-q"] == "failed"

    async def test_on_saga_failed_noop_when_not_tracked(self):
        """Lines 59-68: on_saga_failed is a noop if saga_id unknown."""
        listener = _WebhookStatusListener()
        await listener.on_saga_failed("payment_saga", "unknown", {}, RuntimeError("x"))


# =============================================================================
# POST /{source} - basic accepted flow
# =============================================================================


class TestWebhookHandlerAccepted:
    """Lines 162-278: The accepted (202) path."""

    async def test_webhook_returns_202_and_sets_queued(self):
        """Line 190: accepted path and status 202."""
        app = _make_app()
        with patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire:
            mock_fire.return_value = []
            response = await _post(app, "/webhooks/test-event", json={"key": "value"})

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["source"] == "test-event"
        assert "correlation_id" in data

    async def test_webhook_background_sets_triggered(self):
        """Lines 198-278: Background task executes and updates status."""
        app = _make_app()
        saga_id = "saga-abc-123"

        with patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire:
            mock_fire.return_value = [saga_id]
            response = await _post(app, "/webhooks/payments", json={"amount": 100})

        assert response.status_code == 202
        corr_id = response.json()["correlation_id"]
        status = get_webhook_status(corr_id)
        assert status is not None
        assert status["status"] in ("triggered", "processing", "failed")

    async def test_webhook_uses_x_correlation_id_header(self):
        """Test that X-Correlation-ID header is used when present."""
        app = _make_app()
        custom_corr_id = "my-custom-correlation-id"

        with patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire:
            mock_fire.return_value = []
            response = await _post(
                app,
                "/webhooks/orders",
                json={"order_id": "123"},
                headers={"X-Correlation-ID": custom_corr_id},
            )

        assert response.status_code == 202
        assert response.json()["correlation_id"] == custom_corr_id

    async def test_webhook_background_error_sets_failed(self):
        """Lines 259-262: When fire_event raises, status becomes failed."""
        app = _make_app()

        with patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire:
            mock_fire.side_effect = RuntimeError("broker down")
            response = await _post(app, "/webhooks/events", json={"key": "value"})

        assert response.status_code == 202
        corr_id = response.json()["correlation_id"]
        status = get_webhook_status(corr_id)
        assert status is not None
        assert status["status"] == "failed"
        assert "broker down" in status["error"]

    async def test_webhook_empty_body_defaults_to_empty_dict(self):
        """Lines 165-168: Invalid JSON body defaults to empty dict."""
        app = _make_app()
        with patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire:
            mock_fire.return_value = []
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/test",
                    content="not valid json",
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 202


# =============================================================================
# POST /{source} - idempotency key missing (400)
# =============================================================================


class TestWebhookHandlerIdempotencyMissing:
    """Lines 162-185: The idempotency key validation path."""

    async def test_missing_idempotency_key_returns_400(self):
        """Lines 178-185: When required idempotency key missing, return 400."""
        from sagaz import Saga, action
        from sagaz.core.triggers import trigger
        from sagaz.core.triggers.registry import TriggerRegistry

        TriggerRegistry.clear()

        class PaymentSaga(Saga):
            saga_name = "payment"

            @trigger(source="payment-events", idempotency_key="payment_id")
            def on_payment(self, payload):
                return payload

            @action("process")
            async def process(self, ctx):
                return {}

        app = _make_app()
        try:
            response = await _post(
                app,
                "/webhooks/payment-events",
                json={"amount": 100, "currency": "USD"},
            )
            assert response.status_code == 400
            data = response.json()
            assert data["status"] == "rejected"
            assert data["error"] == "missing_idempotency_key"
            assert "payment_id" in data["message"]
        finally:
            TriggerRegistry.clear()

    async def test_idempotency_key_present_returns_202(self):
        """Lines 162+: When idempotency key is present, proceed normally."""
        from sagaz import Saga, action
        from sagaz.core.triggers import trigger
        from sagaz.core.triggers.registry import TriggerRegistry

        TriggerRegistry.clear()

        class OrderSaga(Saga):
            saga_name = "order"

            @trigger(source="order-events", idempotency_key="order_id")
            def on_order(self, payload):
                return payload

            @action("process")
            async def process(self, ctx):
                return {}

        app = _make_app()
        try:
            with patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire:
                mock_fire.return_value = []
                response = await _post(
                    app,
                    "/webhooks/order-events",
                    json={"order_id": "ord-123", "amount": 100},
                )
            assert response.status_code == 202
        finally:
            TriggerRegistry.clear()

    async def test_trigger_without_idempotency_key_proceeds(self):
        """Line 183->181: trigger has no idempotency_key → skip idempotency check."""
        from sagaz import Saga, action
        from sagaz.core.triggers import trigger
        from sagaz.core.triggers.registry import TriggerRegistry

        TriggerRegistry.clear()

        class SimpleSaga(Saga):
            saga_name = "simple"

            @trigger(source="simple-events")  # no idempotency_key
            def on_event(self, payload):
                return payload

            @action("process")
            async def process(self, ctx):
                return {}

        app = _make_app()
        try:
            with patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire:
                mock_fire.return_value = []
                response = await _post(
                    app,
                    "/webhooks/simple-events",
                    json={"any": "data"},
                )
            assert response.status_code == 202
        finally:
            TriggerRegistry.clear()


# =============================================================================
# GET /{source}/status/{correlation_id} - all branches (lines 295-366)
# =============================================================================


class TestWebhookStatusHandler:
    """Lines 295-366: All status computation branches."""

    async def test_status_not_found_returns_404(self):
        """Lines 295, 297-298: Unknown correlation_id → 404."""
        app = _make_app()
        response = await _get(app, "/webhooks/orders/status/unknown-correlation-id")

        assert response.status_code == 404
        data = response.json()
        assert data["status"] == "not_found"

    async def test_status_queued(self):
        """Lines 314+: queued status message."""
        _webhook_tracking["corr-queued"] = {
            "status": "queued",
            "saga_ids": [],
            "source": "orders",
        }
        app = _make_app()
        response = await _get(app, "/webhooks/orders/status/corr-queued")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert "queued" in data["message"].lower()

    async def test_status_processing(self):
        """Lines 315+: processing status message."""
        _webhook_tracking["corr-proc"] = {
            "status": "processing",
            "saga_ids": [],
            "source": "orders",
        }
        app = _make_app()
        response = await _get(app, "/webhooks/orders/status/corr-proc")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
        assert "processed" in data["message"].lower()

    async def test_status_triggered_with_pending_sagas(self):
        """Lines 309-311: triggered but sagas not yet done → stays triggered."""
        _webhook_tracking["corr-trig"] = {
            "status": "triggered",
            "saga_ids": ["saga-1", "saga-2"],
            "source": "payments",
        }
        app = _make_app()
        response = await _get(app, "/webhooks/payments/status/corr-trig")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "triggered"
        assert "triggered" in data["message"].lower()

    async def test_status_triggered_all_completed(self):
        """Lines 318-322: triggered + all sagas completed → overall completed."""
        _webhook_tracking["corr-comp"] = {
            "status": "triggered",
            "saga_ids": ["saga-1", "saga-2"],
            "source": "orders",
            "saga_statuses": {"saga-1": "completed", "saga-2": "completed"},
        }
        app = _make_app()
        response = await _get(app, "/webhooks/orders/status/corr-comp")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "completed successfully" in data["message"].lower()

    async def test_status_triggered_all_failed(self):
        """Lines 316-317: triggered + all sagas failed → overall failed."""
        _webhook_tracking["corr-fail"] = {
            "status": "triggered",
            "saga_ids": ["saga-1"],
            "source": "payments",
            "saga_statuses": {"saga-1": "failed"},
        }
        app = _make_app()
        response = await _get(app, "/webhooks/payments/status/corr-fail")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"

    async def test_status_triggered_partial_failures(self):
        """Lines 318-319: triggered + some failed → completed_with_failures."""
        _webhook_tracking["corr-mixed"] = {
            "status": "triggered",
            "saga_ids": ["saga-1", "saga-2"],
            "source": "batch",
            "saga_statuses": {"saga-1": "completed", "saga-2": "failed"},
        }
        app = _make_app()
        response = await _get(app, "/webhooks/batch/status/corr-mixed")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed_with_failures"
        assert "failed" in data["message"].lower()

    async def test_status_with_saga_errors_in_response(self):
        """Lines 337-338: saga_errors included in response when present."""
        _webhook_tracking["corr-err"] = {
            "status": "triggered",
            "saga_ids": ["saga-1"],
            "source": "orders",
            "saga_statuses": {"saga-1": "failed"},
            "saga_errors": {"saga-1": "Payment declined"},
        }
        app = _make_app()
        response = await _get(app, "/webhooks/orders/status/corr-err")

        assert response.status_code == 200
        data = response.json()
        assert "saga_errors" in data
        assert data["saga_errors"]["saga-1"] == "Payment declined"

    async def test_status_with_general_error(self):
        """Lines 340-341: general error included in response."""
        _webhook_tracking["corr-gen-err"] = {
            "status": "failed",
            "saga_ids": [],
            "source": "events",
            "error": "broker connection refused",
        }
        app = _make_app()
        response = await _get(app, "/webhooks/events/status/corr-gen-err")

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"] == "broker connection refused"

    async def test_status_with_saga_statuses_in_response(self):
        """Lines 333-335: saga_statuses dict included when present."""
        _webhook_tracking["corr-statuses"] = {
            "status": "triggered",
            "saga_ids": ["saga-1", "saga-2"],
            "source": "events",
            "saga_statuses": {"saga-1": "completed", "saga-2": "completed"},
        }
        app = _make_app()
        response = await _get(app, "/webhooks/events/status/corr-statuses")

        assert response.status_code == 200
        data = response.json()
        assert "saga_statuses" in data

    async def test_status_failed_single_saga_message(self):
        """Lines 355-356: failed message for single saga."""
        _webhook_tracking["corr-single-fail"] = {
            "status": "triggered",
            "saga_ids": ["saga-1"],
            "source": "orders",
            "saga_statuses": {"saga-1": "failed"},
        }
        app = _make_app()
        response = await _get(app, "/webhooks/orders/status/corr-single-fail")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "failed" in data["message"].lower()

    async def test_status_failed_multiple_sagas_message(self):
        """Lines 358-360: failed message for multiple sagas."""
        _webhook_tracking["corr-multi-fail"] = {
            "status": "triggered",
            "saga_ids": ["saga-1", "saga-2"],
            "source": "orders",
            "saga_statuses": {"saga-1": "failed", "saga-2": "failed"},
        }
        app = _make_app()
        response = await _get(app, "/webhooks/orders/status/corr-multi-fail")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"

    async def test_status_completed_directly(self):
        """Status directly set to completed."""
        _webhook_tracking["corr-direct-comp"] = {
            "status": "completed",
            "saga_ids": ["saga-1"],
            "source": "orders",
        }
        app = _make_app()
        response = await _get(app, "/webhooks/orders/status/corr-direct-comp")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    async def test_status_unknown_falls_through_elif_chain(self):
        """Line 360->366: An unknown status string falls through all elif branches."""
        _webhook_tracking["corr-unknown"] = {
            "status": "unexpected_custom_status",
            "saga_ids": [],
            "source": "orders",
        }
        app = _make_app()
        response = await _get(app, "/webhooks/orders/status/corr-unknown")

        assert response.status_code == 200
        data = response.json()
        # Should return the status even without a message
        assert data["status"] == "unexpected_custom_status"


# =============================================================================
# Background task with storage lookup (lines 224-252)
# =============================================================================


class TestWebhookBackgroundStorageLookup:
    """Lines 224-252: storage lookup for already-existing sagas."""

    async def test_background_checks_storage_for_existing_sagas(self):
        """Lines 224-252: When config.storage exists, check saga state."""
        from sagaz.core.types import SagaStatus

        app = _make_app()
        saga_id = "existing-saga-123"
        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(
            return_value={"status": SagaStatus.COMPLETED, "error": None}
        )
        mock_config = MagicMock()
        mock_config.storage = mock_storage

        with (
            patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire,
            patch("sagaz.core.config.get_config", return_value=mock_config),
        ):
            mock_fire.return_value = [saga_id]
            response = await _post(app, "/webhooks/payments", json={"payment_id": "p-123"})

        assert response.status_code == 202
        corr_id = response.json()["correlation_id"]
        status = get_webhook_status(corr_id)
        assert status is not None

    async def test_background_handles_storage_with_failed_saga(self):
        """Lines 238-248: Saga with FAILED status updates tracking."""
        from sagaz.core.types import SagaStatus

        app = _make_app()
        saga_id = "failed-saga-456"
        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(
            return_value={"status": SagaStatus.FAILED, "error": "payment declined"}
        )
        mock_config = MagicMock()
        mock_config.storage = mock_storage

        with (
            patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire,
            patch("sagaz.core.config.get_config", return_value=mock_config),
        ):
            mock_fire.return_value = [saga_id]
            response = await _post(app, "/webhooks/payments", json={"txn": "t-123"})

        assert response.status_code == 202

    async def test_background_handles_storage_exception_gracefully(self):
        """Lines 250-252: Exception in storage lookup swallowed silently."""
        app = _make_app()
        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(side_effect=RuntimeError("db down"))
        mock_config = MagicMock()
        mock_config.storage = mock_storage

        with (
            patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire,
            patch("sagaz.core.config.get_config", return_value=mock_config),
        ):
            mock_fire.return_value = ["saga-xyz"]
            response = await _post(app, "/webhooks/orders", json={"order": "o-1"})

        assert response.status_code == 202

    async def test_background_rolled_back_state(self):
        """Lines 238-248: Saga with ROLLED_BACK status updates tracking."""
        from sagaz.core.types import SagaStatus

        app = _make_app()
        saga_id = "rolledback-saga-789"
        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(
            return_value={"status": SagaStatus.ROLLED_BACK, "error": "rolled back"}
        )
        mock_config = MagicMock()
        mock_config.storage = mock_storage

        with (
            patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire,
            patch("sagaz.core.config.get_config", return_value=mock_config),
        ):
            mock_fire.return_value = [saga_id]
            response = await _post(app, "/webhooks/refunds", json={"ref": "r-1"})

        assert response.status_code == 202

    async def test_background_executing_state_no_status_update(self):
        """Line 255->240: State is EXECUTING (not COMPLETED/FAILED) → no status update."""
        from sagaz.core.types import SagaStatus

        app = _make_app()
        saga_id = "executing-saga"
        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(
            return_value={"status": SagaStatus.EXECUTING, "error": None}
        )
        mock_config = MagicMock()
        mock_config.storage = mock_storage

        with (
            patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire,
            patch("sagaz.core.config.get_config", return_value=mock_config),
        ):
            mock_fire.return_value = [saga_id]
            response = await _post(app, "/webhooks/orders", json={"oid": "x-1"})

        assert response.status_code == 202

    async def test_background_state_is_none(self):
        """Line 243->245 False: state is None → skip status update."""
        app = _make_app()
        saga_id = "none-state-saga"
        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(return_value=None)
        mock_config = MagicMock()
        mock_config.storage = mock_storage

        with (
            patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire,
            patch("sagaz.core.config.get_config", return_value=mock_config),
        ):
            mock_fire.return_value = [saga_id]
            response = await _post(app, "/webhooks/orders", json={"oid": "y-2"})

        assert response.status_code == 202

    async def test_background_failed_without_error_field(self):
        """Line 259->240: Failed saga but state has no 'error' field."""
        from sagaz.core.types import SagaStatus

        app = _make_app()
        saga_id = "failed-no-error"
        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(
            return_value={"status": SagaStatus.FAILED, "error": None}
        )
        mock_config = MagicMock()
        mock_config.storage = mock_storage

        with (
            patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire,
            patch("sagaz.core.config.get_config", return_value=mock_config),
        ):
            mock_fire.return_value = [saga_id]
            response = await _post(app, "/webhooks/payments", json={"txn": "t-99"})

        assert response.status_code == 202

    async def test_background_existing_saga_statuses_key(self):
        """Line 245->248: saga_statuses already in tracking when processing next saga."""
        from sagaz.core.types import SagaStatus

        app = _make_app()
        saga_id_1 = "saga-first"
        saga_id_2 = "saga-second"

        async def mock_load(sid):
            return {"status": SagaStatus.COMPLETED, "error": None}

        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(side_effect=mock_load)
        mock_config = MagicMock()
        mock_config.storage = mock_storage

        with (
            patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire,
            patch("sagaz.core.config.get_config", return_value=mock_config),
        ):
            mock_fire.return_value = [saga_id_1, saga_id_2]
            response = await _post(app, "/webhooks/orders", json={"batch": "b-1"})

        assert response.status_code == 202

    async def test_background_failed_with_existing_saga_errors(self):
        """Line 260->262: saga_errors already in tracking when second saga fails."""
        from sagaz.core.types import SagaStatus

        app = _make_app()
        saga_id_1 = "fail-first"
        saga_id_2 = "fail-second"

        async def mock_load(sid):
            return {"status": SagaStatus.FAILED, "error": f"error for {sid}"}

        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(side_effect=mock_load)
        mock_config = MagicMock()
        mock_config.storage = mock_storage

        with (
            patch("sagaz.core.triggers.fire_event", new_callable=AsyncMock) as mock_fire,
            patch("sagaz.core.config.get_config", return_value=mock_config),
        ):
            mock_fire.return_value = [saga_id_1, saga_id_2]
            response = await _post(app, "/webhooks/payments", json={"multi": "m-1"})

        assert response.status_code == 202
