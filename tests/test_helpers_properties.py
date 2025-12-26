"""
Tests for helper methods and properties across various modules
Targets:sagaz/core.py,sagaz/types.py,sagaz/orchestrator.py
"""

import pytest

from sagaz.core import Saga
from sagaz.orchestrator import SagaOrchestrator
from sagaz.strategies.base import ParallelFailureStrategy
from sagaz.types import SagaResult, SagaStatus


class TestSagaHelperMethods:
    """Test helper methods in Saga class"""

    @pytest.mark.asyncio
    async def test_saga_name_property(self):
        """Test Saga.name property getter"""
        saga = Saga("MySagaName")
        assert saga.name == "MySagaName"

    @pytest.mark.asyncio
    async def test_set_failure_strategy(self):
        """Test set_failure_strategy method with logging"""
        saga = Saga("TestSaga")

        # Default should be FAIL_FAST_WITH_GRACE
        assert saga.failure_strategy.value == "fail_fast_grace"

        # Change to WAIT_ALL
        saga.set_failure_strategy(ParallelFailureStrategy.WAIT_ALL)
        assert saga.failure_strategy.value == "wait_all"

        # Change to FAIL_FAST
        saga.set_failure_strategy(ParallelFailureStrategy.FAIL_FAST)
        assert saga.failure_strategy.value == "fail_fast"

    @pytest.mark.asyncio
    async def test_saga_step_name_property(self):
        """Test SagaStep name access through saga"""

        async def dummy_action(ctx):
            return "result"

        saga = Saga("TestSaga")
        await saga.add_step("test_step", dummy_action)

        # Access step name through saga
        assert saga.steps[0].name == "test_step"
        assert len(saga.steps) == 1


class TestSagaResultProperties:
    """Test SagaResult properties"""

    def test_is_completed_property(self):
        """Test is_completed property"""

        # Completed result
        result = SagaResult(
            success=True,
            saga_name="TestSaga",
            status=SagaStatus.COMPLETED,
            completed_steps=2,
            total_steps=2,
            error=None,
            execution_time=1.0,
            context={},
            compensation_errors=[],
        )
        assert result.is_completed is True

        # Not completed
        result_pending = SagaResult(
            success=False,
            saga_name="TestSaga",
            status=SagaStatus.PENDING,
            completed_steps=0,
            total_steps=2,
            error=None,
            execution_time=0.0,
            context={},
            compensation_errors=[],
        )
        assert result_pending.is_completed is False

    def test_is_rolled_back_property(self):
        """Test is_rolled_back property"""
        # Rolled back result
        result = SagaResult(
            success=False,
            saga_name="TestSaga",
            status=SagaStatus.ROLLED_BACK,
            completed_steps=1,
            total_steps=2,
            error=ValueError("Failed"),
            execution_time=1.0,
            context={},
            compensation_errors=[],
        )
        assert result.is_rolled_back is True

        # Not rolled back
        result_completed = SagaResult(
            success=True,
            saga_name="TestSaga",
            status=SagaStatus.COMPLETED,
            completed_steps=2,
            total_steps=2,
            error=None,
            execution_time=1.0,
            context={},
            compensation_errors=[],
        )
        assert result_completed.is_rolled_back is False


class TestOrchestratorHelpers:
    """Test orchestrator helper methods"""

    @pytest.mark.asyncio
    async def test_orchestrator_get_saga_status(self):
        """Test get_saga_status method"""
        orchestrator = SagaOrchestrator()

        # Create and execute a simple saga
        saga = Saga("test-saga-status")

        async def simple_action(ctx):
            return "done"

        await saga.add_step("step1", simple_action)

        # Execute saga through orchestrator
        await orchestrator.execute_saga(saga)

        # Get status (it's an async method)
        status_data = await orchestrator.get_saga_status(saga.saga_id)
        assert status_data is not None
        assert "status" in status_data
        assert status_data["status"] == SagaStatus.COMPLETED.value


class TestStepWithoutCompensation:
    """Test saga steps without compensation functions"""

    @pytest.mark.asyncio
    async def test_step_without_compensation_execute(self):
        """Test executing step without compensation - covers core.py:103-104"""
        saga = Saga("no-comp-saga")

        executed = []

        async def action_only(ctx):
            executed.append("action")
            return "result"

        # Add step WITHOUT compensation
        await saga.add_step("no_comp_step", action_only)

        result = await saga.execute()

        assert result.success is True
        assert "action" in executed
        assert len(saga.steps) == 1
        assert saga.steps[0].compensation is None

    @pytest.mark.asyncio
    async def test_step_without_compensation_no_rollback_needed(self):
        """Test that step without compensation doesn't cause issues"""
        saga = Saga("mixed-comp-saga")

        async def step1_action(ctx):
            return "step1"

        async def step2_action(ctx):
            msg = "Step 2 fails"
            raise ValueError(msg)

        async def step2_comp(result, ctx):
            pass

        # Step 1 has NO compensation
        await saga.add_step("step1", step1_action)

        # Step 2 has compensation and will fail
        await saga.add_step("step2", step2_action, step2_comp)

        result = await saga.execute()

        # Should fail and compensate step 2, but step 1 has no compensation
        assert result.success is False


class TestWaitAllExceptionRethrow:
    """Test wait_all strategy exception re-raise - covers wait_all.py:37"""

    @pytest.mark.asyncio
    async def test_wait_all_exception_rethrow(self):
        """Test that wait_all re-raises exceptions after all complete"""
        from sagaz.exceptions import SagaStepError
        from sagaz.strategies.wait_all import WaitAllStrategy

        strategy = WaitAllStrategy()

        class FailingStep:
            def __init__(self, should_fail=False):
                self.should_fail = should_fail
                self.executed = False

            async def execute(self):
                self.executed = True
                if self.should_fail:
                    msg = "Step failed"
                    raise SagaStepError(msg)
                return {"step": "success"}

        steps = [
            FailingStep(should_fail=False),
            FailingStep(should_fail=True),  # This will fail
            FailingStep(should_fail=False),
        ]

        # Should raise exception after all steps complete
        with pytest.raises(SagaStepError):
            await strategy.execute_parallel_steps(steps)

        # Verify all steps were executed (wait_all lets them finish)
        for step in steps:
            assert step.executed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
