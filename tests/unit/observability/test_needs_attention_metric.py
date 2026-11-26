"""Sagas that stopped after a pivot are counted under their own status (#662, #571)."""

from __future__ import annotations

from typing import Any

import pytest

from sagaz import RecoveryAction, Saga, SagaFailedError, action, compensate, forward_recovery
from sagaz.choreography import ChoreographedSaga, ChoreographyEngine, ChoreographyTracker, EventBus
from sagaz.core.listeners import MetricsSagaListener
from sagaz.core.types import SagaStatus


class Recorded:
    """A metrics backend that keeps what it was told."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, str]] = []

    def record_execution(self, saga_name: str, status: SagaStatus, duration: float) -> None:
        self.executions.append((saga_name, status.value))


def order_saga(
    metrics: Recorded, *, pivot: bool, manual: bool = False, broken_undo: bool = False
) -> Saga:
    class OrderSaga(Saga):
        saga_name = "order"
        listeners = [MetricsSagaListener(metrics)]

        @action("reserve")
        async def reserve(self, ctx: dict[str, Any]) -> None: ...

        @compensate("reserve")
        async def release(self, ctx: dict[str, Any]) -> None:
            if broken_undo:
                msg = "warehouse offline"
                raise RuntimeError(msg)

        @action("charge", depends_on=["reserve"], pivot=pivot)
        async def charge(self, ctx: dict[str, Any]) -> None: ...

        @action("ship", depends_on=["charge"])
        async def ship(self, ctx: dict[str, Any]) -> None:
            msg = "no carrier"
            raise RuntimeError(msg)

        if manual:

            @forward_recovery("ship")
            async def recover(self, ctx: dict[str, Any], error: Exception) -> RecoveryAction:
                return RecoveryAction.MANUAL_INTERVENTION

    return OrderSaga()


class TestOrchestrated:
    async def test_a_saga_that_fails_after_a_pivot_is_partially_committed(self):
        metrics = Recorded()
        with pytest.raises(SagaFailedError):
            await order_saga(metrics, pivot=True).run({})
        assert metrics.executions == [("order", "partially_committed")]

    async def test_a_saga_that_waits_for_a_person_is_in_forward_recovery(self):
        metrics = Recorded()
        with pytest.raises(SagaFailedError):
            await order_saga(metrics, pivot=True, manual=True).run({})
        assert metrics.executions == [("order", "forward_recovery")]

    async def test_a_rolled_back_saga_is_rolled_back_not_failed(self):
        metrics = Recorded()
        with pytest.raises(SagaFailedError):
            await order_saga(metrics, pivot=False).run({})
        assert metrics.executions == [("order", "rolled_back")]

    async def test_a_saga_whose_compensation_failed_is_failed(self):
        metrics = Recorded()
        with pytest.raises(SagaFailedError):
            await order_saga(metrics, pivot=False, broken_undo=True).run({})
        assert metrics.executions == [("order", "failed")]

    async def test_the_in_memory_metrics_tell_them_apart(self):
        from sagaz.observability.monitoring.metrics import SagaMetrics

        metrics = SagaMetrics()
        for status in (
            SagaStatus.ROLLED_BACK,
            SagaStatus.PARTIALLY_COMMITTED,
            SagaStatus.FORWARD_RECOVERY,
            SagaStatus.FAILED,
        ):
            metrics.record_execution("order", status, 0.1)
        totals = metrics.get_metrics()
        assert totals["total_rolled_back"] == totals["total_failed"] == 1
        assert totals["total_partially_committed"] == totals["total_forward_recovery"] == 1


class TestChoreographed:
    @staticmethod
    async def run(metrics: Recorded, *, pivot: bool) -> None:
        async def reserve(event, me):
            await me.emit("stock.reserved")

        async def charge(event, me):
            await me.emit("payment.captured")

        async def ship(event, me):
            msg = "no carrier"
            raise RuntimeError(msg)

        bus = EventBus()
        engine = ChoreographyEngine(bus, default_max_retries=0)
        orders = ChoreographedSaga(name="orders")
        for participant in (
            orders,
            ChoreographedSaga(name="inventory").on("order.created", reserve, lambda e, me: None),
            ChoreographedSaga(name="payments").on("stock.reserved", charge, pivot=pivot),
            ChoreographedSaga(name="shipping").on("payment.captured", ship),
        ):
            engine.register(participant)
        tracker = ChoreographyTracker(bus, listeners=[MetricsSagaListener(metrics)])
        await engine.start()
        await tracker.start()
        await orders.begin("order.created", correlation_id="t-1")
        await tracker.stop()
        await engine.stop()

    async def test_a_transaction_compensated_after_a_pivot_is_partially_committed(self):
        metrics = Recorded()
        await self.run(metrics, pivot=True)
        assert metrics.executions == [("choreography", "partially_committed")]

    async def test_a_rolled_back_transaction_is_rolled_back_not_failed(self):
        metrics = Recorded()
        await self.run(metrics, pivot=False)
        assert metrics.executions == [("choreography", "rolled_back")]


def test_prometheus_counts_a_partially_committed_saga_as_one_that_compensated():
    pytest.importorskip("prometheus_client")
    from prometheus_client import CollectorRegistry

    from sagaz.observability.monitoring.prometheus import PrometheusMetrics

    registry = CollectorRegistry()
    metrics = PrometheusMetrics(registry=registry)
    metrics.record_execution("order", SagaStatus.PARTIALLY_COMMITTED, 0.1)
    metrics.record_execution("order", SagaStatus.FORWARD_RECOVERY, 0.1)
    value = registry.get_sample_value
    labels = {"saga_name": "order"}
    assert value("sagaz_saga_execution_total", {**labels, "status": "partially_committed"}) == 1
    assert value("sagaz_saga_execution_total", {**labels, "status": "forward_recovery"}) == 1
    assert value("sagaz_saga_compensations_total", labels) == 1  # forward recovery undid nothing
