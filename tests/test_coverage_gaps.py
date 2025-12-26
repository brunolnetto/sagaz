"""
Tests to achieve 100% coverage by covering edge cases and remaining gaps

This file specifically targets the uncovered lines identified in coverage report.
"""

import pytest
import asyncio
import logging
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from sagaz.core import Saga, SagaContext, SagaStep, _StepExecutor
from sagaz.types import SagaStatus, SagaStepStatus, ParallelFailureStrategy, SagaResult
from sagaz.exceptions import SagaExecutionError, SagaStepError


# ==============================================
# Tests forsagaz/core.py - _StepExecutor
# ==============================================

class TestStepExecutor:
    """Tests for _StepExecutor class to cover lines 103-104, 108"""
    
    @pytest.mark.asyncio
    async def test_step_executor_compensate_no_compensation(self):
        """Test _StepExecutor.compensate when step has no compensation function"""
        # Create a step with no compensation
        step = SagaStep(
            name="test_step",
            action=lambda ctx: "result",
            compensation=None
        )
        
        context = SagaContext()
        executor = _StepExecutor(step, context)
        executor.result = {"data": "test"}
        
        # Should not raise, just return None
        await executor.compensate()
    
    @pytest.mark.asyncio
    async def test_step_executor_compensate_with_compensation(self):
        """Test _StepExecutor.compensate when step has compensation function"""
        compensation_called = []
        
        async def mock_compensation(result, ctx):
            compensation_called.append(result)
        
        step = SagaStep(
            name="test_step",
            action=lambda ctx: "result",
            compensation=mock_compensation
        )
        
        context = SagaContext()
        executor = _StepExecutor(step, context)
        executor.result = {"data": "test"}
        
        await executor.compensate()
        
        assert len(compensation_called) == 1
        assert compensation_called[0] == {"data": "test"}
    
    def test_step_executor_name_property(self):
        """Test _StepExecutor.name property"""
        step = SagaStep(
            name="my_unique_step",
            action=lambda ctx: None
        )
        
        context = SagaContext()
        executor = _StepExecutor(step, context)
        
        assert executor.name == "my_unique_step"


# ==============================================
# Tests forsagaz/core.py - Saga duplicate method (lines 254-255, 392-395)
# ==============================================

class TestSagaDuplicateMethod:
    """Tests for set_failure_strategy (duplicated at lines 252-255 and 392-395)"""
    
    @pytest.mark.asyncio
    async def test_set_failure_strategy_first_definition(self):
        """Test the first set_failure_strategy definition"""
        saga = Saga(name="TestSaga")
        
        # Call set_failure_strategy before execute
        saga.set_failure_strategy(ParallelFailureStrategy.WAIT_ALL)
        
        assert saga.failure_strategy == ParallelFailureStrategy.WAIT_ALL
    
    @pytest.mark.asyncio
    async def test_set_failure_strategy_fail_fast(self):
        """Test setting FAIL_FAST strategy"""
        saga = Saga(name="TestSaga")
        saga.set_failure_strategy(ParallelFailureStrategy.FAIL_FAST)
        
        assert saga.failure_strategy == ParallelFailureStrategy.FAIL_FAST


# ==============================================
# Tests forsagaz/core.py - _build_execution_batches (lines 282-287)
# ==============================================

class TestBuildExecutionBatches:
    """Tests for circular/missing dependency detection in _build_execution_batches"""
    
    @pytest.mark.asyncio
    async def test_circular_dependency_detection(self):
        """Test that circular dependencies are detected during build"""
        saga = Saga(name="CircularSaga")
        
        # Create circular dependency: A -> B -> A
        await saga.add_step(
            name="step_a",
            action=lambda ctx: "a",
            dependencies={"step_b"}
        )
        await saga.add_step(
            name="step_b",
            action=lambda ctx: "b",
            dependencies={"step_a"}
        )
        
        # Execute should fail during planning phase
        result = await saga.execute()
        
        assert result.success is False
        assert result.status == SagaStatus.FAILED
        assert "Circular" in str(result.error) or "dependencies" in str(result.error)
    
    @pytest.mark.asyncio
    async def test_missing_dependency_detection(self):
        """Test that missing dependencies are detected"""
        saga = Saga(name="MissingDepSaga")
        
        # Create step that depends on non-existent step
        await saga.add_step(
            name="step_a",
            action=lambda ctx: "a",
            dependencies={"nonexistent_step"}
        )
        
        result = await saga.execute()
        
        assert result.success is False
        assert result.status == SagaStatus.FAILED


