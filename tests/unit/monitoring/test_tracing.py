"""
Tests for distributed tracing functionality

Tests the OpenTelemetry integration for saga tracing, both with
and without the OpenTelemetry dependencies installed.
"""

from unittest.mock import patch

import pytest

from sagaz.core.types import SagaStatus, SagaStepStatus
from sagaz.observability.monitoring.tracing import (
    TRACING_AVAILABLE,
    SagaTracer,
    setup_tracing,
    trace_saga_action,
    trace_saga_compensation,
)


class TestSagaTracerWithoutOTel:
    """Tests for SagaTracer when OpenTelemetry is not available"""

    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    def test_tracer_without_otel(self):
        """Test tracer gracefully degrades without OpenTelemetry"""
        tracer = SagaTracer(service_name="test-service")
        assert tracer.service_name == "test-service"
        assert tracer.tracer is None

    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    def test_start_saga_trace_without_otel(self):
        """Test start_saga_trace returns None without OpenTelemetry"""
        tracer = SagaTracer()

        with tracer.start_saga_trace(
            saga_id="test-123", saga_name="TestSaga", total_steps=3
        ) as span:
            assert span is None

    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    def test_start_step_trace_without_otel(self):
        """Test start_step_trace returns None without OpenTelemetry"""
        tracer = SagaTracer()

        with tracer.start_step_trace(
            saga_id="test-123", saga_name="TestSaga", step_name="step1", step_type="action"
        ) as span:
            assert span is None

    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    def test_record_saga_completion_without_otel(self):
        """Test record_saga_completion works without OpenTelemetry"""
        tracer = SagaTracer()
        # Should not raise any errors
        tracer.record_saga_completion(
            saga_id="test-123",
            status=SagaStatus.COMPLETED,
            completed_steps=3,
            total_steps=3,
            duration_ms=100.0,
        )

    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    def test_record_step_completion_without_otel(self):
        """Test record_step_completion works without OpenTelemetry"""
        tracer = SagaTracer()
        # Should not raise any errors
        tracer.record_step_completion(
            step_name="step1", status=SagaStepStatus.COMPLETED, duration_ms=50.0, retry_count=0
        )

    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    def test_get_trace_context_without_otel(self):
        """Test get_trace_context returns empty dict without OpenTelemetry"""
        tracer = SagaTracer()
        context = tracer.get_trace_context()
        assert context == {}

    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    def test_create_child_span_without_otel(self):
        """Test create_child_span returns None without OpenTelemetry"""
        tracer = SagaTracer()

        span = tracer.create_child_span(name="child-operation", attributes={"key": "value"})
        assert span is None


