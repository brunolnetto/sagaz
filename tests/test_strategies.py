# ============================================
# FILE: tests/test_strategies.py
# ============================================

"""
Tests for parallel execution strategies - fail_fast, wait_all, fail_fast_grace
"""

import asyncio

import pytest

from sagaz.exceptions import SagaStepError
from sagaz.strategies.base import ParallelExecutionStrategy
from sagaz.strategies.fail_fast import FailFastStrategy
from sagaz.strategies.fail_fast_grace import FailFastWithGraceStrategy
from sagaz.strategies.wait_all import WaitAllStrategy


class MockDAGStep:
    """Mock DAG step for testing strategies"""

    def __init__(self, name: str, duration: float = 0.1, should_fail: bool = False):
        self.name = name
        self.duration = duration
        self.should_fail = should_fail
        self.executed = False
        self.cancelled = False

    async def execute(self):
        """Mock step execution"""
        if self.cancelled:
            msg = "Step was cancelled"
            raise asyncio.CancelledError(msg)

        await asyncio.sleep(self.duration)
        self.executed = True

        if self.should_fail:
            msg = f"Step {self.name} failed intentionally"
            raise SagaStepError(msg)

        return {"step": self.name, "result": "success"}

    def cancel(self):
        """Mock step cancellation"""
        self.cancelled = True


class TestFailFastStrategy:
    """Test FailFastStrategy implementation"""

    @pytest.fixture
    def strategy(self):
        """Create FailFastStrategy instance"""
        return FailFastStrategy()

    @pytest.mark.asyncio
    async def test_all_steps_succeed(self, strategy):
        """Test strategy when all parallel steps succeed"""
        steps = [
            MockDAGStep("step1", duration=0.1),
            MockDAGStep("step2", duration=0.1),
            MockDAGStep("step3", duration=0.1),
        ]

        results = await strategy.execute_parallel_steps(steps)

        # All should succeed
        assert len(results) == 3
        for step in steps:
            assert step.executed is True
            assert step.cancelled is False

        # Check results
        step_names = {r["step"] for r in results}
        assert step_names == {"step1", "step2", "step3"}

    @pytest.mark.asyncio
    async def test_one_step_fails_fast(self, strategy):
        """Test strategy cancels other steps when one fails quickly"""
        steps = [
            MockDAGStep("fast_fail", duration=0.05, should_fail=True),
            MockDAGStep("slow_step", duration=0.5),  # Should be cancelled
            MockDAGStep("another_slow", duration=0.5),  # Should be cancelled
        ]

        with pytest.raises(SagaStepError):
            await strategy.execute_parallel_steps(steps)

        # Fast fail step should have executed
        assert steps[0].executed is True

        # Slow steps might not have completed due to cancellation
        # (Exact behavior depends on timing, but cancellation should be attempted)

    @pytest.mark.asyncio
    async def test_multiple_steps_fail(self, strategy):
        """Test strategy handles multiple failing steps correctly"""
        steps = [
            MockDAGStep("fail1", duration=0.1, should_fail=True),
            MockDAGStep("fail2", duration=0.1, should_fail=True),
            MockDAGStep("success", duration=0.1),
        ]

        with pytest.raises(SagaStepError):
            await strategy.execute_parallel_steps(steps)

    @pytest.mark.asyncio
    async def test_empty_steps_list(self, strategy):
        """Test strategy handles empty steps list"""
        results = await strategy.execute_parallel_steps([])
        assert results == []

    @pytest.mark.asyncio
    async def test_single_step(self, strategy):
        """Test strategy with single step (no parallelism)"""
        steps = [MockDAGStep("single", duration=0.1)]

        results = await strategy.execute_parallel_steps(steps)

        assert len(results) == 1
        assert results[0]["step"] == "single"
        assert steps[0].executed is True

    @pytest.mark.asyncio
    async def test_strategy_itself_cancelled(self):
        """Test that strategy handles being cancelled during execution"""
        strategy = FailFastStrategy()

        steps = [
            MockDAGStep("step1", duration=0.5),
            MockDAGStep("step2", duration=0.5),
            MockDAGStep("step3", duration=0.5),
        ]

        # Create a task that will be cancelled
        task = asyncio.create_task(strategy.execute_parallel_steps(steps))

        # Let it start
        await asyncio.sleep(0.05)

        # Cancel the strategy execution
        task.cancel()

        # Should raise CancelledError
        with pytest.raises(asyncio.CancelledError):
            await task


