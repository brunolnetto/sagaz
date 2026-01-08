# ============================================
# FILE: tests/test_orchestrator.py
# ============================================

"""
Tests for SagaOrchestrator - managing multiple concurrent sagas
"""

import asyncio

import pytest

from sagaz.core import Saga, SagaContext
from sagaz.orchestrator import SagaOrchestrator
from sagaz.types import SagaStatus


class SimpleSaga(Saga):
    """Simple test saga for orchestrator testing"""

    def __init__(self, name: str, delay: float = 0.01):
        super().__init__(name=name, version="1.0")
        self.delay = delay

    async def build(self):
        await self.add_step(
            name="simple_step",
            action=self._simple_action,
            timeout=1.0,
        )

    async def _simple_action(self, ctx: SagaContext) -> dict:
        await asyncio.sleep(self.delay)
        return {"completed": True, "saga": self.name}


class FailingSaga(Saga):
    """Saga that always fails for testing error handling"""

    def __init__(self, name: str):
        super().__init__(name=name, version="1.0")

    async def build(self):
        await self.add_step(
            name="failing_step",
            action=self._failing_action,
            timeout=5.0,
        )

    async def _failing_action(self, ctx: SagaContext) -> dict:
        msg = "Intentional failure for testing"
        raise ValueError(msg)


