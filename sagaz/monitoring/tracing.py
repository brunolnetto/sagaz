"""
Distributed tracing support for saga execution

Provides OpenTelemetry-compatible tracing for saga patterns, enabling
end-to-end observability across distributed saga executions.

Note: This module is optional and gracefully degrades when OpenTelemetry
is not installed. All tracing operations become no-ops.

Installation:
    pip install opentelemetry-api opentelemetry-sdk

    # For OTLP export (optional):
    pip install opentelemetry-exporter-otlp-proto-grpc

Quick Start:
    >>> from sagaz.monitoring.tracing import setup_tracing, is_tracing_available

    # Check if tracing is available
    >>> if is_tracing_available():
    ...     tracer = setup_tracing("my-service")
    ... else:
    ...     print("Install opentelemetry for distributed tracing")
"""

import functools
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, ParamSpec, TypeVar

try:
    from opentelemetry import context, trace
    from opentelemetry.trace import Span, Status, StatusCode
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    TRACING_AVAILABLE = True
except ImportError:  # pragma: no cover
    # Graceful degradation if OpenTelemetry is not installed
    TRACING_AVAILABLE = False
    trace = None  # type: ignore[assignment]
    Span = None  # type: ignore[assignment, misc]
    StatusCode = None  # type: ignore[assignment, misc]


from sagaz.core.types import SagaStatus, SagaStepStatus

P = ParamSpec("P")
T = TypeVar("T")

# Context variable for current trace context
trace_context: ContextVar[dict[str, Any]] = ContextVar("trace_context", default={})


def is_tracing_available() -> bool:
    """
    Check if OpenTelemetry is available for distributed tracing.

    Returns:
        True if OpenTelemetry is installed and available, False otherwise.

    Example:
        >>> if is_tracing_available():
        ...     tracer = setup_tracing("my-service")
        ...     # Use tracer for distributed tracing
        ... else:
        ...     print("Tracing not available - install opentelemetry-api opentelemetry-sdk")
    """
    return TRACING_AVAILABLE  # pragma: no cover


class SagaTracer:
    """
    Distributed tracing for saga execution

    Provides automatic span creation and context propagation for saga operations.
    Gracefully degrades to no-ops when OpenTelemetry is not installed.

    Example:
        >>> tracer = SagaTracer("order-service")
        >>> with tracer.start_saga_trace("order-123", "OrderSaga", 3) as span:
        ...     # Saga execution code
        ...     pass
    """

    def __init__(self, service_name: str = "saga-service"):
        self.service_name = service_name

        if TRACING_AVAILABLE:
            self.tracer = trace.get_tracer(__name__)
        else:
            self.tracer = None  # type: ignore[assignment]

    @contextmanager
    def start_saga_trace(
        self,
        saga_id: str,
        saga_name: str,
        total_steps: int,
        parent_context: dict[str, str] | None = None,
    ):
        """
        Start a distributed trace for saga execution

        Args:
            saga_id: Unique saga identifier
            saga_name: Human-readable saga name
            total_steps: Total number of steps in saga
            parent_context: Parent trace context (for chaining sagas)
        """

        if not TRACING_AVAILABLE or not self.tracer:
            yield None
            return

        # Extract parent context if provided
        if parent_context:
            parent_span_context = TraceContextTextMapPropagator().extract(parent_context)
        else:
            parent_span_context = None

        with self.tracer.start_as_current_span(
            name=f"saga.execute.{saga_name}",
            context=parent_span_context,
            kind=trace.SpanKind.INTERNAL,
        ) as span:
            # Set saga attributes
            span.set_attributes(
                {
                    "saga.id": saga_id,
                    "saga.name": saga_name,
                    "saga.total_steps": total_steps,
                    "saga.service": self.service_name,
                }
            )

            # Store trace context
            trace_context.set(
                {
                    "saga_id": saga_id,
                    "saga_name": saga_name,
                    "span": span,
                }
            )

            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

    @contextmanager
    def start_step_trace(
        self, saga_id: str, saga_name: str, step_name: str, step_type: str = "action"
    ):
        """
        Start a trace span for saga step execution

        Args:
            saga_id: Saga identifier
            saga_name: Saga name
            step_name: Step name
            step_type: Type of step ("action" or "compensation")
        """

        if not TRACING_AVAILABLE or not self.tracer:
            yield None
            return

        with self.tracer.start_as_current_span(
            name=f"saga.step.{step_type}.{step_name}", kind=trace.SpanKind.INTERNAL
        ) as span:
            # Set step attributes
            span.set_attributes(
                {
                    "saga.id": saga_id,
                    "saga.name": saga_name,
                    "saga.step.name": step_name,
                    "saga.step.type": step_type,
                }
            )

            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

    def record_saga_completion(
        self,
        saga_id: str,
        status: SagaStatus,
        completed_steps: int,
        total_steps: int,
        duration_ms: float,
        error: Exception | None = None,
    ) -> None:
        """Record saga completion in current trace"""

        if not TRACING_AVAILABLE:
            return

        current_span = trace.get_current_span()
        if current_span.is_recording():
            current_span.set_attributes(
                {
                    "saga.status": status.value,
                    "saga.completed_steps": completed_steps,
                    "saga.total_steps": total_steps,
                    "saga.duration_ms": duration_ms,
                }
            )

            if status == SagaStatus.COMPLETED:
                current_span.set_status(Status(StatusCode.OK))
            else:
                current_span.set_status(
                    Status(StatusCode.ERROR, f"Saga failed with status: {status.value}")
                )

                if error:
                    current_span.record_exception(error)

    def record_step_completion(
        self,
        step_name: str,
        status: SagaStepStatus,
        duration_ms: float,
        retry_count: int = 0,
        error: Exception | None = None,
    ) -> None:
        """Record step completion in current trace"""

        if not TRACING_AVAILABLE:
            return

        current_span = trace.get_current_span()
        if current_span.is_recording():
            current_span.set_attributes(
                {
                    "saga.step.status": status.value,
                    "saga.step.duration_ms": duration_ms,
                    "saga.step.retry_count": retry_count,
                }
            )

            if status == SagaStepStatus.COMPLETED:
                current_span.set_status(Status(StatusCode.OK))
            else:
                current_span.set_status(Status(StatusCode.ERROR, f"Step failed: {step_name}"))

                if error:
                    current_span.record_exception(error)

    def get_trace_context(self) -> dict[str, str]:
        """
        Get current trace context for propagation to downstream services

        Returns:
            Dictionary with trace context headers
        """

        if not TRACING_AVAILABLE:
            return {}

        # Extract trace context as HTTP headers
        carrier: dict[str, str] = {}
        TraceContextTextMapPropagator().inject(carrier)
        return carrier

    def create_child_span(self, name: str, attributes: dict[str, Any] | None = None):
        """Create a child span for external service calls"""

        if not TRACING_AVAILABLE or not self.tracer:
            return None

        span = self.tracer.start_span(name=name, kind=trace.SpanKind.CLIENT)

        if attributes:
            span.set_attributes(attributes)

        return span