class TestSagaTracerWithMockedOTel:
    """Tests for SagaTracer with mocked OpenTelemetry"""

    def test_tracer_initialization(self):
        """Test tracer initialization with service name"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer(service_name="my-service")
        assert tracer.service_name == "my-service"
        assert tracer.tracer is not None

    def test_start_saga_trace(self):
        """Test starting a saga trace"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        with tracer.start_saga_trace(
            saga_id="trace-test-123", saga_name="TracedSaga", total_steps=5
        ) as span:
            # Span should be created
            assert span is not None

    def test_start_saga_trace_with_parent_context(self):
        """Test starting a saga trace with parent context"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        parent_context = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}

        with tracer.start_saga_trace(
            saga_id="child-saga-123",
            saga_name="ChildSaga",
            total_steps=3,
            parent_context=parent_context,
        ) as span:
            assert span is not None

    def test_start_step_trace(self):
        """Test starting a step trace"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        with tracer.start_step_trace(
            saga_id="step-trace-test", saga_name="TestSaga", step_name="payment", step_type="action"
        ) as span:
            assert span is not None

    def test_record_saga_completion_success(self):
        """Test recording successful saga completion"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        # Should not raise errors
        tracer.record_saga_completion(
            saga_id="completion-test",
            status=SagaStatus.COMPLETED,
            completed_steps=5,
            total_steps=5,
            duration_ms=200.0,
        )

    def test_record_saga_completion_failure(self):
        """Test recording failed saga completion"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        tracer.record_saga_completion(
            saga_id="failure-test",
            status=SagaStatus.FAILED,
            completed_steps=3,
            total_steps=5,
            duration_ms=150.0,
            error=Exception("Payment failed"),
        )

    def test_record_saga_completion_compensating(self):
        """Test recording saga in compensating state"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        tracer.record_saga_completion(
            saga_id="compensating-test",
            status=SagaStatus.COMPENSATING,
            completed_steps=3,
            total_steps=5,
            duration_ms=180.0,
        )

    def test_record_step_completion_success(self):
        """Test recording successful step completion"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        tracer.record_step_completion(
            step_name="inventory", status=SagaStepStatus.COMPLETED, duration_ms=45.0, retry_count=0
        )

    def test_record_step_completion_failure(self):
        """Test recording failed step completion"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        tracer.record_step_completion(
            step_name="payment",
            status=SagaStepStatus.FAILED,
            duration_ms=30.0,
            retry_count=2,
            error=Exception("Insufficient funds"),
        )

    def test_record_step_completion_compensated(self):
        """Test recording compensated step"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        tracer.record_step_completion(
            step_name="inventory", status=SagaStepStatus.COMPENSATED, duration_ms=20.0
        )

    def test_get_trace_context(self):
        """Test getting trace context for propagation"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()
        context = tracer.get_trace_context()

        # Should return a dict (may be empty if no active trace)
        assert isinstance(context, dict)

    def test_create_child_span(self):
        """Test creating a child span"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        span = tracer.create_child_span(
            name="database-query", attributes={"query": "SELECT * FROM orders", "db": "postgres"}
        )

        # Should create span
        assert span is not None
        # Clean up
        if span:
            span.end()

    def test_start_saga_trace_with_exception(self):
        """Test saga trace handles exceptions properly"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        with (
            pytest.raises(ValueError, match="Test error"),
            tracer.start_saga_trace(saga_id="error-test", saga_name="ErrorSaga", total_steps=1),
        ):
            msg = "Test error"
            raise ValueError(msg)

    def test_start_step_trace_with_exception(self):
        """Test step trace handles exceptions properly"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        with (
            pytest.raises(RuntimeError, match="Step failed"),
            tracer.start_step_trace(
                saga_id="step-error",
                saga_name="ErrorSaga",
                step_name="failing_step",
                step_type="action",
            ),
        ):
            msg = "Step failed"
            raise RuntimeError(msg)


class TestTracingDecorators:
    """Tests for tracing decorators"""

    @pytest.mark.asyncio
    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    async def test_trace_saga_action_without_otel(self):
        """Test action decorator works without OpenTelemetry"""
        tracer = SagaTracer()

        @trace_saga_action(tracer)
        async def my_action(value: int) -> int:
            return value * 2

        result = await my_action(5)
        assert result == 10

    @pytest.mark.asyncio
    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    async def test_trace_saga_compensation_without_otel(self):
        """Test compensation decorator works without OpenTelemetry"""
        tracer = SagaTracer()

        @trace_saga_compensation(tracer)
        async def my_compensation(value: int) -> int:
            return value // 2

        result = await my_compensation(10)
        assert result == 5

    @pytest.mark.asyncio
    async def test_trace_saga_action_with_otel(self):
        """Test action decorator with OpenTelemetry"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        @trace_saga_action(tracer)
        async def reserve_inventory(items: int) -> dict:
            return {"reserved": items}

        result = await reserve_inventory(100)
        assert result == {"reserved": 100}

    @pytest.mark.asyncio
    async def test_trace_saga_compensation_with_otel(self):
        """Test compensation decorator with OpenTelemetry"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        @trace_saga_compensation(tracer)
        async def release_inventory(reserved_items: dict) -> None:
            pass

        await release_inventory({"reserved": 100})

    @pytest.mark.asyncio
    async def test_trace_saga_action_with_context(self):
        """Test action decorator with saga context"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        # Mock saga context
        class MockContext:
            saga_id = "test-123"
            saga_name = "TestSaga"
            step_name = "reserve"

        @trace_saga_action(tracer)
        async def action_with_ctx(ctx: MockContext) -> str:
            return f"Action for {ctx.saga_id}"

        result = await action_with_ctx(MockContext())
        assert "test-123" in result

    @pytest.mark.asyncio
    async def test_trace_saga_compensation_with_context(self):
        """Test compensation decorator with saga context"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        # Mock saga context
        class MockContext:
            saga_id = "test-456"
            saga_name = "TestSaga"
            step_name = "release"

        @trace_saga_compensation(tracer)
        async def compensation_with_ctx(result: dict, ctx: MockContext) -> str:
            return f"Compensated {ctx.saga_id}"

        result = await compensation_with_ctx({"data": "test"}, MockContext())
        assert "test-456" in result

    @pytest.mark.asyncio
    async def test_trace_saga_action_exception_handling(self):
        """Test action decorator handles exceptions properly"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        @trace_saga_action(tracer)
        async def failing_action(value: int) -> int:
            msg = "Action failed"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="Action failed"):
            await failing_action(5)

    @pytest.mark.asyncio
    async def test_trace_saga_compensation_exception_handling(self):
        """Test compensation decorator handles exceptions properly"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()

        @trace_saga_compensation(tracer)
        async def failing_compensation(result: dict) -> None:
            msg = "Compensation failed"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="Compensation failed"):
            await failing_compensation({"data": "test"})