class TestSagaOrchestrator:
    """Test SagaOrchestrator functionality"""

    @pytest.fixture
    def orchestrator(self):
        """Create a fresh orchestrator for each test"""
        return SagaOrchestrator()

    @pytest.mark.asyncio
    async def test_orchestrator_initialization(self, orchestrator: SagaOrchestrator):
        """Test orchestrator initializes correctly"""
        assert orchestrator.sagas == {}
        assert orchestrator.logger is not None
        assert hasattr(orchestrator, "verbose")
        assert orchestrator.verbose is False

    @pytest.mark.asyncio
    async def test_single_saga_execution(self, orchestrator: SagaOrchestrator):
        """Test executing a single saga through orchestrator"""
        saga = SimpleSaga("test-saga-1")
        await saga.build()

        result = await orchestrator.execute_saga(saga)

        assert result.success is True
        assert result.saga_name == "test-saga-1"
        assert result.status == SagaStatus.COMPLETED
        assert len(orchestrator.sagas) == 1

    @pytest.mark.asyncio
    async def test_multiple_concurrent_sagas(self, orchestrator: SagaOrchestrator):
        """Test executing multiple sagas concurrently"""
        sagas = [
            SimpleSaga("saga-1", delay=0.01),
            SimpleSaga("saga-2", delay=0.01),
            SimpleSaga("saga-3", delay=0.01),
        ]

        # Build all sagas
        for saga in sagas:
            await saga.build()

        # Run them concurrently
        tasks = [orchestrator.execute_saga(saga) for saga in sagas]
        results = await asyncio.gather(*tasks)

        # All should succeedtest_saga_failure_handling
        assert len(results) == 3
        for result in results:
            assert result.success is True
            assert result.status == SagaStatus.COMPLETED

        # Check saga names are correct
        saga_names = {result.saga_name for result in results}
        assert saga_names == {"saga-1", "saga-2", "saga-3"}

        # Check sagas are tracked
        assert len(orchestrator.sagas) == 3

    @pytest.mark.asyncio
    async def test_saga_failure_handling(self, orchestrator: SagaOrchestrator):
        """Test orchestrator handles failed sagas correctly"""
        failing_saga = FailingSaga("failing-saga")
        await failing_saga.build()

        result = await orchestrator.execute_saga(failing_saga)

        assert result.success is False
        # Saga with no completed steps rolls back (to empty state) instead of FAILED
        assert result.status == SagaStatus.ROLLED_BACK
        assert result.error is not None
        assert "Intentional failure" in str(result.error)
        assert len(orchestrator.sagas) == 1

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self, orchestrator: SagaOrchestrator):
        """Test orchestrator handles mix of successful and failed sagas"""
        success_saga = SimpleSaga("success-saga")
        failure_saga = FailingSaga("failure-saga")

        await success_saga.build()
        await failure_saga.build()

        # Run both concurrently
        tasks = [orchestrator.execute_saga(success_saga), orchestrator.execute_saga(failure_saga)]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Check results
        success_result = next(r for r in results if r.saga_name == "success-saga")
        failure_result = next(r for r in results if r.saga_name == "failure-saga")

        assert success_result.success is True
        assert failure_result.success is False
        assert len(orchestrator.sagas) == 2

    @pytest.mark.asyncio
    async def test_orchestrator_concurrent_execution(self, orchestrator: SagaOrchestrator):
        """Test orchestrator can run multiple sagas concurrently"""
        # Create orchestrator with verbose logging
        verbose_orchestrator = SagaOrchestrator(verbose=True)

        # Create 3 sagas with small delays
        sagas = [SimpleSaga(f"concurrent-saga-{i}", delay=0.01) for i in range(3)]
        for saga in sagas:
            await saga.build()

        # Run all at once - should execute concurrently
        import time

        start_time = time.time()

        tasks = [verbose_orchestrator.execute_saga(saga) for saga in sagas]
        results = await asyncio.gather(*tasks)

        end_time = time.time()

        # With concurrent execution, should be faster than sequential (allow generous timeout for CI)
        assert end_time - start_time < 1.0  # Very lenient for slower CI environments

        # All should succeed
        assert all(result.success for result in results)
        assert len(verbose_orchestrator.sagas) == 3

    @pytest.mark.asyncio
    async def test_get_saga_status(self, orchestrator: SagaOrchestrator):
        """Test retrieving saga status from orchestrator"""
        saga = SimpleSaga("status-test-saga")
        await saga.build()

        # Run saga
        await orchestrator.execute_saga(saga)

        # Check we can retrieve status using orchestrator API
        saga_status = await orchestrator.get_saga_status(saga.saga_id)
        assert saga_status is not None
        assert saga_status["name"] == "status-test-saga"

    @pytest.mark.asyncio
    async def test_orchestrator_metrics(self, orchestrator: SagaOrchestrator):
        """Test orchestrator provides execution metrics"""
        # Run a few sagas
        success_saga = SimpleSaga("metrics-success")
        failure_saga = FailingSaga("metrics-failure")

        await success_saga.build()
        await failure_saga.build()

        await orchestrator.execute_saga(success_saga)
        await orchestrator.execute_saga(failure_saga)

        # Check metrics using orchestrator's statistics API
        stats = await orchestrator.get_statistics()

        assert stats["total_sagas"] == 2
        assert stats["completed"] == 1
        # Saga with no completed steps rolls back successfully, not fails
        assert stats["rolled_back"] == 1

    @pytest.mark.asyncio
    async def test_get_all_sagas_status(self, orchestrator):
        """Test retrieving status of all sagas"""
        saga1 = SimpleSaga("status-saga-1")
        saga2 = SimpleSaga("status-saga-2")

        await saga1.build()
        await saga2.build()

        await orchestrator.execute_saga(saga1)
        await orchestrator.execute_saga(saga2)

        all_status = await orchestrator.get_all_sagas_status()
        assert len(all_status) == 2
        # Status returns .value (string) not enum
        for s in all_status:
            assert s["status"] == "completed"

    @pytest.mark.asyncio
    async def test_count_by_status(self, orchestrator: SagaOrchestrator):
        """Test counting sagas by status"""
        success1 = SimpleSaga("success-1")
        success2 = SimpleSaga("success-2")
        failure = FailingSaga("failure-1")

        await success1.build()
        await success2.build()
        await failure.build()

        await orchestrator.execute_saga(success1)
        await orchestrator.execute_saga(success2)
        await orchestrator.execute_saga(failure)

        completed_count = await orchestrator.count_completed()
        # Saga with no completed steps rolls back successfully, not fails
        rolled_back_count = await orchestrator.count_rolled_back()

        assert completed_count == 2
        assert rolled_back_count == 1

    @pytest.mark.asyncio
    async def test_count_rolled_back(self, orchestrator: SagaOrchestrator):
        """Test counting rolled back sagas"""
        # Initially should be 0
        rolled_back_count = await orchestrator.count_rolled_back()
        assert rolled_back_count == 0

        # This method exists for completeness even if we don't have rolled back sagas in this test
        stats = await orchestrator.get_statistics()
        assert "rolled_back" in stats

    @pytest.mark.asyncio
    async def test_get_saga_returns_none_for_unknown_id(self, orchestrator: SagaOrchestrator):
        """Test get_saga returns None for unknown saga ID"""
        saga = await orchestrator.get_saga("nonexistent-id")
        assert saga is None

        status = await orchestrator.get_saga_status("nonexistent-id")
        assert status is None
