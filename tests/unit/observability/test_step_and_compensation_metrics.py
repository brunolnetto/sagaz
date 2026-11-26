"""Step outcomes and compensation failures are counted (#617)."""

from __future__ import annotations

import pytest

pytest.importorskip("prometheus_client")

from prometheus_client import CollectorRegistry

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.exceptions import SagaFailedError
from sagaz.core.listeners import MetricsSagaListener
from sagaz.observability.monitoring.prometheus import PrometheusMetrics


def sample(registry: CollectorRegistry, name: str, **labels: str) -> float:
    return registry.get_sample_value(name, labels) or 0.0


def metrics() -> tuple[PrometheusMetrics, CollectorRegistry]:
    registry = CollectorRegistry()
    return PrometheusMetrics(registry=registry), registry


class TestBackend:
    def test_a_step_outcome_is_counted_by_status(self):
        backend, registry = metrics()
        backend.record_step("order", "reserve", "succeeded")
        backend.record_step("order", "charge", "failed")
        backend.record_step("order", "charge", "failed")
        name = "sagaz_saga_step_executions_total"
        assert (
            sample(registry, name, saga_name="order", step_name="reserve", status="succeeded") == 1
        )
        assert sample(registry, name, saga_name="order", step_name="charge", status="failed") == 2

    def test_a_failed_compensation_is_counted(self):
        backend, registry = metrics()
        backend.record_compensation_failure("order", "reserve")
        name = "sagaz_saga_compensation_failures_total"
        assert sample(registry, name, saga_name="order", step_name="reserve") == 1

    def test_the_new_metrics_have_no_old_name(self):
        _, registry = metrics()
        names = {family.name for family in registry.collect()}
        assert "sagaz_saga_step_executions" in names
        assert "saga_step_executions" not in names
        assert "saga_compensation_failures" not in names


def order_saga(*, charge_fails: bool, release_fails: bool) -> type[Saga]:
    class OrderSaga(Saga):
        saga_name = "order"

        @action("reserve")
        async def reserve(self, ctx: dict) -> dict:
            return {}

        @compensate("reserve")
        async def release(self, ctx: dict) -> None:
            if release_fails:
                msg = "warehouse offline"
                raise RuntimeError(msg)

        @action("charge", depends_on=["reserve"])
        async def charge(self, ctx: dict) -> dict:
            if charge_fails:
                msg = "card declined"
                raise RuntimeError(msg)
            return {}

    return OrderSaga


async def run(saga_class: type[Saga]) -> CollectorRegistry:
    backend, registry = metrics()
    saga = saga_class(config=SagaConfig(metrics=False, logging=False))
    saga.add_listener(MetricsSagaListener(metrics=backend))
    try:
        await saga.run({})
    except SagaFailedError:
        pass
    return registry


class TestThroughTheListener:
    async def test_a_completed_saga_counts_each_step_succeeded(self):
        registry = await run(order_saga(charge_fails=False, release_fails=False))
        name = "sagaz_saga_step_executions_total"
        for step in ("reserve", "charge"):
            assert (
                sample(registry, name, saga_name="order", step_name=step, status="succeeded") == 1
            )

    async def test_a_failed_step_is_counted_failed(self):
        registry = await run(order_saga(charge_fails=True, release_fails=False))
        name = "sagaz_saga_step_executions_total"
        assert sample(registry, name, saga_name="order", step_name="charge", status="failed") == 1
        failures = "sagaz_saga_compensation_failures_total"
        assert sample(registry, failures, saga_name="order", step_name="reserve") == 0

    async def test_a_compensation_that_still_fails_is_counted(self):
        registry = await run(order_saga(charge_fails=True, release_fails=True))
        name = "sagaz_saga_compensation_failures_total"
        assert sample(registry, name, saga_name="order", step_name="reserve") == 1
