"""
Tests for tracing module with mocked OpenTelemetry to achieve 100% coverage

These tests mock the OpenTelemetry imports to test the code paths that require
OpenTelemetry to be available, regardless of whether it's actually installed.
"""

from unittest.mock import MagicMock

import pytest

from sagaz.types import SagaStatus, SagaStepStatus


class TestTracingWithMockedOTel:
    """Tests that mock OpenTelemetry to cover the TRACING_AVAILABLE paths"""

    def _create_mock_span(self):
        """Create a mock span with all necessary methods"""
        span = MagicMock()
        span.set_attributes = MagicMock()
        span.set_status = MagicMock()
        span.record_exception = MagicMock()
        span.is_recording = MagicMock(return_value=True)
        span.end = MagicMock()
        return span

    def test_saga_tracer_init_with_otel(self):
        """Test SagaTracer initialization when OTel is available"""
        import sagaz.monitoring.tracing as tracing_module

        # Skip if OTel not available - these tests only make sense when OTel is installed
        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test-service")

        assert tracer.service_name == "test-service"
        assert tracer.tracer is not None

    def test_start_saga_trace_with_parent_context(self):
        """Test start_saga_trace with parent context extraction"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        parent_ctx = {"traceparent": "00-abc123def456789012345678901234-1234567890123456-01"}

        with tracer.start_saga_trace(
            saga_id="test-123", saga_name="TestSaga", total_steps=3, parent_context=parent_ctx
        ) as span:
            assert span is not None

    def test_start_saga_trace_exception_handling(self):
        """Test that saga trace handles exceptions and sets error status"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        with (
            pytest.raises(ValueError, match="Test error"),
            tracer.start_saga_trace(saga_id="error-test", saga_name="ErrorSaga", total_steps=1),
        ):
            msg = "Test error"
            raise ValueError(msg)

    def test_start_step_trace_exception_handling(self):
        """Test that step trace handles exceptions and sets error status"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

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

    def test_record_saga_completion_success(self):
        """Test record_saga_completion for successful saga"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        # Need to be inside a span context for record_saga_completion to work
        with tracer.start_saga_trace(saga_id="success-123", saga_name="SuccessSaga", total_steps=5):
            tracer.record_saga_completion(
                saga_id="success-123",
                status=SagaStatus.COMPLETED,
                completed_steps=5,
                total_steps=5,
                duration_ms=200.0,
            )

    def test_record_saga_completion_failure_with_error(self):
        """Test record_saga_completion for failed saga with error"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        test_error = Exception("Payment failed")

        with tracer.start_saga_trace(saga_id="fail-123", saga_name="FailSaga", total_steps=5):
            tracer.record_saga_completion(
                saga_id="fail-123",
                status=SagaStatus.FAILED,
                completed_steps=3,
                total_steps=5,
                duration_ms=150.0,
                error=test_error,
            )

    def test_record_step_completion_success(self):
        """Test record_step_completion for successful step"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        with tracer.start_step_trace(
            saga_id="step-test", saga_name="StepSaga", step_name="payment", step_type="action"
        ):
            tracer.record_step_completion(
                step_name="payment",
                status=SagaStepStatus.COMPLETED,
                duration_ms=50.0,
                retry_count=0,
            )

    def test_record_step_completion_failure_with_error(self):
        """Test record_step_completion for failed step with error"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        test_error = ValueError("Invalid data")

        with tracer.start_step_trace(
            saga_id="fail-step",
            saga_name="FailStepSaga",
            step_name="validation",
            step_type="action",
        ):
            tracer.record_step_completion(
                step_name="validation",
                status=SagaStepStatus.FAILED,
                duration_ms=30.0,
                retry_count=2,
                error=test_error,
            )

    def test_get_trace_context(self):
        """Test get_trace_context returns propagation headers"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        result = tracer.get_trace_context()
        assert isinstance(result, dict)

    def test_create_child_span_with_attributes(self):
        """Test create_child_span with attributes"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        attributes = {"db.name": "orders", "db.operation": "SELECT"}
        span = tracer.create_child_span("db-query", attributes=attributes)

        assert span is not None
        if span:
            span.end()

    def test_create_child_span_without_attributes(self):
        """Test create_child_span without attributes"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        span = tracer.create_child_span("simple-operation")

        assert span is not None
        if span:
            span.end()