# ==============================================
# Tests forsagaz/core.py - DAG exception handling (lines 378-390)
# ==============================================

class TestDAGExceptionHandling:
    """Tests for DAG execution exception handling"""
    
    @pytest.mark.asyncio
    async def test_dag_execution_unexpected_exception(self):
        """Test DAG handles unexpected exceptions during batch building"""
        saga = Saga(name="ExceptionSaga")
        
        async def failing_action(ctx):
            raise RuntimeError("Unexpected error")
        
        await saga.add_step(
            name="step_a",
            action=failing_action,
            dependencies=set()  # Explicit DAG mode
        )
        
        result = await saga.execute()
        
        assert result.success is False
        # Should be rolled back or failed
        assert result.status in [SagaStatus.ROLLED_BACK, SagaStatus.FAILED]


# ==============================================
# Tests forsagaz/core.py - SagaStep __hash__ (line 791)
# ==============================================

class TestSagaStepHash:
    """Tests for SagaStep.__hash__ method"""
    
    def test_saga_step_hash(self):
        """Test that SagaStep can be hashed using idempotency_key"""
        step1 = SagaStep(
            name="step1",
            action=lambda ctx: None,
            idempotency_key="key-123"
        )
        
        step2 = SagaStep(
            name="step2",
            action=lambda ctx: None,
            idempotency_key="key-456"
        )
        
        step3 = SagaStep(
            name="step3",
            action=lambda ctx: None,
            idempotency_key="key-123"  # Same key as step1
        )
        
        # Steps with different idempotency keys should have different hashes
        assert hash(step1) != hash(step2)
        
        # Steps with same idempotency key should have same hash
        assert hash(step1) == hash(step3)
        
        # Should be usable in sets
        step_set = {step1, step2}
        assert len(step_set) == 2


# ==============================================
# Tests forsagaz/core.py - Saga already executing (line 413)
# ==============================================

class TestSagaAlreadyExecuting:
    """Tests for saga already executing check"""
    
    @pytest.mark.asyncio
    async def test_saga_already_executing_error(self):
        """Test that concurrent execution raises error"""
        saga = Saga(name="ConcurrentSaga")
        
        await saga.add_step(
            name="simple_step",
            action=lambda ctx: "done"
        )
        
        # Manually set the _executing flag to simulate already executing
        # This is a simpler way to test the guard clause without async race conditions
        async with saga._execution_lock:
            saga._executing = True
        
        # Try to execute - should raise because _executing is True
        with pytest.raises(SagaExecutionError, match="already executing"):
            await saga.execute()
        
        # Reset and verify normal execution works
        async with saga._execution_lock:
            saga._executing = False
        
        result = await saga.execute()
        assert result.success is True


# ==============================================
# Tests forsagaz/monitoring/logging.py - extra record attributes (lines 55, 57, 59)
# ==============================================

class TestSagaJsonFormatterExtraAttributes:
    """Tests for SagaJsonFormatter handling of extra record attributes"""
    
    def test_formatter_with_all_extra_attributes(self):
        """Test formatter includes all extra attributes when present"""
        from sagaz.monitoring.logging import SagaJsonFormatter
        import json
        
        formatter = SagaJsonFormatter()
        
        # Create a log record with extra saga attributes
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        # Add extra saga-related attributes
        record.saga_id = "saga-extra-123"
        record.saga_name = "ExtraSaga"
        record.step_name = "extra_step"
        record.correlation_id = "corr-456"
        record.duration_ms = 100.5
        record.retry_count = 2
        record.error_type = "ValidationError"
        
        output = formatter.format(record)
        log_data = json.loads(output)
        
        assert log_data["saga_id"] == "saga-extra-123"
        assert log_data["saga_name"] == "ExtraSaga"
        assert log_data["step_name"] == "extra_step"
        assert log_data["correlation_id"] == "corr-456"
        assert log_data["duration_ms"] == 100.5
        assert log_data["retry_count"] == 2
        assert log_data["error_type"] == "ValidationError"


