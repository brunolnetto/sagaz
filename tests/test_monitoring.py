# ============================================
# FILE: tests/test_monitoring.py
# ============================================

"""
Tests for monitoring modules - logging, tracing, and metrics
"""

import asyncio
import json
import logging
from io import StringIO

import pytest

from sagaz.core import Saga, SagaContext
from sagaz.monitoring.logging import (
    SagaContextFilter,
    SagaJsonFormatter,
    SagaLogger,
    saga_context,
    setup_saga_logging,
)
from sagaz.monitoring.metrics import SagaMetrics
from sagaz.monitoring.tracing import SagaTracer, trace_saga_action, trace_saga_compensation
from sagaz.types import SagaStatus


class TestSagaJsonFormatter:
    """Test SagaJsonFormatter functionality"""

    def test_json_formatter_basic(self):
        """Test JSON formatter produces valid JSON"""
        formatter = SagaJsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed

    def test_json_formatter_with_saga_context(self):
        """Test JSON formatter includes saga context when available"""
        formatter = SagaJsonFormatter()

        # Set saga context
        context = {
            "saga_id": "test-saga-123",
            "saga_name": "TestSaga",
            "step_name": "test-step",
            "correlation_id": "corr-123",
        }
        saga_context.set(context)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        assert parsed["saga_id"] == "test-saga-123"
        assert parsed["saga_name"] == "TestSaga"
        assert parsed["step_name"] == "test-step"
        assert parsed["correlation_id"] == "corr-123"

    def test_json_formatter_with_record_attributes(self):
        """Test JSON formatter includes extra attributes from record"""
        formatter = SagaJsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        # Add extra attributes to record
        record.saga_id = "record-saga-123"
        record.duration_ms = 250.5
        record.retry_count = 2
        record.error_type = "TestError"

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        assert parsed["saga_id"] == "record-saga-123"
        assert parsed["duration_ms"] == 250.5
        assert parsed["retry_count"] == 2
        assert parsed["error_type"] == "TestError"


class TestSagaContextFilter:
    """Test SagaContextFilter functionality"""

    def test_context_filter_adds_saga_fields(self):
        """Test context filter adds saga fields to log records"""
        saga_filter = SagaContextFilter()

        # Set saga context
        context = {
            "saga_id": "test-saga-456",
            "saga_name": "TestSaga",
            "step_name": "filter-test-step",
            "correlation_id": "corr-456",
        }
        saga_context.set(context)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        # Apply filter
        result = saga_filter.filter(record)

        assert result is True
        assert record.saga_id == "test-saga-456"
        assert record.saga_name == "TestSaga"
        assert record.step_name == "filter-test-step"
        assert record.correlation_id == "corr-456"

    def test_context_filter_with_empty_context(self):
        """Test context filter handles empty context gracefully"""
        saga_filter = SagaContextFilter()

        # Clear saga context
        saga_context.set({})

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        result = saga_filter.filter(record)

        assert result is True
        assert record.saga_id == "unknown"
        assert record.saga_name == "unknown"
        assert record.step_name == ""
        assert record.correlation_id == ""


