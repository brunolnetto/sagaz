"""
Tests for idempotency key enforcement in triggers.
"""

import pytest

from sagaz import Saga, action, compensate
from sagaz.core.exceptions import IdempotencyKeyRequiredError
from sagaz.triggers import fire_event, trigger
from sagaz.triggers.registry import TriggerRegistry


@pytest.fixture(autouse=True)
def _clear_registry():
    """Clear trigger registry before each test."""
    TriggerRegistry.clear()
    yield
    TriggerRegistry.clear()


class TestIdempotencyEnforcement:
    """Test that idempotency keys are enforced for high-value operations."""

    @pytest.mark.asyncio
    async def test_high_value_without_idempotency_raises(self):
        """High-value operation without idempotency_key should raise."""

        class PaymentSaga(Saga):
            saga_name = "payment-saga"

            @trigger(source="payment_requested")
            def on_payment(self, event: dict) -> dict:
                return {
                    "order_id": event["order_id"],
                    "amount": event["amount"],  # Financial field
                }

            @action("process_payment")
            async def process_payment(self, ctx: dict) -> dict:
                return {"status": "success"}

            @compensate("process_payment")
            async def refund(self, ctx: dict) -> None:
                pass

        # Fire event with high amount (>= 100.0 threshold)
        with pytest.raises(IdempotencyKeyRequiredError) as exc_info:
            await fire_event("payment_requested", {"order_id": "ORD-001", "amount": 150.0})

        # Verify error details
        error = exc_info.value
        assert error.saga_name == "PaymentSaga"
        assert error.source == "payment_requested"
        assert "amount" in error.detected_fields

    @pytest.mark.asyncio
    async def test_financial_field_without_idempotency_raises(self):
        """Financial field names should trigger enforcement."""

        class RefundSaga(Saga):
            saga_name = "refund-saga"

            @trigger(source="refund_requested")
            def on_refund(self, event: dict) -> dict:
                return {
                    "transaction_id": event["txn_id"],
                    "refund_amount": 50.0,  # "refund" is a financial indicator
                }

            @action("process_refund")
            async def process_refund(self, ctx: dict) -> dict:
                return {"status": "success"}

            @compensate("process_refund")
            async def undo_refund(self, ctx: dict) -> None:
                pass

        # Should raise even with amount < 100 because of "refund" keyword
        with pytest.raises(IdempotencyKeyRequiredError) as exc_info:
            await fire_event("refund_requested", {"txn_id": "TXN-001"})

        assert exc_info.value.saga_name == "RefundSaga"
        assert "refund_amount" in exc_info.value.detected_fields

    @pytest.mark.asyncio
    async def test_with_idempotency_key_succeeds(self):
        """Operation with idempotency_key should succeed."""

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

    @pytest.mark.asyncio
    async def test_low_value_without_financial_fields_succeeds(self):
        """Low-value operations without financial fields don't need idempotency."""

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

        # Should succeed - no financial fields or high values
        saga_ids = await fire_event("user_login", {"user_id": "U123", "timestamp": "2026-01-10"})
        assert len(saga_ids) == 1

    @pytest.mark.asyncio
    async def test_callable_idempotency_key(self):
        """Callable idempotency_key should work for high-value operations."""

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

    @pytest.mark.asyncio
    async def test_error_message_format(self):
        """Verify error message contains helpful guidance."""

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

        with pytest.raises(IdempotencyKeyRequiredError) as exc_info:
            await fire_event("test_event", {})

        error_msg = str(exc_info.value)
        # Verify helpful content in error message
        assert "IDEMPOTENCY KEY REQUIRED" in error_msg
        assert "test-payment" in error_msg or "TestSaga" in error_msg
        assert "test_event" in error_msg
        assert "@trigger" in error_msg
        assert "idempotency_key" in error_msg

    @pytest.mark.asyncio
    async def test_threshold_boundary(self):
        """Test the high-value threshold (100.0)."""

        class BoundarySaga(Saga):
            @trigger(source="boundary_test")
            def on_event(self, event: dict) -> dict:
                return {"value": event["value"]}

            @action("test")
            async def test_action(self, ctx: dict) -> dict:
                return {}

            @compensate("test")
            async def test_comp(self, ctx: dict) -> None:
                pass

        # Value exactly at threshold should require idempotency
        with pytest.raises(IdempotencyKeyRequiredError):
            await fire_event("boundary_test", {"value": 100.0})

        # Value just below threshold should not require idempotency
        saga_ids = await fire_event("boundary_test", {"value": 99.99})
        assert len(saga_ids) == 1

    @pytest.mark.asyncio
    async def test_multiple_financial_indicators(self):
        """Test detection of multiple financial field types."""

        class MultiFinancialSaga(Saga):
            @trigger(source="multi_test")
            def on_event(self, event: dict) -> dict:
                return {
                    "transaction_id": event["txn"],
                    "charge_amount": 50.0,
                    "refund_pending": True,
                }

            @action("test")
            async def test_action(self, ctx: dict) -> dict:
                return {}

            @compensate("test")
            async def test_comp(self, ctx: dict) -> None:
                pass

        with pytest.raises(IdempotencyKeyRequiredError) as exc_info:
            await fire_event("multi_test", {"txn": "TXN-001"})

        # Should detect multiple financial fields
        error = exc_info.value
        detected = set(error.detected_fields)
        financial_detected = {"charge_amount", "transaction_id", "refund_pending"} & detected
        assert len(financial_detected) > 0  # At least one financial field detected