# ==============================================
# Tests forsagaz/monitoring/logging.py - setup_saga_logging (lines 319-323)
# ==============================================

class TestSetupSagaLogging:
    """Tests for setup_saga_logging function"""
    
    def test_setup_with_no_json_format(self):
        """Test setup_saga_logging with json_format=False"""
        from sagaz.monitoring.logging import setup_saga_logging, SagaLogger
        
        logger = setup_saga_logging(
            log_level="DEBUG",
            json_format=False,
            include_console=True
        )
        
        assert isinstance(logger, SagaLogger)
    
    def test_setup_with_no_console(self):
        """Test setup_saga_logging with include_console=False"""
        from sagaz.monitoring.logging import setup_saga_logging, SagaLogger
        
        logger = setup_saga_logging(
            log_level="INFO",
            json_format=True,
            include_console=False
        )
        
        assert isinstance(logger, SagaLogger)


# ==============================================
# Tests forsagaz/strategies/wait_all.py (line 37)
# ==============================================

class TestWaitAllEmptySteps:
    """Tests for WaitAllStrategy with empty steps list"""
    
    @pytest.mark.asyncio
    async def test_wait_all_empty_steps(self):
        """Test WaitAllStrategy with empty steps returns empty list"""
        from sagaz.strategies.wait_all import WaitAllStrategy
        
        strategy = WaitAllStrategy()
        result = await strategy.execute_parallel_steps([])
        
        assert result == []


# ==============================================
# Tests forsagaz/strategies/fail_fast_grace.py (line 77)
# ==============================================

class TestFailFastGraceEdgeCases:
    """Tests for FailFastWithGraceStrategy edge cases"""
    
    @pytest.mark.asyncio
    async def test_fail_fast_grace_task_timeout(self):
        """Test FailFastWithGraceStrategy when tasks timeout during grace period"""
        from sagaz.strategies.fail_fast_grace import FailFastWithGraceStrategy
        
        class MockExecutor:
            def __init__(self, name, delay, should_fail=False):
                self.name = name
                self.delay = delay
                self.should_fail = should_fail
                self.completed = False
            
            async def execute(self):
                await asyncio.sleep(self.delay)
                if self.should_fail:
                    raise ValueError(f"{self.name} failed")
                self.completed = True
                return f"{self.name} result"
        
        strategy = FailFastWithGraceStrategy(grace_period=0.05)
        
        # First task fails quickly, second takes longer than grace period
        executors = [
            MockExecutor("fast_fail", 0.01, should_fail=True),
            MockExecutor("slow_success", 0.5)  # Longer than grace period
        ]
        
        with pytest.raises(ValueError, match="fast_fail failed"):
            await strategy.execute_parallel_steps(executors)


# ==============================================
# Tests forsagaz/orchestrator.py (line 64)
# ==============================================

class TestOrchestratorCountRolledBack:
    """Tests for SagaOrchestrator.count_rolled_back method"""
    
    @pytest.mark.asyncio
    async def test_count_rolled_back(self):
        """Test counting rolled back sagas"""
        from sagaz.orchestrator import SagaOrchestrator
        
        orchestrator = SagaOrchestrator()
        
        # Create a saga that will be rolled back
        saga = Saga(name="RollingBackSaga")
        
        async def failing_action(ctx):
            raise ValueError("Force failure")
        
        async def compensation(result, ctx):
            pass
        
        await saga.add_step(
            name="succeeding_step",
            action=lambda ctx: "success",
            compensation=compensation
        )
        
        await saga.add_step(
            name="failing_step",
            action=failing_action
        )
        
        await orchestrator.execute_saga(saga)
        
        count = await orchestrator.count_rolled_back()
        assert count >= 1


# ==============================================
# Tests forsagaz/state_machine.py (line 23)
# ==============================================

class TestStateMachineTypeChecking:
    """Tests for state machine TYPE_CHECKING import"""
    
    def test_state_machine_imports(self):
        """Test state machine module imports correctly"""
        from sagaz.state_machine import SagaStateMachine, SagaStepStateMachine
        from sagaz.state_machine import validate_state_transition, get_valid_next_states
        
        # Validate state transition function works
        assert validate_state_transition("Pending", "Executing") is True
        assert validate_state_transition("Pending", "Completed") is False
        
        # Get valid next states
        next_states = get_valid_next_states("Executing")
        assert "Completed" in next_states
        assert "Compensating" in next_states


