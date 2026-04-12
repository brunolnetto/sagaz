"""Metrics listener for saga performance tracking."""

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass

from sagaz.core.listeners._base import SagaListener
from sagaz.core.logger import get_logger

logger = get_logger(__name__)


class MetricsSagaListener(SagaListener):
    """
    Records saga metrics using a metrics backend.

    Supports both the simple SagaMetrics class and the PrometheusMetrics backend.

    For Prometheus dashboards, use PrometheusMetrics:
        >>> from sagaz.monitoring.prometheus import PrometheusMetrics
        >>> metrics = PrometheusMetrics()
        >>>
        >>> class OrderSaga(Saga):
        ...     listeners = [MetricsSagaListener(metrics=metrics)]

    Example with simple metrics:
        >>> from sagaz.monitoring.metrics import SagaMetrics
        >>> metrics = SagaMetrics()
        >>>
        >>> class OrderSaga(Saga):
        ...     listeners = [MetricsSagaListener(metrics=metrics)]
    """

    def __init__(self, metrics=None):
        if metrics is None:
            from sagaz.monitoring.metrics import SagaMetrics

            metrics = SagaMetrics()
        self.metrics = metrics
        self._saga_start_times: dict[str, float] = {}
        self._step_start_times: dict[str, float] = {}

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        import time

        self._saga_start_times[saga_id] = time.time()
        # Track active sagas if metrics backend supports it
        if hasattr(self.metrics, "saga_started"):
            self.metrics.saga_started(saga_name)

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        import time

        saga_id = ctx.get("saga_id", "unknown")
        self._step_start_times[f"{saga_id}:{step_name}"] = time.time()

    async def on_step_success(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], result: Any
    ) -> None:
        self._record_step_duration(saga_name, step_name, ctx)

    async def on_step_failure(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self._record_step_duration(saga_name, step_name, ctx)

    def _record_step_duration(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        import time

        saga_id = ctx.get("saga_id", "unknown")
        key = f"{saga_id}:{step_name}"
        if key in self._step_start_times:
            duration = time.time() - self._step_start_times.pop(key)
            # Record step duration if metrics backend supports it
            if hasattr(self.metrics, "record_step_duration"):
                self.metrics.record_step_duration(saga_name, step_name, duration)

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        import time

        from sagaz.core.types import SagaStatus

        start_time = self._saga_start_times.pop(saga_id, time.time())
        duration = time.time() - start_time
        self.metrics.record_execution(saga_name, SagaStatus.COMPLETED, duration)
        # Track active sagas if metrics backend supports it
        if hasattr(self.metrics, "saga_finished"):
            self.metrics.saga_finished(saga_name)

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        import time

        from sagaz.core.types import SagaStatus

        start_time = self._saga_start_times.pop(saga_id, time.time())
        duration = time.time() - start_time
        self.metrics.record_execution(saga_name, SagaStatus.FAILED, duration)
        # Track active sagas if metrics backend supports it
        if hasattr(self.metrics, "saga_finished"):
            self.metrics.saga_finished(saga_name)
