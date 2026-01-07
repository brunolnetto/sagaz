"""
Tests for saga pattern core functionality.

Includes:
1. SagaMetrics tests
2. Failure strategy tests (FAIL_FAST, WAIT_ALL, FAIL_FAST_WITH_GRACE)
"""

import asyncio

import pytest

from sagaz import ParallelFailureStrategy, SagaStatus
from sagaz.core import Saga
from sagaz.monitoring.metrics import SagaMetrics


class TestSagaMetrics:
    """Test SagaMetrics"""

    def test_metrics_initialization(self):
        """Test metrics initialize correctly"""
        metrics = SagaMetrics()

        assert metrics.metrics["total_executed"] == 0
        assert metrics.metrics["total_successful"] == 0
        assert metrics.metrics["total_failed"] == 0

    def test_record_successful_execution(self):
        """Test recording successful execution"""
        metrics = SagaMetrics()

        metrics.record_execution("TestSaga", SagaStatus.COMPLETED, 1.5)

        assert metrics.metrics["total_executed"] == 1
        assert metrics.metrics["total_successful"] == 1
        assert metrics.metrics["average_execution_time"] == 1.5

    def test_record_failed_execution(self):
        """Test recording failed execution"""
        metrics = SagaMetrics()

        metrics.record_execution("TestSaga", SagaStatus.FAILED, 0.5)

        assert metrics.metrics["total_executed"] == 1
        assert metrics.metrics["total_failed"] == 1

    def test_record_rolled_back_execution(self):
        """Test recording rolled back execution"""
        metrics = SagaMetrics()

        metrics.record_execution("TestSaga", SagaStatus.ROLLED_BACK, 2.0)

        assert metrics.metrics["total_executed"] == 1
        assert metrics.metrics["total_rolled_back"] == 1

    def test_average_execution_time_calculation(self):
        """Test average execution time is calculated correctly"""
        metrics = SagaMetrics()

        metrics.record_execution("Saga1", SagaStatus.COMPLETED, 1.0)
        metrics.record_execution("Saga2", SagaStatus.COMPLETED, 3.0)

        assert metrics.metrics["average_execution_time"] == 2.0

    def test_per_saga_name_tracking(self):
        """Test metrics tracked per saga name"""
        metrics = SagaMetrics()

        metrics.record_execution("OrderSaga", SagaStatus.COMPLETED, 1.0)
        metrics.record_execution("OrderSaga", SagaStatus.COMPLETED, 1.0)
        metrics.record_execution("PaymentSaga", SagaStatus.FAILED, 0.5)

        assert metrics.metrics["by_saga_name"]["OrderSaga"]["count"] == 2
        assert metrics.metrics["by_saga_name"]["OrderSaga"]["success"] == 2
        assert metrics.metrics["by_saga_name"]["PaymentSaga"]["failed"] == 1

    def test_get_metrics_includes_success_rate(self):
        """Test get_metrics includes success rate"""
        metrics = SagaMetrics()

        metrics.record_execution("Saga1", SagaStatus.COMPLETED, 1.0)
        metrics.record_execution("Saga2", SagaStatus.COMPLETED, 1.0)
        metrics.record_execution("Saga3", SagaStatus.FAILED, 1.0)

        result = metrics.get_metrics()

        assert "success_rate" in result
        assert result["success_rate"] == "66.67%"


class TestFailFastStrategy:
    """Test FAIL_FAST strategy"""

    @pytest.mark.asyncio
    async def test_fail_fast_cancels_immediately(self):
        """Test FAIL_FAST cancels remaining tasks immediately"""
        saga = Saga("FailFast", failure_strategy=ParallelFailureStrategy.FAIL_FAST)
        cancelled = []

        async def slow_task(ctx):
            try:
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                cancelled.append("cancelled")
                raise

        async def fast_fail(ctx):
            await asyncio.sleep(0.1)
            msg = "Fast fail"
            raise ValueError(msg)

        async def validate(ctx):
            return "validated"

        await saga.add_step("validate", validate, dependencies=set())
        await saga.add_step("slow", slow_task, dependencies={"validate"})
        await saga.add_step("fail", fast_fail, dependencies={"validate"})

        await saga.execute()

        assert "cancelled" in cancelled


class TestWaitAllStrategy:
    """Test WAIT_ALL strategy"""

    @pytest.mark.asyncio
    async def test_wait_all_completes_everything(self):
        """Test WAIT_ALL lets all tasks complete"""
        saga = Saga("WaitAll", failure_strategy=ParallelFailureStrategy.WAIT_ALL)
        completed = []

        async def task1(ctx):
            await asyncio.sleep(0.1)
            completed.append("task1")
            return "done"

        async def task2_fails(ctx):
            await asyncio.sleep(0.2)
            completed.append("task2_failed")
            msg = "Fail"
            raise ValueError(msg)

        async def task3(ctx):
            await asyncio.sleep(0.3)
            completed.append("task3")
            return "done"

        async def validate(ctx):
            return "validated"

        await saga.add_step("validate", validate, dependencies=set())
        await saga.add_step("task1", task1, dependencies={"validate"})
        await saga.add_step("task2", task2_fails, dependencies={"validate"})
        await saga.add_step("task3", task3, dependencies={"validate"})

        await saga.execute()

        assert "task1" in completed
        assert "task2_failed" in completed
        assert "task3" in completed


class TestFailFastWithGraceStrategy:
    """Test FAIL_FAST_WITH_GRACE strategy"""

    @pytest.mark.asyncio
    async def test_fail_fast_grace_waits_for_inflight(self):
        """Test FAIL_FAST_WITH_GRACE waits for in-flight tasks"""
        saga = Saga(
            "FailFastGrace", failure_strategy=ParallelFailureStrategy.FAIL_FAST_WITH_GRACE
        )
        completed = []

        async def fast_fail(ctx):
            await asyncio.sleep(0.1)
            msg = "Fail"
            raise ValueError(msg)

        async def inflight_task(ctx):
            await asyncio.sleep(0.3)
            completed.append("inflight")
            return "done"

        async def validate(ctx):
            return "validated"

        await saga.add_step("validate", validate, dependencies=set())
        await saga.add_step("fail", fast_fail, dependencies={"validate"})
        await saga.add_step("inflight", inflight_task, dependencies={"validate"})

        await saga.execute()

        # In-flight task should have completed
        assert "inflight" in completed