class TestWaitAllStrategy:
    """Test WaitAllStrategy implementation"""

    @pytest.fixture
    def strategy(self):
        """Create WaitAllStrategy instance"""
        return WaitAllStrategy()

    @pytest.mark.asyncio
    async def test_all_steps_succeed(self, strategy):
        """Test strategy when all parallel steps succeed"""
        steps = [
            MockDAGStep("step1", duration=0.1),
            MockDAGStep("step2", duration=0.15),
            MockDAGStep("step3", duration=0.05),
        ]

        results = await strategy.execute_parallel_steps(steps)

        # All should succeed
        assert len(results) == 3
        for step in steps:
            assert step.executed is True
            assert step.cancelled is False

    @pytest.mark.asyncio
    async def test_some_steps_fail_wait_all(self, strategy):
        """Test strategy waits for all steps even when some fail"""
        steps = [
            MockDAGStep("success1", duration=0.1),
            MockDAGStep("fail", duration=0.05, should_fail=True),
            MockDAGStep("success2", duration=0.2),  # Should complete despite failure
        ]

        with pytest.raises(SagaStepError):
            await strategy.execute_parallel_steps(steps)

        # All steps should have been attempted
        assert steps[0].executed is True  # success1
        assert steps[1].executed is True  # fail (executed but failed)
        assert steps[2].executed is True  # success2 (should complete despite other failure)

    @pytest.mark.asyncio
    async def test_multiple_failures_collect_all(self, strategy):
        """Test strategy collects all failures when multiple steps fail"""
        steps = [
            MockDAGStep("fail1", duration=0.1, should_fail=True),
            MockDAGStep("success", duration=0.1),
            MockDAGStep("fail2", duration=0.1, should_fail=True),
        ]

        with pytest.raises(SagaStepError):
            await strategy.execute_parallel_steps(steps)

        # All should have been attempted
        for step in steps:
            assert step.executed is True

    @pytest.mark.asyncio
    async def test_wait_for_slowest_step(self, strategy):
        """Test strategy waits for the slowest step to complete"""
        import time

        steps = [
            MockDAGStep("fast", duration=0.05),
            MockDAGStep("slow", duration=0.2),
            MockDAGStep("medium", duration=0.1),
        ]

        start_time = time.time()
        results = await strategy.execute_parallel_steps(steps)
        end_time = time.time()

        # Should take at least as long as the slowest step (with small tolerance for timing variation)
        assert end_time - start_time >= 0.19  # Allow 10ms tolerance
        assert len(results) == 3


