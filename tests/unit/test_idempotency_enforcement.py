"""
Tests for idempotency warnings in triggers.

Tests verify that triggers WITHOUT idempotency_key emit warnings,
but still execute successfully. The library is now agnostic and
warns users rather than enforcing business rules.
"""

import pytest

from sagaz import Saga, action, compensate
from sagaz.triggers import fire_event, trigger
from sagaz.triggers.registry import TriggerRegistry


@pytest.fixture(autouse=True)
def _clear_registry():
    """Clear trigger registry before each test."""
    TriggerRegistry.clear()
    yield
    TriggerRegistry.clear()


class TestIdempotencyWarnings:
    """Test that idempotency warnings are emitted when keys are missing."""

    @pytest.mark.asyncio
    async def test_without_idempotency_emits_warning(self, caplog):
        """Triggers without idempotency_key should emit warning but execute."""

        class PaymentSaga(Saga):
            saga_name = "payment-saga"

            @trigger(source="payment_requested")
            def on_payment(self, event: dict) -> dict:
                return {
                    "order_id": event["order_id"],
                    "amount": event["amount"],
                }

            @action("process_payment")
            async def process_payment(self, ctx: dict) -> dict:
                return {"status": "success"}

            @compensate("process_payment")
            async def refund(self, ctx: dict) -> None:
                pass

        # Should execute successfully despite missing idempotency_key
        saga_ids = await fire_event("payment_requested", {"order_id": "ORD-001", "amount": 150.0})
        assert len(saga_ids) == 1

        # But should have logged a warning
        assert "IDEMPOTENCY WARNING" in caplog.text
        assert "PaymentSaga.on_payment" in caplog.text
        assert "payment_requested" in caplog.text

    @pytest.mark.asyncio
    async def test_financial_field_without_idempotency_warns(self, caplog):
        """Financial field triggers should warn but still execute."""

        class RefundSaga(Saga):
            saga_name = "refund-saga"

            @trigger(source="refund_requested")
            def on_refund(self, event: dict) -> dict:
                return {
                    "transaction_id": event["txn_id"],
                    "refund_amount": 50.0,
                }

            @action("process_refund")
            async def process_refund(self, ctx: dict) -> dict:
                return {"status": "success"}

            @compensate("process_refund")
            async def undo_refund(self, ctx: dict) -> None:
                pass

        # Should execute successfully
        saga_ids = await fire_event("refund_requested", {"txn_id": "TXN-001"})
        assert len(saga_ids) == 1

        # But should warn
        assert "IDEMPOTENCY WARNING" in caplog.text

    @pytest.mark.asyncio
    async def test_with_idempotency_key_no_warning(self, caplog):
        """Operation with idempotency_key should succeed without warning."""

        class SafePaymentSaga(Saga):
            saga_name = "safe-payment"

            @trigger(source="payment_requested", idempotency_key="order_id")
            def on_payment(self, event: dict) -> dict:
                return {
                    "order_id": event["order_id"],
                    "amount": event["amount"],
                }

            @action("process_payment")
            async def process_payment(self, ctx: dict) -> dict:
                return {"status": "success"}

            @compensate("process_payment")
            async def refund(self, ctx: dict) -> None:
                pass

        # Should succeed because idempotency_key is configured
        saga_ids = await fire_event("payment_requested", {"order_id": "ORD-001", "amount": 150.0})
        assert len(saga_ids) == 1

        # Should NOT have warning
        assert "IDEMPOTENCY WARNING" not in caplog.text

    @pytest.mark.asyncio
    async def test_low_value_without_financial_fields_warns(self, caplog):
        """Even low-value operations warn without idempotency (library agnostic)."""

        class NotificationSaga(Saga):
            saga_name = "notification"

            @trigger(source="user_login")
            def on_login(self, event: dict) -> dict:
                return {
                    "user_id": event["user_id"],
                    "timestamp": event["timestamp"],
                }

            @action("send_notification")
            async def send_notification(self, ctx: dict) -> dict:
                return {"sent": True}

            @compensate("send_notification")
            async def cancel_notification(self, ctx: dict) -> None:
                pass

        # Should succeed - library doesn't enforce business rules
        saga_ids = await fire_event("user_login", {"user_id": "U123", "timestamp": "2026-01-10"})
        assert len(saga_ids) == 1

        # But should still warn (consistent warning for all triggers)
        assert "IDEMPOTENCY WARNING" in caplog.text

    @pytest.mark.asyncio
    async def test_callable_idempotency_key_no_warning(self, caplog):
        """Callable idempotency_key should work without warnings."""

        class OrderSaga(Saga):
            saga_name = "order"

            @trigger(
                source="order_placed",
                idempotency_key=lambda event: f"{event['user_id']}-{event['order_id']}",
            )
            def on_order(self, event: dict) -> dict:
                return {
                    "user_id": event["user_id"],
                    "order_id": event["order_id"],
                    "price": event["price"],
                }

            @action("charge")
            async def charge(self, ctx: dict) -> dict:
                return {"charged": True}

            @compensate("charge")
            async def refund(self, ctx: dict) -> None:
                pass

        # Should succeed with callable idempotency_key
        saga_ids = await fire_event(
            "order_placed", {"user_id": "U123", "order_id": "ORD-001", "price": 250.0}
        )
        assert len(saga_ids) == 1

        # No warning
        assert "IDEMPOTENCY WARNING" not in caplog.text

    @pytest.mark.asyncio
    async def test_warning_message_format(self, caplog):
        """Verify warning message contains helpful guidance."""

        class TestSaga(Saga):
            saga_name = "test-payment"

            @trigger(source="test_event")
            def on_event(self, event: dict) -> dict:
                return {"amount": 500.0, "payment_id": "PAY-001"}

            @action("test")
            async def test_action(self, ctx: dict) -> dict:
                return {}

            @compensate("test")
            async def test_comp(self, ctx: dict) -> None:
                pass

        saga_ids = await fire_event("test_event", {})
        assert len(saga_ids) == 1

        # Verify helpful content in warning message
        assert "IDEMPOTENCY WARNING" in caplog.text
        assert "TestSaga.on_event" in caplog.text
        assert "test_event" in caplog.text
        assert "idempotency_key" in caplog.text


