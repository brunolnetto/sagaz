"""
Tests for hooks.py and listeners.py to improve coverage.

Covers:
- Hook decorators (on_step_enter, on_step_success, etc.)
- publish_on_success, publish_on_failure, publish_on_compensate
- log_step_lifecycle
- SagaListener implementations (Logging, Metrics, Tracing, Outbox)
- default_listeners factory
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

# ============================================
# HOOKS TESTS
# ============================================


class TestHookDecorators:
    """Test hook decorator functions."""

    def test_on_step_enter_is_passthrough(self):
        """Test on_step_enter decorator just returns the function."""
        from sagaz.core.hooks import on_step_enter

        async def my_hook(ctx, step_name):
            pass

        result = on_step_enter(my_hook)
        assert result is my_hook

    def test_on_step_success_is_passthrough(self):
        """Test on_step_success decorator just returns the function."""
        from sagaz.core.hooks import on_step_success

        async def my_hook(ctx, step_name, result):
            pass

        result = on_step_success(my_hook)
        assert result is my_hook

    def test_on_step_failure_is_passthrough(self):
        """Test on_step_failure decorator just returns the function."""
        from sagaz.core.hooks import on_step_failure

        async def my_hook(ctx, step_name, error):
            pass

        result = on_step_failure(my_hook)
        assert result is my_hook

    def test_on_step_compensate_is_passthrough(self):
        """Test on_step_compensate decorator just returns the function."""
        from sagaz.core.hooks import on_step_compensate

        async def my_hook(ctx, step_name):
            pass

        result = on_step_compensate(my_hook)
        assert result is my_hook


class TestPublishOnSuccess:
    """Test publish_on_success hook factory."""

    @pytest.mark.asyncio
    async def test_publish_on_success_with_dict_result(self):
        """Test publishing success event with dict result."""
        from sagaz.core.hooks import publish_on_success

        mock_storage = AsyncMock()

        hook = publish_on_success(storage=mock_storage, event_type="order.created")

        ctx = {"saga_id": "saga-123", "aggregate_id": "agg-456"}
        result = {"order_id": "ORD-789"}

        await hook(ctx, "create_order", result)

        # Verify event was inserted
        mock_storage.insert.assert_called_once()
        event = mock_storage.insert.call_args[0][0]
        assert event.event_type == "order.created"
        assert event.saga_id == "saga-123"
        assert event.payload == {"order_id": "ORD-789"}

    @pytest.mark.asyncio
    async def test_publish_on_success_with_non_dict_result(self):
        """Test publishing success event with non-dict result."""
        from sagaz.core.hooks import publish_on_success

        mock_storage = AsyncMock()

        hook = publish_on_success(storage=mock_storage, event_type="order.processed")

        ctx = {"saga_id": "saga-123"}
        result = "SUCCESS"

        await hook(ctx, "process_order", result)

        event = mock_storage.insert.call_args[0][0]
        assert event.payload == {"result": "SUCCESS"}

    @pytest.mark.asyncio
    async def test_publish_on_success_with_custom_payload_builder(self):
        """Test publishing success event with custom payload builder."""
        from sagaz.core.hooks import publish_on_success

        mock_storage = AsyncMock()

        def custom_builder(ctx, result):
            return {"custom": True, "order_id": result.get("id")}

        hook = publish_on_success(
            storage=mock_storage, event_type="order.custom", payload_builder=custom_builder
        )

        ctx = {"saga_id": "saga-123"}
        result = {"id": "ORD-999"}

        await hook(ctx, "custom_step", result)

        event = mock_storage.insert.call_args[0][0]
        assert event.payload == {"custom": True, "order_id": "ORD-999"}

    @pytest.mark.asyncio
    async def test_publish_on_success_handles_storage_error(self):
        """Test that storage errors are logged but don't raise."""
        from sagaz.core.hooks import publish_on_success

        mock_storage = AsyncMock()
        mock_storage.insert.side_effect = Exception("Storage error")

        hook = publish_on_success(storage=mock_storage, event_type="order.created")

        ctx = {"saga_id": "saga-123"}
        result = {"data": "test"}

        # Should not raise
        await hook(ctx, "create_order", result)

    @pytest.mark.asyncio
    async def test_publish_on_success_uses_saga_id_as_aggregate_fallback(self):
        """Test that saga_id is used as aggregate_id fallback."""
        from sagaz.core.hooks import publish_on_success

        mock_storage = AsyncMock()

        hook = publish_on_success(storage=mock_storage, event_type="order.created")

        ctx = {"saga_id": "saga-123"}  # No aggregate_id
        result = {}

        await hook(ctx, "step", result)

        event = mock_storage.insert.call_args[0][0]
        assert event.aggregate_id == "saga-123"