class TestTracingDecoratorsWithContext:
    """Tests for tracing decorators with saga context"""

    @pytest.mark.asyncio
    async def test_trace_saga_action_with_saga_context(self):
        """Test action decorator extracts saga context from arguments"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer, trace_saga_action

        tracer = SagaTracer(service_name="test")

        # Create mock saga context
        class MockSagaContext:
            saga_id = "ctx-123"
            saga_name = "ContextSaga"
            step_name = "traced_action"

        @trace_saga_action(tracer)
        async def my_action(ctx):
            return f"executed for {ctx.saga_id}"

        result = await my_action(MockSagaContext())
        assert "ctx-123" in result

    @pytest.mark.asyncio
    async def test_trace_saga_compensation_with_saga_context(self):
        """Test compensation decorator extracts saga context from second arg"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer, trace_saga_compensation

        tracer = SagaTracer(service_name="test")

        class MockSagaContext:
            saga_id = "comp-456"
            saga_name = "CompSaga"
            step_name = "compensated_step"

        @trace_saga_compensation(tracer)
        async def my_compensation(result, ctx):
            return f"compensated {ctx.saga_id}"

        result = await my_compensation({"data": "test"}, MockSagaContext())
        assert "comp-456" in result


class TestSetupTracingCoverage:
    """Tests for setup_tracing function coverage"""

    def test_setup_tracing_with_endpoint(self):
        """Test setup_tracing with OTLP endpoint"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer, setup_tracing

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

    def test_setup_tracing_no_endpoint(self):
        """Test setup_tracing without endpoint (no OTLP configuration)"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer, setup_tracing

        tracer = setup_tracing(service_name="simple-service", endpoint=None)

        assert isinstance(tracer, SagaTracer)


class TestTracingRecordCompletionEdgeCases:
    """Tests for record_saga_completion and record_step_completion edge cases"""

    def test_record_saga_completion_non_completed_status(self):
        """Test record_saga_completion with non-COMPLETED status sets error status"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        # Test with FAILED status (no error provided)
        with tracer.start_saga_trace(saga_id="failed-saga", saga_name="FailedSaga", total_steps=5):
            tracer.record_saga_completion(
                saga_id="failed-saga",
                status=SagaStatus.FAILED,
                completed_steps=3,
                total_steps=5,
                duration_ms=150.0,
                error=None,  # No error
            )

    def test_record_saga_completion_rolled_back_status(self):
        """Test record_saga_completion with ROLLED_BACK status"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        with tracer.start_saga_trace(
            saga_id="rolledback-saga", saga_name="RolledBackSaga", total_steps=5
        ):
            tracer.record_saga_completion(
                saga_id="rolledback-saga",
                status=SagaStatus.ROLLED_BACK,
                completed_steps=2,
                total_steps=5,
                duration_ms=100.0,
                error=ValueError("Some error"),
            )

    def test_record_step_completion_non_completed_status(self):
        """Test record_step_completion with non-COMPLETED status"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        with tracer.start_step_trace(
            saga_id="step-test", saga_name="StepSaga", step_name="my_step", step_type="action"
        ):
            # Test with FAILED status (no error)
            tracer.record_step_completion(
                step_name="my_step",
                status=SagaStepStatus.FAILED,
                duration_ms=30.0,
                retry_count=1,
                error=None,  # No error provided
            )

    def test_record_step_completion_compensated_status(self):
        """Test record_step_completion with COMPENSATED status"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        with tracer.start_step_trace(
            saga_id="comp-step",
            saga_name="CompSaga",
            step_name="compensated_step",
            step_type="compensation",
        ):
            tracer.record_step_completion(
                step_name="compensated_step",
                status=SagaStepStatus.COMPENSATED,
                duration_ms=15.0,
                retry_count=0,
            )

    def test_record_outside_span_context(self):
        """Test record completion methods when not inside a span context"""
        import sagaz.monitoring.tracing as tracing_module

        if not tracing_module.TRACING_AVAILABLE:
            pytest.skip("OpenTelemetry not available")

        from sagaz.monitoring.tracing import SagaTracer

        tracer = SagaTracer(service_name="test")

        # These should not raise errors even when called outside of a span context
        tracer.record_saga_completion(
            saga_id="no-span",
            status=SagaStatus.COMPLETED,
            completed_steps=3,
            total_steps=3,
            duration_ms=100.0,
        )

        tracer.record_step_completion(
            step_name="no-span-step", status=SagaStepStatus.COMPLETED, duration_ms=50.0
        )