class TestTracingSetup:
    """Tests for tracing setup function"""

    @patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False)
    def test_setup_tracing_without_otel(self):
        """Test setup_tracing works without OpenTelemetry"""
        result = setup_tracing(service_name="test-service", endpoint="http://localhost:4317")

        # Should return a tracer even when OTel not available
        assert isinstance(result, SagaTracer)

    def test_setup_tracing_with_otel(self):
        """Test setup_tracing configures tracer"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        # Just test it doesn't crash - actual OTLP endpoint not needed
        tracer = setup_tracing(
            service_name="test-service",
            endpoint=None,  # No actual endpoint
        )

        # Should return a tracer instance
        assert isinstance(tracer, SagaTracer)

    def test_setup_tracing_with_endpoint(self):
        """Test setup_tracing with endpoint"""
        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        # Test without actual connection (OTLP exporter might not be installed)
        try:
            tracer = setup_tracing(
                service_name="prod-service",
                endpoint="http://localhost:4317",
                headers={"api-key": "test"},
            )
            assert isinstance(tracer, SagaTracer)
        except ImportError:
            # OTLP exporter not installed, which is fine
            pytest.skip("OTLP exporter not available")


class TestMonitoringTracingBranches:
    def test_is_tracing_available_called(self):
        """69: return TRACING_AVAILABLE - just needs to be called."""
        from sagaz.observability.monitoring.tracing import is_tracing_available

        result = is_tracing_available()
        assert isinstance(result, bool)

    def test_record_saga_completion_with_recording_span_completed(self):
        """207-218: record_saga_completion when span is_recording()=True, status=COMPLETED."""
        from unittest.mock import MagicMock, patch

        from sagaz.core.types import SagaStatus
        from sagaz.observability.monitoring.tracing import TRACING_AVAILABLE, SagaTracer

        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        tracer = SagaTracer()

        with patch("sagaz.monitoring.tracing.trace") as mock_trace:
            mock_trace.get_current_span.return_value = mock_span
            tracer.record_saga_completion(
                saga_id="test",
                status=SagaStatus.COMPLETED,
                completed_steps=3,
                total_steps=3,
                duration_ms=100.0,
            )
        mock_span.set_attributes.assert_called_once()
        mock_span.set_status.assert_called_once()

    def test_record_saga_completion_with_recording_span_failure_error(self):
        """219-224: record_saga_completion when failed with error → record_exception."""
        from unittest.mock import MagicMock, patch

        from sagaz.core.types import SagaStatus
        from sagaz.observability.monitoring.tracing import TRACING_AVAILABLE, SagaTracer

        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        tracer = SagaTracer()
        err = Exception("payment failed")

        with patch("sagaz.monitoring.tracing.trace") as mock_trace:
            mock_trace.get_current_span.return_value = mock_span
            tracer.record_saga_completion(
                saga_id="test",
                status=SagaStatus.FAILED,
                completed_steps=1,
                total_steps=3,
                duration_ms=50.0,
                error=err,
            )
        mock_span.record_exception.assert_called_once_with(err)

    def test_record_step_completion_with_recording_span_completed(self):
        """250-251: record_step_completion when is_recording()=True and status=COMPLETED."""
        from unittest.mock import MagicMock, patch

        from sagaz.core.types import SagaStepStatus
        from sagaz.observability.monitoring.tracing import TRACING_AVAILABLE, SagaTracer

        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        tracer = SagaTracer()

        with patch("sagaz.monitoring.tracing.trace") as mock_trace:
            mock_trace.get_current_span.return_value = mock_span
            tracer.record_step_completion(
                step_name="reserve_inventory",
                status=SagaStepStatus.COMPLETED,
                duration_ms=20.0,
            )
        mock_span.set_attributes.assert_called_once()
        mock_span.set_status.assert_called_once()

    def test_record_step_completion_with_recording_span_failed_no_error(self):
        """254->exit: record_step_completion failed with no error → if error: False."""
        from unittest.mock import MagicMock, patch

        from sagaz.core.types import SagaStepStatus
        from sagaz.observability.monitoring.tracing import TRACING_AVAILABLE, SagaTracer

        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        tracer = SagaTracer()

        with patch("sagaz.monitoring.tracing.trace") as mock_trace:
            mock_trace.get_current_span.return_value = mock_span
            tracer.record_step_completion(
                step_name="charge_payment",
                status=SagaStepStatus.FAILED,
                duration_ms=30.0,
                error=None,
            )
        mock_span.set_status.assert_called_once()
        mock_span.record_exception.assert_not_called()

    def test_create_child_span_without_attributes(self):
        """281->284: create_child_span called without attributes → if attributes: False."""
        from sagaz.observability.monitoring.tracing import TRACING_AVAILABLE, SagaTracer

        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        tracer = SagaTracer()
        span = tracer.create_child_span(name="no-attr-span")
        assert span is not None
        if span:
            span.end()

    def test_record_saga_completion_failed_no_error(self):
        """223->exit: status=FAILED with error=None → if error: False → exits block."""
        from unittest.mock import MagicMock, patch

        from sagaz.core.types import SagaStatus
        from sagaz.observability.monitoring.tracing import TRACING_AVAILABLE, SagaTracer

        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        tracer = SagaTracer()

        with patch("sagaz.monitoring.tracing.trace") as mock_trace:
            mock_trace.get_current_span.return_value = mock_span
            tracer.record_saga_completion(
                saga_id="test",
                status=SagaStatus.FAILED,
                completed_steps=1,
                total_steps=3,
                duration_ms=50.0,
                error=None,
            )
        mock_span.set_status.assert_called_once()
        mock_span.record_exception.assert_not_called()

    def test_record_step_completion_failed_with_error(self):
        """255: record_step_completion with status=FAILED and error set → record_exception."""
        from unittest.mock import MagicMock, patch

        from sagaz.core.types import SagaStepStatus
        from sagaz.observability.monitoring.tracing import TRACING_AVAILABLE, SagaTracer

        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        tracer = SagaTracer()
        err = Exception("step error")

        with patch("sagaz.monitoring.tracing.trace") as mock_trace:
            mock_trace.get_current_span.return_value = mock_span
            tracer.record_step_completion(
                step_name="charge_payment",
                status=SagaStepStatus.FAILED,
                duration_ms=30.0,
                error=err,
            )
        mock_span.record_exception.assert_called_once_with(err)

    def test_setup_tracing_otlp_import_error(self):
        """408-409: setup_tracing with endpoint when OTLP exporter not installed → except ImportError: pass."""
        import sys
        from unittest.mock import patch

        from sagaz.observability.monitoring.tracing import TRACING_AVAILABLE, SagaTracer, setup_tracing

        if not TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        # Block OTLP imports to trigger ImportError in setup_tracing
        with patch.dict(
            sys.modules,
            {
                "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
                "opentelemetry.sdk.resources": None,
                "opentelemetry.sdk.trace": None,
                "opentelemetry.sdk.trace.export": None,
            },
        ):
            result = setup_tracing(service_name="test-svc", endpoint="http://localhost:4317")
        assert isinstance(result, SagaTracer)


# ==========================================================================
# outbox/brokers/factory.py  – 50->49, 100, 196


class TestTracingImportError:
    """Cover lines 38, 40-43 in monitoring/tracing.py (except ImportError fallback)."""

    def test_tracing_module_import_error_fallback(self):
        """38, 40-43: ImportError when opentelemetry not installed → TRACING_AVAILABLE=False."""
        import importlib
        import sys

        orig_tracing = sys.modules.get("sagaz.monitoring.tracing")
        otel_keys = [k for k in sys.modules if "opentelemetry" in k]
        orig_otel = {k: sys.modules[k] for k in otel_keys}

        # Remove opentelemetry and the module
        for key in otel_keys:
            sys.modules.pop(key)
        sys.modules["opentelemetry"] = None  # type: ignore[assignment]
        sys.modules.pop("sagaz.monitoring.tracing", None)

        try:
            mod = importlib.import_module("sagaz.monitoring.tracing")
            assert mod.TRACING_AVAILABLE is False
        finally:
            if sys.modules.get("opentelemetry") is None:
                del sys.modules["opentelemetry"]
            # Restore opentelemetry
            for key, val in orig_otel.items():
                sys.modules[key] = val
            # Restore original module
            sys.modules.pop("sagaz.monitoring.tracing", None)
            if orig_tracing is not None:
                sys.modules["sagaz.monitoring.tracing"] = orig_tracing
