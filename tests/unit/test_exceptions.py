"""
Additional tests for sagaz.core.exceptions to improve coverage
"""

import pytest

from sagaz.core.exceptions import (
    IdempotencyKeyMissingInPayloadError,
    IdempotencyKeyRequiredError,
    MissingDependencyError,
    SagaCompensationError,
    SagaDependencyError,
    SagaError,
    SagaExecutionError,
    SagaStepError,
    SagaTimeoutError,
)


class TestExceptionConstructors:
    """Test exception constructors and message formatting"""

    def test_saga_error_basic(self):
        """Test SagaError base exception"""
        error = SagaError("test message")
        assert str(error) == "test message"
        assert isinstance(error, Exception)

    def test_saga_execution_error(self):
        """Test SagaExecutionError"""
        error = SagaExecutionError("execution failed")
        assert "execution failed" in str(error)

    def test_saga_step_error(self):
        """Test SagaStepError"""
        error = SagaStepError("step failed")
        assert "step failed" in str(error)

    def test_saga_compensation_error(self):
        """Test SagaCompensationError"""
        error = SagaCompensationError("compensation failed")
        assert "compensation failed" in str(error)

    def test_saga_timeout_error(self):
        """Test SagaTimeoutError"""
        error = SagaTimeoutError("operation timed out")
        assert "timed out" in str(error)

    def test_saga_dependency_error(self):
        """Test SagaDependencyError"""
        error = SagaDependencyError("circular dependency detected")
        assert "circular dependency" in str(error)
        assert isinstance(error, SagaError)

    def test_missing_dependency_error(self):
        """Test MissingDependencyError with details"""
        error = MissingDependencyError("asyncpg", "PostgreSQL storage")
        assert "asyncpg" in str(error)

    def test_missing_dependency_error_install_commands(self):
        """Test MissingDependencyError has install commands"""
        error = MissingDependencyError("redis")
        assert hasattr(error, "package")
        assert error.package == "redis"
        assert "redis" in MissingDependencyError.INSTALL_COMMANDS

    def test_idempotency_key_required_error(self):
        """Test IdempotencyKeyRequiredError formats nicely"""
        error = IdempotencyKeyRequiredError(
            saga_name="PaymentSaga", source="webhook", detected_fields=["amount", "user_id"]
        )
        message = str(error)
        assert "PaymentSaga" in message
        assert "webhook" in message

    def test_idempotency_key_missing_in_payload_error(self):
        """Test IdempotencyKeyMissingInPayloadError"""
        error = IdempotencyKeyMissingInPayloadError(
            saga_name="OrderSaga",
            source="api",
            key_name="order_id",
            payload_keys=["user_id", "amount"],
        )
        message = str(error)
        assert "OrderSaga" in message
        assert "order_id" in message

    def test_exception_inheritance(self):
        """Test exception inheritance hierarchy"""
        assert issubclass(SagaExecutionError, SagaError)
        assert issubclass(SagaStepError, SagaError)
        assert issubclass(SagaCompensationError, SagaError)
        assert issubclass(SagaTimeoutError, SagaError)
        assert issubclass(SagaDependencyError, SagaError)

    def test_idempotency_error_formatting(self):
        """Test IdempotencyKeyRequiredError has nice formatting"""
        error = IdempotencyKeyRequiredError(
            saga_name="OrderSaga",
            source="api",
            detected_fields=["order_id", "customer_id", "total"],
        )
        message = str(error)
        # Check for box drawing characters
        assert "╔" in message or "=" in message
        assert "OrderSaga" in message
        assert "api" in message

    def test_missing_dependency_error_with_feature(self):
        """Test MissingDependencyError with feature description"""
        error = MissingDependencyError("opentelemetry", "Distributed tracing")
        message = str(error)
        assert "opentelemetry" in message.lower()

    def test_missing_dependency_error_without_feature(self):
        """Test MissingDependencyError without feature"""
        error = MissingDependencyError("asyncpg")
        message = str(error)
        assert "asyncpg" in message.lower()