class TestIdempotencyKeyMissing:
    """Test that missing idempotency keys in payload raise errors."""

    @pytest.mark.asyncio
    async def test_missing_idempotency_field_raises_error(self):
        """When trigger has idempotency_key but payload lacks it, should raise."""
        from sagaz.core.exceptions import IdempotencyKeyMissingInPayloadError

        class OrderSaga(Saga):
            saga_name = "order"

            @trigger(source="order_placed", idempotency_key="order_id")
            def on_order(self, event: dict) -> dict:
                return {
                    "user_id": event.get("user_id", "unknown"),
                    "amount": event.get("amount", 0),
                }

            @action("process")
            async def process(self, ctx: dict) -> dict:
                return {}

            @compensate("process")
            async def undo(self, ctx: dict) -> None:
                pass

        # Payload missing 'order_id' field
        with pytest.raises(IdempotencyKeyMissingInPayloadError) as exc_info:
            await fire_event("order_placed", {"user_id": "U123", "amount": 100.0})

        # Verify error details
        assert "order_id" in str(exc_info.value)
        assert "OrderSaga" in str(exc_info.value)
        assert "user_id, amount" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_field_with_callable_raises_error(self):
        """Callable idempotency_key that returns None should raise."""
        from sagaz.core.exceptions import IdempotencyKeyMissingInPayloadError

        class PaymentSaga(Saga):
            saga_name = "payment"

            @trigger(
                source="payment_requested",
                idempotency_key=lambda e: e.get("transaction_id"),  # Returns None if missing
            )
            def on_payment(self, event: dict) -> dict:
                return {"amount": event["amount"]}

            @action("charge")
            async def charge(self, ctx: dict) -> dict:
                return {}

            @compensate("charge")
            async def refund(self, ctx: dict) -> None:
                pass

        # Payload missing 'transaction_id' field
        with pytest.raises(IdempotencyKeyMissingInPayloadError) as exc_info:
            await fire_event("payment_requested", {"amount": 50.0})

        # Should mention callable
        assert "<callable>" in str(exc_info.value)
        assert "PaymentSaga" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_payload_with_idempotency_raises_error(self):
        """Empty payload with idempotency_key should raise."""
        from sagaz.core.exceptions import IdempotencyKeyMissingInPayloadError

        class RefundSaga(Saga):
            saga_name = "refund"

            @trigger(source="refund_requested", idempotency_key="refund_id")
            def on_refund(self, event: dict) -> dict | None:
                return {"status": "pending"}

            @action("process_refund")
            async def process_refund(self, ctx: dict) -> dict:
                return {}

            @compensate("process_refund")
            async def undo_refund(self, ctx: dict) -> None:
                pass

        # Empty payload
        with pytest.raises(IdempotencyKeyMissingInPayloadError) as exc_info:
            await fire_event("refund_requested", {})

        assert "refund_id" in str(exc_info.value)
        assert "(empty payload)" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_with_correct_field_succeeds(self):
        """When payload has the idempotency field, should succeed."""

        class OrderSaga(Saga):
            saga_name = "order"

            @trigger(source="order_placed", idempotency_key="order_id")
            def on_order(self, event: dict) -> dict:
                return {
                    "order_id": event["order_id"],
                    "amount": event["amount"],
                }

            @action("process")
            async def process(self, ctx: dict) -> dict:
                return {}

            @compensate("process")
            async def undo(self, ctx: dict) -> None:
                pass

        # Should succeed - payload has order_id
        saga_ids = await fire_event("order_placed", {"order_id": "ORD-123", "amount": 100.0})
        assert len(saga_ids) == 1