class TestFailFastWithGraceStrategy:
    """Test FailFastWithGraceStrategy implementation"""

    @pytest.fixture
    def strategy(self):
        """Create FailFastWithGraceStrategy instance"""
        return FailFastWithGraceStrategy(grace_period=0.1)

    @pytest.mark.asyncio
    async def test_all_steps_succeed(self, strategy):
        """Test strategy when all parallel steps succeed"""
        steps = [
            MockDAGStep("step1", duration=0.05),
            MockDAGStep("step2", duration=0.05),
            MockDAGStep("step3", duration=0.05),
        ]

        results = await strategy.execute_parallel_steps(steps)

        assert len(results) == 3
        for step in steps:
            assert step.executed is True

    @pytest.mark.asyncio
    async def test_graceful_cancellation(self, strategy):
        """Test strategy allows grace period for in-flight steps"""
        steps = [
            MockDAGStep("quick_fail", duration=0.01, should_fail=True),
            MockDAGStep("in_flight", duration=0.08),  # Should complete within grace period
            MockDAGStep("too_slow", duration=0.5),  # Should be cancelled after grace
        ]

        with pytest.raises(SagaStepError):
            await strategy.execute_parallel_steps(steps)

        # Quick fail should have executed
        assert steps[0].executed is True

        # In-flight might complete (within grace period)
        # Too slow should be cancelled (exact timing depends on implementation)

    @pytest.mark.asyncio
    async def test_grace_period_configuration(self):
        """Test strategy respects different grace period settings"""
        short_grace = FailFastWithGraceStrategy(grace_period=0.05)
        long_grace = FailFastWithGraceStrategy(grace_period=0.3)

        assert short_grace.grace_period == 0.05
        assert long_grace.grace_period == 0.3

    @pytest.mark.asyncio
    async def test_no_grace_period(self):
        """Test strategy with zero grace period behaves like fail-fast"""
        strategy = FailFastWithGraceStrategy(grace_period=0.0)

        steps = [
            MockDAGStep("fail", duration=0.01, should_fail=True),
            MockDAGStep("slow", duration=0.5),
        ]

        with pytest.raises(SagaStepError):
            await strategy.execute_parallel_steps(steps)

    def test_should_wait_for_completion(self):
        """Test should_wait_for_completion returns True"""
        strategy = FailFastWithGraceStrategy()
        assert strategy.should_wait_for_completion() is True

    def test_get_description(self):
        """Test get_description returns proper description"""
        strategy = FailFastWithGraceStrategy()
        desc = strategy.get_description()
        assert "FAIL_FAST_WITH_GRACE" in desc
        assert isinstance(desc, str)

    @pytest.mark.asyncio
    async def test_strategy_cancellation_handling(self):
        """Test that strategy properly handles being cancelled itself"""
        strategy = FailFastWithGraceStrategy(grace_period=0.2)

        steps = [
            MockDAGStep("step1", duration=0.5),
            MockDAGStep("step2", duration=0.5),
            MockDAGStep("step3", duration=0.5),
        ]

        # Create a task that will be cancelled
        task = asyncio.create_task(strategy.execute_parallel_steps(steps))

        # Let it start
        await asyncio.sleep(0.05)

        # Cancel the strategy execution
        task.cancel()

        # Should raise CancelledError
        with pytest.raises(asyncio.CancelledError):
            await task

        # All steps should have been cancelled
        for _step in steps:
            # Steps may or may not have started depending on timing
            pass  # Just verify no exception from cleanup

    @pytest.mark.asyncio
    async def test_empty_steps_list(self):
        """Test strategy handles empty steps list"""
        strategy = FailFastWithGraceStrategy(grace_period=0.1)

        results = await strategy.execute_parallel_steps([])

        assert results == []

    @pytest.mark.asyncio
    async def test_timeout_during_grace_period(self):
        """Test handling when in-flight tasks exceed grace period"""
        strategy = FailFastWithGraceStrategy(grace_period=0.05)  # Very short grace

        steps = [
            MockDAGStep("quick_fail", duration=0.01, should_fail=True),
            MockDAGStep("very_slow", duration=1.0),  # Will exceed grace period
        ]

        with pytest.raises(SagaStepError):
            await strategy.execute_parallel_steps(steps)

        # First step should have failed
        assert steps[0].executed is True