class TestPublishOnFailure:
    """Test publish_on_failure hook factory."""

    @pytest.mark.asyncio
    async def test_publish_on_failure_with_error(self):
        """Test publishing failure event with error details."""
        from sagaz.core.hooks import publish_on_failure

        mock_storage = AsyncMock()

        hook = publish_on_failure(storage=mock_storage, event_type="order.failed")

        ctx = {"saga_id": "saga-123"}
        error = ValueError("Payment declined")

        await hook(ctx, "payment_step", error)

        event = mock_storage.insert.call_args[0][0]
        assert event.event_type == "order.failed"
        assert event.payload["step"] == "payment_step"
        assert event.payload["error"] == "Payment declined"
        assert event.payload["error_type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_publish_on_failure_without_error_details(self):
        """Test publishing failure event without error details."""
        from sagaz.core.hooks import publish_on_failure

        mock_storage = AsyncMock()

        hook = publish_on_failure(
            storage=mock_storage, event_type="order.failed", include_error=False
        )

        ctx = {"saga_id": "saga-123"}
        error = ValueError("Secret error")

        await hook(ctx, "payment_step", error)

        event = mock_storage.insert.call_args[0][0]
        assert "error" not in event.payload
        assert "error_type" not in event.payload

    @pytest.mark.asyncio
    async def test_publish_on_failure_handles_storage_error(self):
        """Test that storage errors are logged but don't raise."""
        from sagaz.core.hooks import publish_on_failure

        mock_storage = AsyncMock()
        mock_storage.insert.side_effect = Exception("Storage error")

        hook = publish_on_failure(storage=mock_storage, event_type="order.failed")

        ctx = {"saga_id": "saga-123"}
        error = ValueError("Test error")

        # Should not raise
        await hook(ctx, "step", error)


class TestPublishOnCompensate:
    """Test publish_on_compensate hook factory."""

    @pytest.mark.asyncio
    async def test_publish_on_compensate(self):
        """Test publishing compensation event."""
        from sagaz.core.hooks import publish_on_compensate

        mock_storage = AsyncMock()

        hook = publish_on_compensate(storage=mock_storage, event_type="order.cancelled")

        ctx = {"saga_id": "saga-123"}

        await hook(ctx, "cancel_order")

        event = mock_storage.insert.call_args[0][0]
        assert event.event_type == "order.cancelled"
        assert event.payload["step"] == "cancel_order"
        assert event.payload["compensated"] is True

    @pytest.mark.asyncio
    async def test_publish_on_compensate_handles_storage_error(self):
        """Test that storage errors are logged but don't raise."""
        from sagaz.core.hooks import publish_on_compensate

        mock_storage = AsyncMock()
        mock_storage.insert.side_effect = Exception("Storage error")

        hook = publish_on_compensate(storage=mock_storage, event_type="order.cancelled")

        ctx = {"saga_id": "saga-123"}

        # Should not raise
        await hook(ctx, "cancel_order")


class TestLogStepLifecycle:
    """Test log_step_lifecycle hook factory."""

    @pytest.mark.asyncio
    async def test_log_step_lifecycle_returns_hooks(self):
        """Test that log_step_lifecycle returns all expected hooks."""
        from sagaz.core.hooks import log_step_lifecycle

        hooks = log_step_lifecycle()

        assert "on_enter" in hooks
        assert "on_success" in hooks
        assert "on_failure" in hooks

    @pytest.mark.asyncio
    async def test_log_step_lifecycle_on_enter(self):
        """Test on_enter hook logs step start."""
        from sagaz.core.hooks import log_step_lifecycle

        mock_logger = MagicMock()
        hooks = log_step_lifecycle(logger_instance=mock_logger)

        await hooks["on_enter"]({}, "my_step")

        mock_logger.info.assert_called_once()
        assert "my_step" in mock_logger.info.call_args[0][0]

    @pytest.mark.asyncio
    async def test_log_step_lifecycle_on_success(self):
        """Test on_success hook logs step success."""
        from sagaz.core.hooks import log_step_lifecycle

        mock_logger = MagicMock()
        hooks = log_step_lifecycle(logger_instance=mock_logger)

        await hooks["on_success"]({}, "my_step", "result")

        mock_logger.info.assert_called_once()
        assert "my_step" in mock_logger.info.call_args[0][0]

    @pytest.mark.asyncio
    async def test_log_step_lifecycle_on_failure(self):
        """Test on_failure hook logs step failure."""
        from sagaz.core.hooks import log_step_lifecycle

        mock_logger = MagicMock()
        hooks = log_step_lifecycle(logger_instance=mock_logger)

        error = ValueError("Test error")
        await hooks["on_failure"]({}, "my_step", error)

        mock_logger.error.assert_called_once()
        assert "my_step" in mock_logger.error.call_args[0][0]


# ============================================
# LISTENERS TESTS
# ============================================


class TestSagaListenerBase:
    """Test base SagaListener class."""

    @pytest.mark.asyncio
    async def test_base_listener_methods_are_noops(self):
        """Test that base listener methods are no-ops."""
        from sagaz.core.listeners import SagaListener

        listener = SagaListener()

        # These should all do nothing but not raise
        await listener.on_saga_start("saga", "id", {})
        await listener.on_step_enter("saga", "step", {})
        await listener.on_step_success("saga", "step", {}, "result")
        await listener.on_step_failure("saga", "step", {}, Exception())
        await listener.on_compensation_start("saga", "step", {})
        await listener.on_compensation_complete("saga", "step", {})
        await listener.on_saga_complete("saga", "id", {})
        await listener.on_saga_failed("saga", "id", {}, Exception())


class TestLoggingSagaListener:
    """Test LoggingSagaListener class."""

    @pytest.mark.asyncio
    async def test_on_saga_start_logs(self):
        """Test saga start is logged."""
        from sagaz.core.listeners import LoggingSagaListener

        mock_logger = MagicMock()
        listener = LoggingSagaListener(logger_instance=mock_logger)

        await listener.on_saga_start("OrderSaga", "saga-123", {})

        mock_logger.log.assert_called_once()
        log_message = mock_logger.log.call_args[0][1]
        assert "OrderSaga" in log_message
        assert "saga-123" in log_message

    @pytest.mark.asyncio
    async def test_on_step_enter_logs(self):
        """Test step enter is logged."""
        from sagaz.core.listeners import LoggingSagaListener

        mock_logger = MagicMock()
        listener = LoggingSagaListener(logger_instance=mock_logger)

        await listener.on_step_enter("OrderSaga", "create_order", {})

        log_message = mock_logger.log.call_args[0][1]
        assert "OrderSaga.create_order" in log_message

    @pytest.mark.asyncio
    async def test_on_step_success_logs(self):
        """Test step success is logged."""
        from sagaz.core.listeners import LoggingSagaListener

        mock_logger = MagicMock()
        listener = LoggingSagaListener(logger_instance=mock_logger)

        await listener.on_step_success("OrderSaga", "create_order", {}, "result")

        log_message = mock_logger.log.call_args[0][1]
        assert "Success" in log_message

    @pytest.mark.asyncio
    async def test_on_step_failure_logs_error(self):
        """Test step failure is logged at error level."""
        from sagaz.core.listeners import LoggingSagaListener

        mock_logger = MagicMock()
        listener = LoggingSagaListener(logger_instance=mock_logger)

        error = ValueError("Test error")
        await listener.on_step_failure("OrderSaga", "payment", {}, error)

        mock_logger.error.assert_called_once()
        assert "Failed" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_compensation_start_logs(self):
        """Test compensation start is logged."""
        from sagaz.core.listeners import LoggingSagaListener

        mock_logger = MagicMock()
        listener = LoggingSagaListener(logger_instance=mock_logger)

        await listener.on_compensation_start("OrderSaga", "revert_payment", {})

        log_message = mock_logger.log.call_args[0][1]
        assert "COMPENSATION" in log_message

    @pytest.mark.asyncio
    async def test_on_compensation_complete_logs(self):
        """Test compensation complete is logged."""
        from sagaz.core.listeners import LoggingSagaListener

        mock_logger = MagicMock()
        listener = LoggingSagaListener(logger_instance=mock_logger)

        await listener.on_compensation_complete("OrderSaga", "revert_payment", {})

        log_message = mock_logger.log.call_args[0][1]
        assert "Complete" in log_message

    @pytest.mark.asyncio
    async def test_on_saga_complete_logs(self):
        """Test saga complete is logged."""
        from sagaz.core.listeners import LoggingSagaListener

        mock_logger = MagicMock()
        listener = LoggingSagaListener(logger_instance=mock_logger)

        await listener.on_saga_complete("OrderSaga", "saga-123", {})

        log_message = mock_logger.log.call_args[0][1]
        assert "Completed" in log_message

    @pytest.mark.asyncio
    async def test_on_saga_failed_logs_error(self):
        """Test saga failed is logged at error level."""
        from sagaz.core.listeners import LoggingSagaListener

        mock_logger = MagicMock()
        listener = LoggingSagaListener(logger_instance=mock_logger)

        error = ValueError("Saga error")
        await listener.on_saga_failed("OrderSaga", "saga-123", {}, error)

        mock_logger.error.assert_called_once()

    def test_custom_log_level(self):
        """Test LoggingSagaListener with custom log level."""
        from sagaz.core.listeners import LoggingSagaListener

        listener = LoggingSagaListener(level=logging.DEBUG)

        assert listener.level == logging.DEBUG


class TestMetricsSagaListener:
    """Test MetricsSagaListener class."""

    @pytest.mark.asyncio
    async def test_on_saga_start_records_time(self):
        """Test saga start records start time."""
        from sagaz.core.listeners import MetricsSagaListener

        mock_metrics = MagicMock()
        listener = MetricsSagaListener(metrics=mock_metrics)

        await listener.on_saga_start("OrderSaga", "saga-123", {})

        assert "saga-123" in listener._saga_start_times

    @pytest.mark.asyncio
    async def test_on_saga_complete_records_duration(self):
        """Test saga complete records execution duration."""
        from sagaz.core.listeners import MetricsSagaListener
        from sagaz.core.types import SagaStatus

        mock_metrics = MagicMock()
        listener = MetricsSagaListener(metrics=mock_metrics)

        await listener.on_saga_start("OrderSaga", "saga-123", {})
        await listener.on_saga_complete("OrderSaga", "saga-123", {})

        mock_metrics.record_execution.assert_called_once()
        args = mock_metrics.record_execution.call_args[0]
        assert args[0] == "OrderSaga"
        assert args[1] == SagaStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_on_saga_failed_records_duration(self):
        """Test saga failed records execution duration."""
        from sagaz.core.listeners import MetricsSagaListener
        from sagaz.core.types import SagaStatus

        mock_metrics = MagicMock()
        listener = MetricsSagaListener(metrics=mock_metrics)

        await listener.on_saga_start("OrderSaga", "saga-123", {})
        await listener.on_saga_failed("OrderSaga", "saga-123", {}, Exception())

        mock_metrics.record_execution.assert_called_once()
        args = mock_metrics.record_execution.call_args[0]
        assert args[1] == SagaStatus.FAILED

    def test_creates_default_metrics_if_not_provided(self):
        """Test MetricsSagaListener creates default metrics."""
        from sagaz.core.listeners import MetricsSagaListener
        from sagaz.observability.monitoring.metrics import SagaMetrics

        listener = MetricsSagaListener()

        assert isinstance(listener.metrics, SagaMetrics)


class TestTracingSagaListener:
    """TracingSagaListener emits real OpenTelemetry spans (in-memory exporter)."""

    @pytest.fixture
    def traced(self):
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        from sagaz.core.listeners import TracingSagaListener
        from sagaz.observability.monitoring.tracing import SagaTracer

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = SagaTracer("order-service")
        tracer.tracer = provider.get_tracer("test")
        return TracingSagaListener(tracer=tracer), exporter

    @staticmethod
    def _spans(exporter):
        return {span.name: span for span in exporter.get_finished_spans()}

    @pytest.mark.asyncio
    async def test_successful_run_emits_saga_and_step_spans(self, traced):
        listener, exporter = traced
        ctx = {"_steps": [1, 2]}
        await listener.on_saga_start("OrderSaga", "saga-123", ctx)
        await listener.on_step_enter("OrderSaga", "create_order", ctx)
        await listener.on_step_success("OrderSaga", "create_order", ctx, {"id": 1})
        await listener.on_saga_complete("OrderSaga", "saga-123", ctx)

        spans = self._spans(exporter)
        saga = spans["saga.execute.OrderSaga"]
        step = spans["saga.step.action.create_order"]
        assert saga.attributes["saga.id"] == "saga-123"
        assert saga.attributes["saga.total_steps"] == 2
        assert saga.attributes["saga.service"] == "order-service"
        assert saga.attributes["saga.status"] == "completed"
        assert step.parent.span_id == saga.context.span_id
        assert step.attributes["saga.step.type"] == "action"
        assert step.status.status_code.name == "OK"

    @pytest.mark.asyncio
    async def test_failure_and_compensation_are_traced(self, traced):
        listener, exporter = traced
        ctx: dict = {}
        error = RuntimeError("card declined")
        await listener.on_saga_start("OrderSaga", "saga-9", ctx)
        await listener.on_step_enter("OrderSaga", "charge", ctx)
        await listener.on_step_failure("OrderSaga", "charge", ctx, error)
        await listener.on_compensation_start("OrderSaga", "reserve", ctx)
        await listener.on_compensation_complete("OrderSaga", "reserve", ctx)
        await listener.on_saga_failed("OrderSaga", "saga-9", ctx, error)

        spans = self._spans(exporter)
        saga = spans["saga.execute.OrderSaga"]
        failed = spans["saga.step.action.charge"]
        undo = spans["saga.step.compensation.reserve"]
        assert failed.status.status_code.name == "ERROR"
        assert failed.events[0].name == "exception"
        assert undo.attributes["saga.step.type"] == "compensation"
        assert undo.parent.span_id == saga.context.span_id
        assert saga.status.status_code.name == "ERROR"
        assert saga.attributes["saga.status"] == "rolled_back"

    @pytest.mark.asyncio
    async def test_dangling_step_spans_are_closed_with_the_saga(self, traced):
        listener, exporter = traced
        ctx: dict = {}
        await listener.on_saga_start("OrderSaga", "s", ctx)
        await listener.on_step_enter("OrderSaga", "never_reports", ctx)
        await listener.on_saga_failed("OrderSaga", "s", ctx, RuntimeError("x"))

        assert "saga.step.action.never_reports" in self._spans(exporter)
        assert listener._steps == {}
        assert listener._runs == {}

    @pytest.mark.asyncio
    async def test_concurrent_runs_are_kept_apart(self, traced):
        listener, exporter = traced
        a: dict = {}
        b: dict = {}
        await listener.on_saga_start("OrderSaga", "run-a", a)
        await listener.on_saga_start("OrderSaga", "run-b", b)
        await listener.on_step_enter("OrderSaga", "step", a)
        await listener.on_step_enter("OrderSaga", "step", b)
        await listener.on_step_success("OrderSaga", "step", b, None)
        await listener.on_step_success("OrderSaga", "step", a, None)
        await listener.on_saga_complete("OrderSaga", "run-a", a)
        await listener.on_saga_complete("OrderSaga", "run-b", b)

        steps = [s for s in exporter.get_finished_spans() if s.name == "saga.step.action.step"]
        assert sorted(s.attributes["saga.id"] for s in steps) == ["run-a", "run-b"]

    @pytest.mark.asyncio
    async def test_hooks_without_a_started_run_are_ignored(self, traced):
        listener, exporter = traced
        ctx: dict = {}
        await listener.on_step_enter("OrderSaga", "orphan", ctx)
        await listener.on_step_success("OrderSaga", "orphan", ctx, None)
        await listener.on_saga_complete("OrderSaga", "missing", ctx)
        assert exporter.get_finished_spans() == ()

    @pytest.mark.asyncio
    async def test_noop_without_opentelemetry(self):
        from sagaz.core.listeners import TracingSagaListener

        tracer = MagicMock(spec=[])  # no ``tracer`` attribute -> tracing unavailable
        listener = TracingSagaListener(tracer=tracer)
        ctx: dict = {}
        await listener.on_saga_start("OrderSaga", "s", ctx)
        await listener.on_step_enter("OrderSaga", "a", ctx)
        await listener.on_saga_complete("OrderSaga", "s", ctx)
        assert listener._runs == {}

    def test_defaults_to_the_module_tracer(self):
        from sagaz.core.listeners import TracingSagaListener
        from sagaz.observability.monitoring.tracing import saga_tracer

        assert TracingSagaListener().tracer is saga_tracer


class TestOutboxSagaListener:
    """Test OutboxSagaListener class."""

    @pytest.mark.asyncio
    async def test_on_step_success_publishes_event(self):
        """Test step success publishes to outbox."""
        from sagaz.core.listeners import OutboxSagaListener

        mock_storage = AsyncMock()
        listener = OutboxSagaListener(storage=mock_storage)

        ctx = {"saga_id": "saga-123"}
        await listener.on_step_success("OrderSaga", "create_order", ctx, {"order_id": "123"})

        mock_storage.insert.assert_called_once()
        event = mock_storage.insert.call_args[0][0]
        assert event.event_type == "OrderSaga.create_order.success"

    @pytest.mark.asyncio
    async def test_on_step_success_skipped_when_disabled(self):
        """Test step success doesn't publish when disabled."""
        from sagaz.core.listeners import OutboxSagaListener

        mock_storage = AsyncMock()
        listener = OutboxSagaListener(storage=mock_storage, publish_step_events=False)

        ctx = {"saga_id": "saga-123"}
        await listener.on_step_success("OrderSaga", "create_order", ctx, {})

        mock_storage.insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_step_failure_publishes_event(self):
        """Test step failure publishes to outbox."""
        from sagaz.core.listeners import OutboxSagaListener

        mock_storage = AsyncMock()
        listener = OutboxSagaListener(storage=mock_storage)

        ctx = {"saga_id": "saga-123"}
        error = ValueError("Payment failed")
        await listener.on_step_failure("OrderSaga", "payment", ctx, error)

        event = mock_storage.insert.call_args[0][0]
        assert event.event_type == "OrderSaga.payment.failed"
        assert event.payload["error"] == "Payment failed"

    @pytest.mark.asyncio
    async def test_on_saga_complete_publishes_event(self):
        """Test saga complete publishes to outbox."""
        from sagaz.core.listeners import OutboxSagaListener

        mock_storage = AsyncMock()
        listener = OutboxSagaListener(storage=mock_storage)

        await listener.on_saga_complete("OrderSaga", "saga-123", {})

        event = mock_storage.insert.call_args[0][0]
        assert event.event_type == "OrderSaga.completed"

    @pytest.mark.asyncio
    async def test_on_saga_failed_publishes_event(self):
        """Test saga failed publishes to outbox."""
        from sagaz.core.listeners import OutboxSagaListener

        mock_storage = AsyncMock()
        listener = OutboxSagaListener(storage=mock_storage)

        error = ValueError("Saga error")
        await listener.on_saga_failed("OrderSaga", "saga-123", {}, error)

        event = mock_storage.insert.call_args[0][0]
        assert event.event_type == "OrderSaga.failed"
        assert event.payload["error"] == "Saga error"

    @pytest.mark.asyncio
    async def test_on_compensation_complete_publishes_event(self):
        """Test compensation complete publishes to outbox."""
        from sagaz.core.listeners import OutboxSagaListener

        mock_storage = AsyncMock()
        listener = OutboxSagaListener(storage=mock_storage)

        ctx = {"saga_id": "saga-123"}
        await listener.on_compensation_complete("OrderSaga", "revert_order", ctx)

        event = mock_storage.insert.call_args[0][0]
        assert event.event_type == "OrderSaga.revert_order.compensated"

    @pytest.mark.asyncio
    async def test_publish_event_handles_storage_error(self):
        """Test that storage errors are caught."""
        from sagaz.core.listeners import OutboxSagaListener

        mock_storage = AsyncMock()
        mock_storage.insert.side_effect = Exception("Storage error")
        listener = OutboxSagaListener(storage=mock_storage)

        # Should not raise
        ctx = {"saga_id": "saga-123"}
        await listener.on_step_success("OrderSaga", "step", ctx, {})


class TestDefaultListeners:
    """Test default_listeners factory function."""

    def test_default_listeners_with_all_options(self):
        """Test creating listeners with all options enabled."""
        from sagaz.core.listeners import (
            LoggingSagaListener,
            MetricsSagaListener,
            OutboxSagaListener,
            TracingSagaListener,
            default_listeners,
        )

        mock_storage = AsyncMock()

        listeners = default_listeners(
            metrics=True,
            logging_enabled=True,
            tracing=True,
            outbox_storage=mock_storage,
        )

        assert len(listeners) == 4
        assert any(isinstance(l, LoggingSagaListener) for l in listeners)
        assert any(isinstance(l, MetricsSagaListener) for l in listeners)
        assert any(isinstance(l, TracingSagaListener) for l in listeners)
        assert any(isinstance(l, OutboxSagaListener) for l in listeners)

    def test_default_listeners_with_no_options(self):
        """Test creating listeners with all options disabled."""
        from sagaz.core.listeners import default_listeners

        listeners = default_listeners(
            metrics=False,
            logging_enabled=False,
            tracing=False,
            outbox_storage=None,
        )

        assert len(listeners) == 0

    def test_default_listeners_defaults(self):
        """Test default_listeners has sensible defaults."""
        from sagaz.core.listeners import LoggingSagaListener, MetricsSagaListener, default_listeners

        listeners = default_listeners()

        # By default, metrics and logging are enabled
        assert len(listeners) == 2
        assert any(isinstance(l, LoggingSagaListener) for l in listeners)
        assert any(isinstance(l, MetricsSagaListener) for l in listeners)