# ==============================================
# Tests forsagaz/storage/base.py (line 200->203)
# ==============================================

class TestSagaStepStateFromDict:
    """Tests for SagaStepState.from_dict edge cases"""
    
    def test_from_dict_without_optional_fields(self):
        """Test creating SagaStepState from dict without optional fields"""
        from sagaz.storage.base import SagaStepState
        
        minimal_dict = {
            "name": "minimal_step",
            "status": "pending"
        }
        
        state = SagaStepState.from_dict(minimal_dict)
        
        assert state.name == "minimal_step"
        assert state.status == SagaStepStatus.PENDING
        assert state.result is None
        assert state.executed_at is None
        assert state.retry_count == 0


# ==============================================
# Tests forsagaz/storage/memory.py (lines 133, 167, 179, 184)
# ==============================================

class TestInMemoryStorageEdgeCases:
    """Tests for InMemorySagaStorage edge cases"""
    
    @pytest.mark.asyncio
    async def test_update_step_with_executed_at(self):
        """Test updating step state with executed_at timestamp"""
        from sagaz.storage.memory import InMemorySagaStorage
        
        storage = InMemorySagaStorage()
        
        await storage.save_saga_state(
            saga_id="timestamp-test",
            saga_name="TimestampSaga",
            status=SagaStatus.EXECUTING,
            steps=[{"name": "step1", "status": "pending", "result": None, "error": None}],
            context={}
        )
        
        # Update with executed_at
        await storage.update_step_state(
            saga_id="timestamp-test",
            step_name="step1",
            status=SagaStepStatus.COMPLETED,
            result={"data": "test"},
            executed_at=datetime.now(timezone.utc)
        )
        
        loaded = await storage.load_saga_state("timestamp-test")
        assert loaded["steps"][0]["executed_at"] is not None
    
    @pytest.mark.asyncio
    async def test_cleanup_with_various_statuses(self):
        """Test cleanup with different saga statuses"""
        from sagaz.storage.memory import InMemorySagaStorage
        
        storage = InMemorySagaStorage()
        
        # Create sagas with different statuses
        statuses = [
            ("saga-completed", SagaStatus.COMPLETED),
            ("saga-rolled-back", SagaStatus.ROLLED_BACK),
            ("saga-executing", SagaStatus.EXECUTING),
            ("saga-failed", SagaStatus.FAILED),
        ]
        
        for saga_id, status in statuses:
            await storage.save_saga_state(
                saga_id=saga_id,
                saga_name="Test",
                status=status,
                steps=[],
                context={}
            )
        
        # Small delay to ensure timestamps are older
        await asyncio.sleep(0.1)
        
        # Cleanup completed and rolled_back (default)
        deleted = await storage.cleanup_completed_sagas(
            older_than=datetime.now(timezone.utc)
        )
        
        # Should only delete completed and rolled_back
        assert deleted == 2
        
        # Executing and failed should still exist
        assert await storage.load_saga_state("saga-executing") is not None
        assert await storage.load_saga_state("saga-failed") is not None


# ==============================================
# Tests forsagaz/metrics.py (line 34->38)
# ==============================================

class TestMetrics:
    """Tests for metrics module"""
    
    def test_saga_metrics_exist(self):
        """Test that SagaMetrics can be imported and used"""
        from sagaz.monitoring.metrics import SagaMetrics
        from sagaz.types import SagaStatus
        
        metrics = SagaMetrics()
        
        # Record some executions  
        metrics.record_execution("TestSaga", SagaStatus.COMPLETED, 0.5)
        metrics.record_execution("TestSaga", SagaStatus.FAILED, 0.3)
        metrics.record_execution("TestSaga", SagaStatus.ROLLED_BACK, 0.4)
        metrics.record_execution("OtherSaga", SagaStatus.COMPLETED, 0.2)
        
        # Get metrics
        result = metrics.get_metrics()
        
        assert result["total_executed"] == 4
        assert result["total_successful"] == 2
        assert result["total_failed"] == 1
        assert result["total_rolled_back"] == 1
        assert "TestSaga" in result["by_saga_name"]
        assert "OtherSaga" in result["by_saga_name"]
        assert "success_rate" in result