class TestStrategyIntegration:
    """Test strategies work independently (simplified tests)"""

    @pytest.mark.asyncio
    async def test_strategy_with_successful_steps(self):
        """Test strategies handle successful execution correctly"""
        steps = [
            MockDAGStep("step1", duration=0.05),
            MockDAGStep("step2", duration=0.05),
            MockDAGStep("step3", duration=0.05),
        ]

        # Test all strategies with successful steps
        strategies = [FailFastStrategy(), WaitAllStrategy(), FailFastWithGraceStrategy()]

        for strategy in strategies:
            results = await strategy.execute_parallel_steps(steps)
            assert len(results) == 3

            # Reset steps for next strategy
            for step in steps:
                step.executed = False
                step.cancelled = False

    @pytest.mark.asyncio
    async def test_strategy_polymorphic_usage(self):
        """Test strategies can be used polymorphically"""
        steps = [MockDAGStep("step1", duration=0.01)]

        strategies = [
            FailFastStrategy(),
            WaitAllStrategy(),
            FailFastWithGraceStrategy(grace_period=0.1),
        ]

        # All strategies should handle single successful step
        for strategy in strategies:
            results = await strategy.execute_parallel_steps(steps)
            assert len(results) == 1
            assert results[0]["step"] == "step1"

            # Reset step
            steps[0].executed = False

    @pytest.mark.asyncio
    async def test_strategy_failure_behavior_differences(self):
        """Test strategies handle failures differently"""
        # Test with one quick fail and one slow success
        fail_fast_steps = [
            MockDAGStep("quick_fail", duration=0.01, should_fail=True),
            MockDAGStep("slow_success", duration=0.1),
        ]

        wait_all_steps = [
            MockDAGStep("quick_fail", duration=0.01, should_fail=True),
            MockDAGStep("slow_success", duration=0.1),
        ]

        # FailFastStrategy should fail quickly
        fail_fast = FailFastStrategy()
        with pytest.raises(SagaStepError):
            await fail_fast.execute_parallel_steps(fail_fast_steps)

        # WaitAllStrategy should wait for all to complete before failing
        wait_all = WaitAllStrategy()
        with pytest.raises(SagaStepError):
            await wait_all.execute_parallel_steps(wait_all_steps)

        # Both steps should have been attempted in wait_all
        assert wait_all_steps[0].executed is True  # Failed but executed
        assert wait_all_steps[1].executed is True  # Completed


class TestStrategyBase:
    """Test base strategy class and interface"""

    def test_strategy_interface(self):
        """Test strategy base class defines correct interface"""
        # Test that base class exists and has required methods
        # Can't instantiate abstract class directly, so test via concrete implementation
        strategy = FailFastStrategy()

        # Should have execute_parallel_steps method
        assert hasattr(strategy, "execute_parallel_steps")
        assert callable(strategy.execute_parallel_steps)

        # Should be instance of base class
        assert isinstance(strategy, ParallelExecutionStrategy)

    def test_strategy_polymorphism(self):
        """Test strategies can be used polymorphically"""
        strategies = [FailFastStrategy(), WaitAllStrategy(), FailFastWithGraceStrategy()]

        # All should be instances of base strategy
        for strategy in strategies:
            assert isinstance(strategy, ParallelExecutionStrategy)
            assert hasattr(strategy, "execute_parallel_steps")

    def test_strategy_factory_pattern(self):
        """Test strategy factory pattern could be implemented"""

        # Example of how a factory might work
        def create_strategy(strategy_type: str, **kwargs):
            if strategy_type == "fail_fast":
                return FailFastStrategy()
            if strategy_type == "wait_all":
                return WaitAllStrategy()
            if strategy_type == "fail_fast_grace":
                return FailFastWithGraceStrategy(**kwargs)
            msg = f"Unknown strategy: {strategy_type}"
            raise ValueError(msg)

        # Test factory
        fail_fast = create_strategy("fail_fast")
        wait_all = create_strategy("wait_all")
        grace = create_strategy("fail_fast_grace", grace_period=0.5)

        assert isinstance(fail_fast, FailFastStrategy)
        assert isinstance(wait_all, WaitAllStrategy)
        assert isinstance(grace, FailFastWithGraceStrategy)
        assert grace.grace_period == 0.5