class TestSagaLogger:
    """Tests for SagaLogger"""

    def test_saga_logger_initialization(self):
        """Test SagaLogger initializes correctly"""
        logger = SagaLogger(name="test-saga")

        assert logger.logger.name == "test-saga"
        assert isinstance(logger.logger, logging.Logger)

        # Verify filter was added
        filters = logger.logger.filters
        assert len(filters) > 0
        assert any(isinstance(f, SagaContextFilter) for f in filters)

    def test_saga_logger_context_injection(self):
        """Test SagaLogger sets and uses saga context"""
        logger = SagaLogger(name="context-test")

        # Set saga context
        logger.set_saga_context(
            saga_id="test-123",
            saga_name="TestSaga",
            step_name="test_step",
            correlation_id="corr-456",
        )

        # Context should be set
        from sagaz.monitoring.logging import saga_context

        ctx = saga_context.get()
        assert ctx["saga_id"] == "test-123"
        assert ctx["saga_name"] == "TestSaga"
        assert ctx["step_name"] == "test_step"
        assert ctx["correlation_id"] == "corr-456"

        # Clean up
        logger.clear_saga_context()

    def test_saga_logger_saga_lifecycle(self):
        """Test SagaLogger logs saga lifecycle events"""
        logger = SagaLogger(name="lifecycle-test")

        # Capture log output
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)

        # Test saga started
        logger.saga_started("saga-123", "TestSaga", 5, "corr-123")
        log_output = stream.getvalue()
        assert "Saga started: TestSaga" in log_output

        # Test saga completed
        stream.truncate(0)
        stream.seek(0)
        logger.saga_completed("saga-123", "TestSaga", SagaStatus.COMPLETED, 100.0, 5, 5)
        log_output = stream.getvalue()
        assert "Saga finished: TestSaga" in log_output
        assert "completed" in log_output.lower()  # Status value is lowercase

    def test_saga_logger_step_lifecycle(self):
        """Test SagaLogger logs step lifecycle events"""
        logger = SagaLogger(name="step-test")

        # Capture log output
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)

        # Test step started
        logger.step_started("saga-123", "TestSaga", "step1")
        log_output = stream.getvalue()
        assert "Step started: step1" in log_output

        # Test step completed
        stream.truncate(0)
        stream.seek(0)
        logger.step_completed("saga-123", "TestSaga", "step1", 50.0, 0)
        log_output = stream.getvalue()
        assert "Step completed: step1" in log_output

    def test_log_level_filtering(self):
        """Test log level filtering works correctly"""
        logger = SagaLogger(name="level-test")
        logger.logger.setLevel(logging.WARNING)

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        logger.logger.addHandler(handler)

        # Log at different levels
        logger.logger.debug("Debug message")
        logger.logger.info("Info message")
        logger.logger.warning("Warning message")
        logger.logger.error("Error message")

        log_output = stream.getvalue()

        # Only warning and error should appear
        assert "Debug message" not in log_output
        assert "Info message" not in log_output
        assert "Warning message" in log_output
        assert "Error message" in log_output

    def test_saga_logger_step_failed(self):
        """Test step_failed logging"""
        logger = SagaLogger(name="step-failed-test")

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.ERROR)

        # Log step failure
        error = ValueError("Test error")
        logger.step_failed("saga-123", "TestSaga", "step1", error, 2)
        log_output = stream.getvalue()
        assert "Step failed: step1" in log_output
        assert "Test error" in log_output

    def test_saga_logger_compensation_lifecycle(self):
        """Test compensation logging methods"""
        logger = SagaLogger(name="compensation-test")

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.WARNING)

        # Test compensation started
        logger.compensation_started("saga-123", "TestSaga", "step1")
        log_output = stream.getvalue()
        assert "Compensation started: step1" in log_output

        # Test compensation completed
        stream.truncate(0)
        stream.seek(0)
        logger.compensation_completed("saga-123", "TestSaga", "step1", 50.0)
        log_output = stream.getvalue()
        assert "Compensation completed: step1" in log_output

        # Test compensation failed
        stream.truncate(0)
        stream.seek(0)
        error = RuntimeError("Compensation error")
        logger.compensation_failed("saga-123", "TestSaga", "step1", error)
        log_output = stream.getvalue()
        assert "Compensation FAILED: step1" in log_output
        assert "Compensation error" in log_output

    def test_setup_saga_logging(self):
        """Test setup_saga_logging utility function"""

        # Test with JSON format
        logger = setup_saga_logging(log_level="DEBUG", json_format=True, include_console=True)
        assert isinstance(logger, SagaLogger)
        assert logger.logger.name == "saga"

        # Test without console
        logger2 = setup_saga_logging(log_level="INFO", json_format=False, include_console=False)
        assert isinstance(logger2, SagaLogger)