def trace_saga_action(tracer: SagaTracer):
    """
    Decorator to automatically trace saga actions

    Usage:
        @trace_saga_action(saga_tracer)
        async def my_action(ctx: SagaContext) -> Any:
            # Action implementation
            pass
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extract saga context from arguments
            saga_context = None
            for arg in args:
                if hasattr(arg, "saga_id"):
                    saga_context = arg
                    break

            if not saga_context:
                # No saga context found, execute without tracing
                return await func(*args, **kwargs)  # type: ignore[no-any-return, misc]

            step_name = getattr(saga_context, "step_name", func.__name__)
            saga_id = getattr(saga_context, "saga_id", "unknown")
            saga_name = getattr(saga_context, "saga_name", "unknown")

            with tracer.start_step_trace(saga_id, saga_name, step_name, "action"):
                return await func(*args, **kwargs)  # type: ignore[no-any-return, misc]

        return wrapper  # type: ignore[return-value]

    return decorator


def trace_saga_compensation(tracer: SagaTracer):
    """
    Decorator to automatically trace saga compensations

    Usage:
        @trace_saga_compensation(saga_tracer)
        async def my_compensation(result: Any, ctx: SagaContext) -> None:
            # Compensation implementation
            pass
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extract saga context from arguments (usually second arg)
            saga_context = None
            if len(args) >= 2 and hasattr(args[1], "saga_id"):
                saga_context = args[1]

            if not saga_context:
                return await func(*args, **kwargs)  # type: ignore[no-any-return, misc]

            step_name = getattr(saga_context, "step_name", func.__name__)
            saga_id = getattr(saga_context, "saga_id", "unknown")
            saga_name = getattr(saga_context, "saga_name", "unknown")

            with tracer.start_step_trace(saga_id, saga_name, step_name, "compensation"):
                return await func(*args, **kwargs)  # type: ignore[no-any-return, misc]

        return wrapper  # type: ignore[return-value]

    return decorator


# Default tracer instance
saga_tracer = SagaTracer()


def setup_tracing(
    service_name: str = "saga-service",
    endpoint: str | None = None,
    headers: dict[str, str] | None = None,
) -> SagaTracer:
    """
    Set up distributed tracing for sagas

    Args:
        service_name: Name of the service for tracing
        endpoint: OTLP endpoint for trace export (optional)
        headers: Additional headers for trace export

    Returns:
        Configured SagaTracer instance
    """

    if not TRACING_AVAILABLE:
        return SagaTracer(service_name)

    # Configure tracing provider if endpoint provided
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            # Create resource
            resource = Resource.create(
                {
                    "service.name": service_name,
                    "service.version": "1.0.0",
                }
            )

            # Set up tracer provider
            trace.set_tracer_provider(TracerProvider(resource=resource))

            # Set up OTLP exporter
            otlp_exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers or {})

            # Add span processor
            span_processor = BatchSpanProcessor(otlp_exporter)
            trace.get_tracer_provider().add_span_processor(span_processor)  # type: ignore[attr-defined]

        except ImportError:
            pass

    return SagaTracer(service_name)
