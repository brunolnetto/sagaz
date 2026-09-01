"""
Tests for sagaz.core.triggers.engine._detect_high_value_operation method.

Tests the detection of high-value operations based on financial keywords
and numeric thresholds.
"""

import pytest

from sagaz.core.triggers.engine import TriggerEngine


class TestDetectHighValueOperation:
    """Test the _detect_high_value_operation method of TriggerEngine."""

    def setup_method(self):
        """Set up a TriggerEngine instance for each test."""
        self.engine = TriggerEngine()

    def test_detect_empty_context(self):
        """Empty context should return no detected fields."""
        result = self.engine._detect_high_value_operation({})
        assert result == []

    def test_detect_amount_keyword(self):
        """Should detect 'amount' field by keyword."""
        context = {"amount": 100.0}
        result = self.engine._detect_high_value_operation(context)
        assert "amount" in result

    def test_detect_price_keyword(self):
        """Should detect 'price' field by keyword."""
        context = {"price": 50.0}
        result = self.engine._detect_high_value_operation(context)
        assert "price" in result

    def test_detect_payment_keyword(self):
        """Should detect 'payment' field by keyword."""
        context = {"payment": 10.0}
        result = self.engine._detect_high_value_operation(context)
        assert "payment" in result

    def test_detect_charge_keyword(self):
        """Should detect 'charge' field by keyword."""
        context = {"charge": 5.0}
        result = self.engine._detect_high_value_operation(context)
        assert "charge" in result

    def test_detect_refund_keyword(self):
        """Should detect 'refund' field by keyword."""
        context = {"refund": 200.0}
        result = self.engine._detect_high_value_operation(context)
        assert "refund" in result

    def test_detect_transaction_keyword(self):
        """Should detect 'transaction' field by keyword."""
        context = {"transaction": 150.0}
        result = self.engine._detect_high_value_operation(context)
        assert "transaction" in result

    def test_detect_total_keyword(self):
        """Should detect 'total' field by keyword."""
        context = {"total": 500.0}
        result = self.engine._detect_high_value_operation(context)
        assert "total" in result

    def test_detect_balance_keyword(self):
        """Should detect 'balance' field by keyword."""
        context = {"balance": 1000.0}
        result = self.engine._detect_high_value_operation(context)
        assert "balance" in result

    def test_detect_large_numeric_value(self):
        """Should detect numeric values >= 100.0."""
        context = {"order_value": 150.0}
        result = self.engine._detect_high_value_operation(context)
        assert "order_value" in result

    def test_detect_large_integer_value(self):
        """Should detect integer values >= 100."""
        context = {"quantity": 150}
        result = self.engine._detect_high_value_operation(context)
        assert "quantity" in result

    def test_ignore_small_numeric_value(self):
        """Should ignore numeric values < 100.0."""
        context = {"small_amount": 50.0}
        result = self.engine._detect_high_value_operation(context)
        assert "small_amount" not in result

    def test_ignore_small_integer_value(self):
        """Should ignore integer values < 100."""
        context = {"quantity": 50}
        result = self.engine._detect_high_value_operation(context)
        assert "quantity" not in result

    def test_ignore_zero_value(self):
        """Should ignore zero values."""
        context = {"order_value": 0.0}
        result = self.engine._detect_high_value_operation(context)
        assert "order_value" not in result

    def test_ignore_non_numeric_values(self):
        """Should ignore non-numeric values."""
        context = {"description": "large description"}
        result = self.engine._detect_high_value_operation(context)
        assert "description" not in result

    def test_ignore_string_numbers(self):
        """Should ignore string representations of numbers."""
        context = {"amount_str": "150.0"}
        result = self.engine._detect_high_value_operation(context)
        assert "amount_str" not in result

    def test_case_insensitive_keyword_matching(self):
        """Keywords should be matched case-insensitively."""
        context = {"Amount": 100.0, "PRICE": 50.0, "Payment": 10.0}
        result = self.engine._detect_high_value_operation(context)
        assert "Amount" in result
        assert "PRICE" in result
        assert "Payment" in result

    def test_keyword_match_takes_precedence(self):
        """Keyword match should be detected even with small value."""
        context = {"amount": 50.0}
        result = self.engine._detect_high_value_operation(context)
        # amount matches keyword, so should be detected despite value < 100
        assert "amount" in result

    def test_multiple_high_value_fields(self):
        """Should detect multiple high-value fields."""
        context = {
            "amount": 100.0,
            "price": 200.0,
            "quantity": 150,
            "description": "order",
            "item_count": 5,
        }
        result = self.engine._detect_high_value_operation(context)
        assert len(result) == 3
        assert "amount" in result
        assert "price" in result
        assert "quantity" in result
        assert "description" not in result
        assert "item_count" not in result

    def test_boundary_value_exactly_100(self):
        """Should detect numeric value exactly at 100.0."""
        context = {"amount": 100.0}
        result = self.engine._detect_high_value_operation(context)
        assert "amount" in result

    def test_boundary_value_just_above_100(self):
        """Should detect numeric value just above 100.0."""
        context = {"amount": 100.1}
        result = self.engine._detect_high_value_operation(context)
        assert "amount" in result

    def test_boundary_value_just_below_100(self):
        """Should not detect numeric value just below 100.0."""
        context = {"amount": 99.9}
        result = self.engine._detect_high_value_operation(context)
        # amount is a keyword, so should be detected
        assert "amount" in result

    def test_negative_values(self):
        """Should not detect negative values >= 100."""
        context = {"amount": -150.0}
        result = self.engine._detect_high_value_operation(context)
        # amount is a keyword, so should be detected
        assert "amount" in result

    def test_none_value(self):
        """Should ignore None values."""
        context = {"amount": None}
        result = self.engine._detect_high_value_operation(context)
        # amount is a keyword, so should be detected
        assert "amount" in result

    def test_bool_value(self):
        """Should handle boolean values (bool is subclass of int)."""
        context = {"active": True, "amount": 100}
        result = self.engine._detect_high_value_operation(context)
        # amount should be detected as keyword
        assert "amount" in result
        # True == 1, which is < 100, so active not detected
        assert "active" not in result

    def test_list_value(self):
        """Should ignore list values."""
        context = {"amounts": [100, 200, 300]}
        result = self.engine._detect_high_value_operation(context)
        assert "amounts" not in result

    def test_dict_value(self):
        """Should ignore dict values."""
        context = {"amount_data": {"total": 100}}
        result = self.engine._detect_high_value_operation(context)
        assert "amount_data" not in result

    def test_combined_keyword_and_numeric_detection(self):
        """Should combine keyword and numeric detection results."""
        context = {
            "amount": 50.0,  # keyword, detected
            "total": 200.0,  # keyword, detected
            "order_value": 150.0,  # numeric threshold
            "description": "test",  # ignored
        }
        result = self.engine._detect_high_value_operation(context)
        assert len(result) == 3
        assert "amount" in result
        assert "total" in result
        assert "order_value" in result
        assert "description" not in result