class TestSagaTracer:
    """Test SagaTracer functionality"""

    def test_tracer_initialization(self):
        """Test SagaTracer initializes correctly"""
        tracer = SagaTracer(service_name="test-service")

        assert tracer.service_name == "test-service"
        # Tracer may be None if OpenTelemetry not installed
        assert hasattr(tracer, "tracer")

    @pytest.mark.asyncio
    async def test_tracer_start_saga_trace(self):
        """Test start_saga_trace context manager"""
        tracer = SagaTracer(service_name="trace-test")

        # Should work whether OpenTelemetry is installed or not
        with tracer.start_saga_trace("saga-123", "TestSaga", 3):
            # Context manager should work
            pass

    @pytest.mark.asyncio
    async def test_tracer_start_step_trace(self):
        """Test start_step_trace context manager"""
        tracer = SagaTracer(service_name="step-test")

        # Should work whether OpenTelemetry is installed or not
        with tracer.start_step_trace("saga-123", "TestSaga", "step1", "action"):
            pass

    @pytest.mark.asyncio
    async def test_trace_saga_action_decorator(self):
        """Test @trace_saga_action decorator works"""
        tracer = SagaTracer(service_name="decorator-test")

        @trace_saga_action(tracer)
        async def test_action(ctx: SagaContext):
            await asyncio.sleep(0.01)
            return {"result": "success"}

        ctx = SagaContext(data={"test": "data"})
        ctx._saga_id = "test-123"
        ctx._saga_name = "TestSaga"
        ctx._step_name = "test_action"

        result = await test_action(ctx)

        assert result["result"] == "success"
        # Decorator should not interfere with function execution

    @pytest.mark.asyncio
    async def test_trace_saga_compensation_decorator(self):
        """Test @trace_saga_compensation decorator works"""
        tracer = SagaTracer(service_name="compensation-test")

        @trace_saga_compensation(tracer)
        async def test_compensation(action_result, ctx: SagaContext):
            await asyncio.sleep(0.01)
            return

        ctx = SagaContext(data={"test": "data"})
        ctx._saga_id = "test-123"
        ctx._saga_name = "TestSaga"
        ctx._step_name = "test_compensation"

        result = await test_compensation({"original": "data"}, ctx)

        assert result is None
        # Decorator should not interfere with function execution

    def test_tracer_record_saga_completion(self):
        """Test record_saga_completion"""
        tracer = SagaTracer(service_name="completion-test")

        # Should not raise exception
        tracer.record_saga_completion(
            saga_id="saga-123",
            status=SagaStatus.COMPLETED,
            completed_steps=5,
            total_steps=5,
            duration_ms=100.0,
        )

    def test_tracer_record_step_completion(self):
        """Test record_step_completion"""
        tracer = SagaTracer(service_name="step-completion-test")

        # Should not raise exception
        from sagaz.types import SagaStepStatus

        tracer.record_step_completion(
            step_name="step1", status=SagaStepStatus.COMPLETED, duration_ms=50.0, retry_count=0
        )

    def test_tracer_get_trace_context(self):
        """Test get_trace_context"""
        tracer = SagaTracer(service_name="context-test")

        # Should return dict (empty if OpenTelemetry not installed)
        context = tracer.get_trace_context()
        assert isinstance(context, dict)

    def test_tracer_create_child_span(self):
        """Test create_child_span"""
        tracer = SagaTracer(service_name="child-span-test")

        # Should handle gracefully whether OpenTelemetry is installed or not
        tracer.create_child_span("external-call", {"service": "payment"})
        # Span may be None if OpenTelemetry not installed, which is fine

    def test_setup_tracing(self):
        """Test setup_tracing utility function"""
        from sagaz.monitoring.tracing import setup_tracing

        tracer = setup_tracing(service_name="test-service")
        assert isinstance(tracer, SagaTracer)
        assert tracer.service_name == "test-service"

    @pytest.mark.asyncio
    async def test_tracer_with_parent_context(self):
        """Test saga trace with parent context"""
        tracer = SagaTracer(service_name="parent-test")

        # Should handle parent context gracefully
        parent_context = {"traceparent": "00-trace-id-span-id-01"}
        with tracer.start_saga_trace("saga-123", "TestSaga", 3, parent_context):
            pass  # Should not raise

    @pytest.mark.asyncio
    async def test_tracer_error_recording(self):
        """Test tracer records errors properly"""
        tracer = SagaTracer(service_name="error-test")

        # Test recording saga error
        error = ValueError("Test error")
        tracer.record_saga_completion(
            saga_id="saga-123",
            status=SagaStatus.FAILED,
            completed_steps=2,
            total_steps=5,
            duration_ms=100.0,
            error=error,
        )
        # Should not raise

        # Test recording step error
        from sagaz.types import SagaStepStatus

        tracer.record_step_completion(
            step_name="step1",
            status=SagaStepStatus.FAILED,
            duration_ms=50.0,
            retry_count=1,
            error=error,
        )
        # Should not raise


