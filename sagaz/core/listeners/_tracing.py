"""Tracing listener for distributed tracing support."""

from __future__ import annotations

from typing import Any

from sagaz.core.listeners._base import SagaListener
from sagaz.core.logger import get_logger

logger = get_logger(__name__)

_ACTION = "action"
_COMPENSATION = "compensation"


class TracingSagaListener(SagaListener):
    """
    Emits OpenTelemetry spans for saga execution.

    One ``saga.execute.<name>`` span per run, with a child span per step action
    (``saga.step.action.<step>``) and per compensation
    (``saga.step.compensation.<step>``). Failed steps and failed sagas get an
    ERROR status and the recorded exception. All of this is a no-op when
    OpenTelemetry is not installed.

    Listener hooks are fire-and-forget callbacks, so spans are opened and closed
    explicitly here (``SagaTracer``'s context managers cannot span two hooks).
    Spans are keyed by the identity of the run's context dict, which the
    executor passes unchanged to every hook of a run; one listener instance can
    therefore trace concurrent runs of the same saga class.

    Example:
        >>> from sagaz.observability.monitoring.tracing import setup_tracing
        >>> tracer = setup_tracing("order-service")
        >>>
        >>> class OrderSaga(Saga):
        ...     listeners = [TracingSagaListener(tracer=tracer)]
    """

    def __init__(self, tracer=None):
        if tracer is None:
            from sagaz.observability.monitoring.tracing import saga_tracer

            tracer = saga_tracer
        self.tracer = tracer
        self._runs: dict[int, tuple[Any, str]] = {}
        self._steps: dict[tuple[int, str, str], Any] = {}

    @property
    def _otel(self) -> Any:
        """The underlying OpenTelemetry tracer, or None when tracing is unavailable."""
        return getattr(self.tracer, "tracer", None)

    # ------------------------------------------------------------------ saga

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        if self._otel is None:
            return
        span = self._otel.start_span(
            f"saga.execute.{saga_name}",
            attributes={
                "saga.id": saga_id,
                "saga.name": saga_name,
                "saga.total_steps": len(ctx.get("_steps", [])),
                "saga.service": getattr(self.tracer, "service_name", ""),
            },
        )
        self._runs[id(ctx)] = (span, saga_id)

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        self._end_saga(ctx, "completed")

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self._end_saga(ctx, "rolled_back", error)

    # ----------------------------------------------------------------- steps

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        self._start_step(saga_name, step_name, ctx, _ACTION)

    async def on_step_success(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], result: Any
    ) -> None:
        self._end_step(ctx, step_name, _ACTION)

    async def on_step_failure(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self._end_step(ctx, step_name, _ACTION, error)

    async def on_compensation_start(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        self._start_step(saga_name, step_name, ctx, _COMPENSATION)

    async def on_compensation_complete(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        self._end_step(ctx, step_name, _COMPENSATION)

    # -------------------------------------------------------------- internals

    def _start_step(self, saga_name: str, step_name: str, ctx: dict[str, Any], kind: str) -> None:
        run = self._runs.get(id(ctx))
        if run is None or self._otel is None:
            return
        from opentelemetry import trace

        saga_span, saga_id = run
        span = self._otel.start_span(
            f"saga.step.{kind}.{step_name}",
            context=trace.set_span_in_context(saga_span),
            attributes={
                "saga.id": saga_id,
                "saga.name": saga_name,
                "saga.step.name": step_name,
                "saga.step.type": kind,
            },
        )
        self._steps[(id(ctx), step_name, kind)] = span

    def _end_step(
        self, ctx: dict[str, Any], step_name: str, kind: str, error: Exception | None = None
    ) -> None:
        span = self._steps.pop((id(ctx), step_name, kind), None)
        if span is not None:
            _finish(span, error)

    def _end_saga(self, ctx: dict[str, Any], status: str, error: Exception | None = None) -> None:
        run = self._runs.pop(id(ctx), None)
        if run is None:
            return
        # Close spans of steps that never reported back (e.g. cancelled siblings).
        for key in [k for k in self._steps if k[0] == id(ctx)]:
            _finish(self._steps.pop(key), error)
        saga_span, _ = run
        saga_span.set_attribute("saga.status", status)
        _finish(saga_span, error)


def _finish(span: Any, error: Exception | None) -> None:
    from opentelemetry.trace import Status, StatusCode

    if error is None:
        span.set_status(Status(StatusCode.OK))
    else:
        span.record_exception(error)
        span.set_status(Status(StatusCode.ERROR, str(error)))
    span.end()