class TestSagaMetrics:
    """Tests for SagaMetrics"""

    def test_metrics_initialization(self):
        """Test metrics initialization"""
        metrics = SagaMetrics()
        result = metrics.get_metrics()

        assert result["total_executed"] == 0
        assert result["total_successful"] == 0
        assert result["total_failed"] == 0
        assert result["total_rolled_back"] == 0

    def test_metrics_recording(self):
        """Test recording metrics"""
        metrics = SagaMetrics()

        metrics.record_execution("test-saga", SagaStatus.COMPLETED, 1.5)
        result = metrics.get_metrics()
        assert result["total_executed"] == 1
        assert result["total_successful"] == 1

        metrics.record_execution("test-saga", SagaStatus.FAILED, 0.8)
        result = metrics.get_metrics()
        assert result["total_executed"] == 2
        assert result["total_failed"] == 1

        metrics.record_execution("test-saga", SagaStatus.ROLLED_BACK, 2.0)
        result = metrics.get_metrics()
        assert result["total_executed"] == 3
        assert result["total_rolled_back"] == 1

    def test_metrics_calculations(self):
        """Test metrics calculations"""
        metrics = SagaMetrics()

        metrics.record_execution("saga-1", SagaStatus.COMPLETED, 1.0)
        metrics.record_execution("saga-2", SagaStatus.COMPLETED, 2.0)
        metrics.record_execution("saga-3", SagaStatus.FAILED, 0.5)

        result = metrics.get_metrics()
        assert result["average_execution_time"] == pytest.approx(1.166, abs=0.01)
        assert result["success_rate"] == "66.67%"
        assert result["by_saga_name"]["saga-1"]["count"] == 1
        assert result["by_saga_name"]["saga-2"]["count"] == 1
        assert result["by_saga_name"]["saga-3"]["count"] == 1


class MockSaga(Saga):
    """Mock saga for integration testing"""

    def __init__(self, name: str, should_fail: bool = False):
        super().__init__(name=name, version="1.0")
        self.should_fail = should_fail

    async def build(self):
        await self.add_step(
            name="mock_step",
            action=self._mock_action,
            timeout=5.0,
        )

    async def _mock_action(self, ctx: SagaContext):
        if self.should_fail:
            msg = "Mock failure"
            raise ValueError(msg)
        await asyncio.sleep(0.01)
        return {"mock": "result"}


class TestMonitoringIntegration:
    """Test monitoring components work together"""

    @pytest.mark.asyncio
    async def test_saga_with_monitoring(self):
        """Test saga execution with full monitoring"""
        SagaLogger(name="integration-saga")
        SagaTracer(service_name="integration-test")
        metrics = SagaMetrics()

        saga = MockSaga("monitored-saga")
        await saga.build()

        # Execute saga (monitoring should not interfere)
        result = await saga.execute()

        assert result.success is True

        # Record metrics manually (in real implementation this would be automatic)
        metrics.record_execution(saga.name, result.status, result.execution_time)

        stats = metrics.get_metrics()
        assert stats["total_executed"] == 1
        assert stats["total_successful"] == 1
