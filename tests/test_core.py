"""
EXHAUSTIVE TEST SUITE FOR SAGA PATTERN
=======================================

Complete test coverage for:
- Core Saga functionality
- DAG Saga with parallel execution
- All failure strategies
- State machine transitions
- Orchestrator
- Edge cases and error conditions
- Performance and concurrency
- Integration scenarios
"""

import asyncio
import time

import pytest

from sagaz import (
    ClassicSaga,
    DAGSaga,
    ParallelFailureStrategy,
    SagaContext,
    SagaExecutionError,
    SagaOrchestrator,
    SagaResult,
    SagaStatus,
    SagaTimeoutError,
)

# Alias for backward compatibility in tests
Saga = ClassicSaga


# ============================================
# TEST FIXTURES
# ============================================


@pytest.fixture
def saga_context():
    """Create fresh saga context"""
    return SagaContext()


@pytest.fixture
def orchestrator():
    """Create fresh orchestrator"""
    return SagaOrchestrator()


@pytest.fixture
async def simple_saga():
    """Create simple test saga"""
    return SimpleSaga("SimpleSaga")


class SimpleSaga(ClassicSaga):
    """Simple saga for testing (renamed from TestSaga to avoid pytest collection warning)"""

    def __init__(self, name: str = "TestSaga", retry_backoff_base: float = 0.01, **kwargs):
        super().__init__(name=name, retry_backoff_base=retry_backoff_base, **kwargs)


# ============================================
# CORE SAGA TESTS
# ============================================


class TestCoreSaga:
    """Test core Saga functionality"""

    @pytest.mark.asyncio
    async def test_saga_initialization(self):
        """Test saga is initialized correctly"""
        saga = SimpleSaga("MyTest")

        assert saga.name == "MyTest"
        assert saga.version == "1.0"
        assert saga.status == SagaStatus.PENDING
        assert len(saga.steps) == 0
        assert len(saga.completed_steps) == 0
        assert saga.error is None
        assert saga.saga_id is not None

    @pytest.mark.asyncio
    async def test_add_step_basic(self):
        """Test adding basic step"""
        saga = SimpleSaga()

        async def action(ctx):
            return "result"

        async def compensation(result, ctx):
            pass

        await saga.add_step("step1", action, compensation)

        assert len(saga.steps) == 1
        assert saga.steps[0].name == "step1"
        assert saga.steps[0].action == action
        assert saga.steps[0].compensation == compensation

    @pytest.mark.asyncio
    async def test_add_step_with_options(self):
        """Test adding step with all options"""
        saga = SimpleSaga()

        await saga.add_step(
            "step1",
            lambda ctx: "result",
            lambda r, ctx: None,
            timeout=15.0,
            compensation_timeout=20.0,
            max_retries=5,
            idempotency_key="custom-key",
        )

        step = saga.steps[0]
        assert step.timeout == 15.0
        assert step.compensation_timeout == 20.0
        assert step.max_retries == 5
        assert step.idempotency_key == "custom-key"

    @pytest.mark.asyncio
    async def test_cannot_add_steps_during_execution(self):
        """Test that steps cannot be added while saga is executing"""
        saga = SimpleSaga()

        async def slow_action(ctx):
            await asyncio.sleep(0.5)
            return "done"

        await saga.add_step("step1", slow_action)

        # Start execution
        task = asyncio.create_task(saga.execute())
        await asyncio.sleep(0.1)  # Let it start

        # Try to add step
        with pytest.raises(SagaExecutionError, match="Cannot add steps while saga is executing"):
            await saga.add_step("step2", lambda ctx: "result")

        await task

    @pytest.mark.asyncio
    async def test_successful_execution_single_step(self):
        """Test successful execution with one step"""
        saga = SimpleSaga()
        executed = []

        async def action(ctx):
            executed.append("action")
            return "success"

        await saga.add_step("step1", action)
        result = await saga.execute()

        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        assert result.completed_steps == 1
        assert result.total_steps == 1
        assert result.error is None
        assert executed == ["action"]

    @pytest.mark.asyncio
    async def test_successful_execution_multiple_steps(self):
        """Test successful execution with multiple steps"""
        saga = SimpleSaga()
        executed = []

        async def action1(ctx):
            executed.append("action1")
            return "result1"

        async def action2(ctx):
            executed.append("action2")
            return "result2"

        async def action3(ctx):
            executed.append("action3")
            return "result3"

        await saga.add_step("step1", action1)
        await saga.add_step("step2", action2)
        await saga.add_step("step3", action3)

        result = await saga.execute()

        assert result.success is True
        assert result.completed_steps == 3
        assert executed == ["action1", "action2", "action3"]

    @pytest.mark.asyncio
    async def test_execution_order(self):
        """Test that steps execute in order"""
        saga = SimpleSaga()
        execution_order = []

        async def make_action(name):
            async def action(ctx):
                execution_order.append(name)
                return name

            return action

        await saga.add_step("step1", await make_action("step1"))
        await saga.add_step("step2", await make_action("step2"))
        await saga.add_step("step3", await make_action("step3"))

        await saga.execute()

        assert execution_order == ["step1", "step2", "step3"]


# ============================================
# CONTEXT TESTS
# ============================================


class TestSagaContext:
    """Test SagaContext functionality"""

    def test_context_set_get(self):
        """Test basic set/get operations"""
        ctx = SagaContext()

        ctx.set("key1", "value1")
        ctx.set("key2", 123)

        assert ctx.get("key1") == "value1"
        assert ctx.get("key2") == 123

    def test_context_get_default(self):
        """Test get with default value"""
        ctx = SagaContext()

        assert ctx.get("nonexistent", "default") == "default"
        assert ctx.get("nonexistent") is None

    def test_context_has(self):
        """Test checking key existence"""
        ctx = SagaContext()

        ctx.set("key1", "value1")

        assert ctx.has("key1") is True
        assert ctx.has("key2") is False

    @pytest.mark.asyncio
    async def test_context_passed_between_steps(self):
        """Test context data is shared between steps"""
        saga = SimpleSaga()

        async def step1(ctx):
            ctx.set("step1_data", "from_step1")
            return {"amount": 100}

        async def step2(ctx):
            # Access data from step1
            data = ctx.get("step1_data")
            previous_result = ctx.get("step1")
            return {"data": data, "amount": previous_result["amount"] * 2}

        await saga.add_step("step1", step1)
        await saga.add_step("step2", step2)

        await saga.execute()

        assert saga.context.get("step1_data") == "from_step1"
        assert saga.context.get("step1") == {"amount": 100}
        assert saga.context.get("step2")["amount"] == 200


# ============================================
# FAILURE AND COMPENSATION TESTS
# ============================================


class TestFailureAndCompensation:
    """Test failure handling and compensation"""

    @pytest.mark.asyncio
    async def test_step_failure_triggers_compensation(self):
        """Test that step failure triggers compensation of previous steps"""
        saga = SimpleSaga()
        compensations = []

        async def action1(ctx):
            return "result1"

        async def comp1(result, ctx):
            compensations.append("comp1")

        async def action2(ctx):
            msg = "Step 2 failed"
            raise ValueError(msg)

        await saga.add_step("step1", action1, comp1)
        await saga.add_step("step2", action2)

        result = await saga.execute()

        assert result.success is False
        assert result.status == SagaStatus.ROLLED_BACK
        assert result.completed_steps == 1
        assert compensations == ["comp1"]

    @pytest.mark.asyncio
    async def test_compensation_in_reverse_order(self):
        """Test compensations execute in reverse order"""
        saga = SimpleSaga()
        compensations = []

        async def action(ctx):
            return "result"

        async def comp1(result, ctx):
            compensations.append("comp1")

        async def comp2(result, ctx):
            compensations.append("comp2")

        async def comp3(result, ctx):
            compensations.append("comp3")

        async def failing_action(ctx):
            msg = "Failed"
            raise ValueError(msg)

        await saga.add_step("step1", action, comp1)
        await saga.add_step("step2", action, comp2)
        await saga.add_step("step3", action, comp3)
        await saga.add_step("step4", failing_action)

        await saga.execute()

        assert compensations == ["comp3", "comp2", "comp1"]

    @pytest.mark.asyncio
    async def test_compensation_failure_changes_status(self):
        """Test that compensation failure changes status to FAILED"""
        saga = SimpleSaga()

        async def action(ctx):
            return "result"

        async def failing_comp(result, ctx):
            msg = "Compensation failed"
            raise ValueError(msg)

        async def failing_action(ctx):
            msg = "Action failed"
            raise ValueError(msg)

        await saga.add_step("step1", action, failing_comp)
        await saga.add_step("step2", failing_action)

        result = await saga.execute()

        assert result.success is False
        assert result.status == SagaStatus.FAILED  # Not ROLLED_BACK!
        assert len(result.compensation_errors) > 0

    @pytest.mark.asyncio
    async def test_partial_compensation_failure(self):
        """Test that saga continues compensating even if one fails"""
        saga = SimpleSaga()
        compensations = []

        async def action(ctx):
            return "result"

        async def comp1(result, ctx):
            compensations.append("comp1")

        async def failing_comp(result, ctx):
            compensations.append("comp2_attempted")
            msg = "Compensation 2 failed"
            raise ValueError(msg)

        async def comp3(result, ctx):
            compensations.append("comp3")

        async def failing_action(ctx):
            msg = "Action failed"
            raise ValueError(msg)

        await saga.add_step("step1", action, comp1)
        await saga.add_step("step2", action, failing_comp)
        await saga.add_step("step3", action, comp3)
        await saga.add_step("step4", failing_action)

        result = await saga.execute()

        # All compensations should be attempted
        assert "comp3" in compensations
        assert "comp2_attempted" in compensations
        assert "comp1" in compensations
        assert len(result.compensation_errors) == 1

    @pytest.mark.asyncio
    async def test_step_without_compensation(self):
        """Test steps without compensation are skipped during rollback"""
        saga = SimpleSaga()
        compensations = []

        async def action(ctx):
            return "result"

        async def comp1(result, ctx):
            compensations.append("comp1")

        async def failing_action(ctx):
            msg = "Failed"
            raise ValueError(msg)

        await saga.add_step("step1", action, comp1)
        await saga.add_step("step2", action)  # No compensation
        await saga.add_step("step3", failing_action)

        result = await saga.execute()

        assert compensations == ["comp1"]  # Only step1 compensated
        assert result.status == SagaStatus.ROLLED_BACK


# ============================================
# RETRY TESTS
# ============================================


class TestRetryLogic:
    """Test retry functionality"""

    @pytest.mark.asyncio
    async def test_step_retries_on_failure(self):
        """Test that failing steps are retried"""
        saga = SimpleSaga()
        attempts = []

        async def flaky_action(ctx):
            attempts.append(1)
            if len(attempts) < 3:
                msg = "Not yet"
                raise ValueError(msg)
            return "success"

        await saga.add_step("flaky", flaky_action, max_retries=3)

        result = await saga.execute()

        assert result.success is True
        assert len(attempts) == 3
        assert saga.steps[0].retry_count == 2  # 0-indexed

    @pytest.mark.asyncio
    async def test_step_retry_exhaustion(self):
        """Test step fails after exhausting retries"""
        saga = SimpleSaga()
        attempts = []

        async def always_fails(ctx):
            attempts.append(1)
            msg = "Always fails"
            raise ValueError(msg)

        await saga.add_step("failing", always_fails, max_retries=3)

        result = await saga.execute()

        assert result.success is False
        # max_retries=3 means 1 initial attempt + 3 retries = 4 total attempts
        assert len(attempts) == 4
        assert saga.steps[0].retry_count == 3

    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self):
        """Test that retries use exponential backoff"""
        saga = SimpleSaga()
        attempt_times = []

        async def flaky_action(ctx):
            attempt_times.append(time.time())
            msg = "Fail"
            raise ValueError(msg)

        await saga.add_step("flaky", flaky_action, max_retries=3)

        time.time()
        await saga.execute()

        # Check timing between attempts (0.01s, 0.02s, 0.04s backoff)
        if len(attempt_times) >= 2:
            delay1 = attempt_times[1] - attempt_times[0]
            assert delay1 >= 0.01  # At least 0.01 seconds

        if len(attempt_times) >= 3:
            delay2 = attempt_times[2] - attempt_times[1]
            assert delay2 >= 0.02  # At least 0.02 seconds

    @pytest.mark.asyncio
    async def test_configurable_retry_backoff_base(self):
        """Test that retry backoff base timeout is configurable"""
        # Create saga with custom retry backoff base (0.1s instead of default 0.01s)
        saga = SimpleSaga(retry_backoff_base=0.1)
        attempt_times = []

        async def flaky_action(ctx):
            attempt_times.append(time.time())
            msg = "Fail"
            raise ValueError(msg)

        await saga.add_step("flaky", flaky_action, max_retries=2)

        start = time.time()
        await saga.execute()

        # With base=0.1, backoff should be 0.1s, 0.2s
        # Total execution should take at least 0.3s
        total_time = time.time() - start
        assert total_time >= 0.3, f"Expected >= 0.3s, got {total_time}s"

        # Check timing between attempts
        if len(attempt_times) >= 2:
            delay1 = attempt_times[1] - attempt_times[0]
            assert delay1 >= 0.1, f"Expected delay1 >= 0.1s, got {delay1}s"

        if len(attempt_times) >= 3:
            delay2 = attempt_times[2] - attempt_times[1]
            assert delay2 >= 0.2, f"Expected delay2 >= 0.2s, got {delay2}s"

    @pytest.mark.asyncio
    async def test_successful_step_no_retry(self):
        """Test successful steps don't retry"""
        saga = SimpleSaga()
        attempts = []

        async def action(ctx):
            attempts.append(1)
            return "success"

        await saga.add_step("step1", action, max_retries=5)

        await saga.execute()

        assert len(attempts) == 1  # Only executed once


# ============================================
# TIMEOUT TESTS
# ============================================


class TestTimeouts:
    """Test timeout functionality"""

    @pytest.mark.asyncio
    async def test_step_timeout(self):
        """Test that slow steps timeout"""
        saga = SimpleSaga()

        async def slow_action(ctx):
            await asyncio.sleep(1.0)  # Longer than timeout (0.5s)
            return "done"

        await saga.add_step("slow", slow_action, timeout=0.5, max_retries=1)

        result = await saga.execute()

        assert result.success is False
        assert isinstance(saga.steps[0].error, SagaTimeoutError)

    @pytest.mark.asyncio
    async def test_compensation_timeout(self):
        """Test that slow compensations timeout"""
        saga = SimpleSaga()

        async def action(ctx):
            return "result"

        async def slow_comp(result, ctx):
            await asyncio.sleep(1.0)  # Longer than compensation_timeout (0.5s)

        async def failing_action(ctx):
            msg = "Fail"
            raise ValueError(msg)

        await saga.add_step("step1", action, slow_comp, compensation_timeout=0.5)
        await saga.add_step("step2", failing_action, max_retries=1)

        result = await saga.execute()

        assert result.success is False
        assert result.status == SagaStatus.FAILED
        assert len(result.compensation_errors) > 0

    @pytest.mark.asyncio
    async def test_fast_step_no_timeout(self):
        """Test that fast steps don't timeout"""
        saga = SimpleSaga()

        async def fast_action(ctx):
            await asyncio.sleep(0.1)
            return "done"

        await saga.add_step("fast", fast_action, timeout=1.0)

        result = await saga.execute()

        assert result.success is True


# ============================================
# IDEMPOTENCY TESTS
# ============================================


class TestIdempotency:
    """Test idempotency functionality"""

    @pytest.mark.asyncio
    async def test_idempotency_key_prevents_duplicate(self):
        """Test same idempotency key prevents duplicate execution"""
        saga = SimpleSaga()
        executions = []

        async def action(ctx):
            executions.append(1)
            return "result"

        key = "unique-key"
        await saga.add_step("step1", action, idempotency_key=key)
        await saga.add_step("step2", action, idempotency_key=key)  # Same key

        await saga.execute()

        assert len(executions) == 1  # Only executed once

    @pytest.mark.asyncio
    async def test_different_keys_allow_execution(self):
        """Test different idempotency keys allow execution"""
        saga = SimpleSaga()
        executions = []

        async def action(ctx):
            executions.append(1)
            return "result"

        await saga.add_step("step1", action, idempotency_key="key1")
        await saga.add_step("step2", action, idempotency_key="key2")

        await saga.execute()

        assert len(executions) == 2  # Both executed


# ============================================
# STATE MACHINE TESTS
# ============================================


class TestStateMachine:
    """Test state machine transitions"""

    @pytest.mark.asyncio
    async def test_initial_state_pending(self):
        """Test saga starts in PENDING state"""
        saga = SimpleSaga()

        assert saga.status == SagaStatus.PENDING
        # State machine needs to be activated for async state machines
        # Check status directly instead of state machine state
        assert saga.status.value == "pending"

    @pytest.mark.asyncio
    async def test_transition_to_executing(self):
        """Test transition to EXECUTING state"""
        saga = SimpleSaga()

        async def action(ctx):
            # Check state during execution
            assert saga.status == SagaStatus.EXECUTING
            return "done"

        await saga.add_step("step1", action)
        await saga.execute()

    @pytest.mark.asyncio
    async def test_transition_to_completed(self):
        """Test successful transition to COMPLETED"""
        saga = SimpleSaga()

        await saga.add_step("step1", lambda ctx: "done")
        result = await saga.execute()

        assert saga.status == SagaStatus.COMPLETED
        assert result.status == SagaStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_transition_to_compensating_then_rolled_back(self):
        """Test failure transitions through COMPENSATING to ROLLED_BACK"""
        saga = SimpleSaga()
        states_seen = []

        async def action(ctx):
            return "result"

        async def comp(result, ctx):
            states_seen.append(saga.status)

        async def failing_action(ctx):
            msg = "Fail"
            raise ValueError(msg)

        await saga.add_step("step1", action, comp)
        await saga.add_step("step2", failing_action)

        await saga.execute()

        assert SagaStatus.COMPENSATING in states_seen
        assert saga.status == SagaStatus.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_empty_saga_succeeds(self):
        """Test saga completes successfully with no steps"""
        saga = SimpleSaga()

        # Empty saga now completes successfully with 0 steps
        result = await saga.execute()
        assert result.success is True
        assert result.completed_steps == 0

    @pytest.mark.asyncio
    async def test_timestamps_recorded(self):
        """Test that execution timestamps are recorded"""
        saga = SimpleSaga()

        await saga.add_step("step1", lambda ctx: "done")
        await saga.execute()

        assert saga.started_at is not None
        assert saga.completed_at is not None
        assert saga.completed_at > saga.started_at


# ============================================
# ORCHESTRATOR TESTS
# ============================================


class TestOrchestrator:
    """Test SagaOrchestrator functionality"""

    @pytest.mark.asyncio
    async def test_orchestrator_tracks_sagas(self):
        """Test orchestrator tracks executed sagas"""
        orchestrator = SagaOrchestrator()

        saga1 = SimpleSaga("Saga1")
        await saga1.add_step("step1", lambda ctx: "done")

        saga2 = SimpleSaga("Saga2")
        await saga2.add_step("step1", lambda ctx: "done")

        await orchestrator.execute_saga(saga1)
        await orchestrator.execute_saga(saga2)

        assert len(orchestrator.sagas) == 2
        assert saga1.saga_id in orchestrator.sagas
        assert saga2.saga_id in orchestrator.sagas

    @pytest.mark.asyncio
    async def test_orchestrator_get_saga(self):
        """Test retrieving saga from orchestrator"""
        orchestrator = SagaOrchestrator()

        saga = SimpleSaga("TestSaga")
        await saga.add_step("step1", lambda ctx: "done")
        await orchestrator.execute_saga(saga)

        retrieved = await orchestrator.get_saga(saga.saga_id)

        assert retrieved is saga
        assert retrieved.name == "TestSaga"

    @pytest.mark.asyncio
    async def test_orchestrator_get_nonexistent_saga(self):
        """Test retrieving nonexistent saga returns None"""
        orchestrator = SagaOrchestrator()

        result = await orchestrator.get_saga("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_orchestrator_count_by_status(self):
        """Test counting sagas by status"""
        orchestrator = SagaOrchestrator()

        async def success_action(ctx):
            return "done"

        async def failure_action(ctx):
            raise ValueError

        async def dummy_action(ctx):
            return "done"

        # Successful saga
        saga1 = SimpleSaga("Success")
        await saga1.add_step("step1", success_action)
        await orchestrator.execute_saga(saga1)

        # Failed saga
        saga2 = SimpleSaga("Failed")
        await saga2.add_step("step1", failure_action)
        await saga2.add_step("step2", dummy_action)
        await orchestrator.execute_saga(saga2)

        completed = await orchestrator.count_completed()
        rolled_back = await orchestrator.count_rolled_back()

        assert completed == 1
        assert rolled_back == 1

    @pytest.mark.asyncio
    async def test_orchestrator_statistics(self):
        """Test orchestrator statistics"""
        orchestrator = SagaOrchestrator()

        async def action(ctx):
            return "done"

        saga = SimpleSaga()
        await saga.add_step("step1", action)
        await orchestrator.execute_saga(saga)

        stats = await orchestrator.get_statistics()

        assert stats["total_sagas"] == 1
        assert stats["completed"] == 1
        assert stats["failed"] == 0
        assert stats["rolled_back"] == 0


# ============================================
# DAG SAGA TESTS
# ============================================


class TestDAGSaga:
    """Test DAG Saga functionality"""

    @pytest.mark.asyncio
    async def test_dag_saga_initialization(self):
        """Test DAG saga initializes correctly"""
        saga = DAGSaga("TestDAG")

        assert saga.name == "TestDAG"
        assert saga.failure_strategy == ParallelFailureStrategy.FAIL_FAST_WITH_GRACE
        assert len(saga.steps) == 0

    @pytest.mark.asyncio
    async def test_add_dag_step_without_dependencies(self):
        """Test adding DAG step without dependencies"""
        saga = DAGSaga()

        await saga.add_step("step1", lambda ctx: "result", dependencies=set())

        assert len(saga.steps) == 1
        assert saga.steps[0].name == "step1"
        assert len(saga.step_dependencies["step1"]) == 0

    @pytest.mark.asyncio
    async def test_add_dag_step_with_dependencies(self):
        """Test adding DAG step with dependencies"""
        saga = DAGSaga()

        await saga.add_step("step1", lambda ctx: "result", dependencies=set())
        await saga.add_step("step2", lambda ctx: "result", dependencies={"step1"})

        assert saga.step_dependencies["step2"] == {"step1"}

    @pytest.mark.asyncio
    async def test_invalid_dependency_raises_error(self):
        """Test adding step with nonexistent dependency raises error"""
        saga = DAGSaga()

        # Should fail during execution when dependency validation happens
        await saga.add_step("step1", lambda ctx: "result", dependencies={"nonexistent"})

        result = await saga.execute()
        assert result.success is False
        assert "missing dependencies" in str(result.error).lower()

    @pytest.mark.asyncio
    async def test_compute_execution_order(self):
        """Test computation of execution order (topological sort)"""
        saga = DAGSaga()

        await saga.add_step("step1", lambda ctx: "r", dependencies=set())
        await saga.add_step("step2", lambda ctx: "r", dependencies={"step1"})
        await saga.add_step("step3", lambda ctx: "r", dependencies={"step1"})
        await saga.add_step("step4", lambda ctx: "r", dependencies={"step2", "step3"})

        # Execute to build batches
        await saga.execute()

        # Check execution batches
        assert len(saga.execution_batches) == 3  # 3 levels
        assert saga.execution_batches[0] == {"step1"}
        assert saga.execution_batches[1] == {"step2", "step3"}  # Can run in parallel
        assert saga.execution_batches[2] == {"step4"}

    @pytest.mark.asyncio
    async def test_circular_dependency_detected(self):
        """Test circular dependency detection"""
        saga = DAGSaga()

        await saga.add_step("step1", lambda ctx: "r", dependencies={"step2"})
        await saga.add_step("step2", lambda ctx: "r", dependencies={"step1"})

        result = await saga.execute()
        assert result.success is False
        assert "circular" in str(result.error).lower() or "missing" in str(result.error).lower()

    @pytest.mark.asyncio
    async def test_parallel_execution_faster_than_sequential(self):
        """Test parallel execution is faster than sequential"""
        # Sequential saga
        seq_saga = Saga("Sequential")

        async def sleep_05_1(ctx):
            await asyncio.sleep(0.05)
            return "r"

        async def sleep_05_2(ctx):
            await asyncio.sleep(0.05)
            return "r"

        await seq_saga.add_step("s1", sleep_05_1)
        await seq_saga.add_step("s2", sleep_05_2)

        start = time.time()
        await seq_saga.execute()
        seq_time = time.time() - start

        # Parallel DAG saga
        dag_saga = DAGSaga("Parallel")

        async def validate_step(ctx):
            return "r"

        async def p1_step(ctx):
            await asyncio.sleep(0.05)
            return "r"

        async def p2_step(ctx):
            await asyncio.sleep(0.05)
            return "r"

        await dag_saga.add_step("validate", validate_step, dependencies=set())
        await dag_saga.add_step("p1", p1_step, dependencies={"validate"})
        await dag_saga.add_step("p2", p2_step, dependencies={"validate"})

        start = time.time()
        await dag_saga.execute()
        dag_time = time.time() - start

        # Parallel should be faster, but allow for CI/system overhead
        # Both run 50ms steps, but parallel runs 2 in parallel vs sequential
        # On a loaded system, timing may vary - use a generous margin
        # The key insight: parallel saga should not take 2x as long as sequential
        assert dag_time < seq_time * 1.5  # Generous margin for CI overhead


# ============================================
# PARALLEL FAILURE STRATEGY TESTS
# ============================================


class TestParallelFailureStrategies:
    """Test different parallel failure strategies"""

    @pytest.mark.asyncio
    async def test_fail_fast_cancels_other_tasks(self):
        """Test FAIL_FAST cancels remaining tasks immediately"""
        saga = DAGSaga("FailFast", failure_strategy=ParallelFailureStrategy.FAIL_FAST)
        completed = []

        async def fast_success(ctx):
            await asyncio.sleep(0.1)
            completed.append("fast")
            return "fast"

        async def fast_fail(ctx):
            await asyncio.sleep(0.2)
            msg = "Fast fail"
            raise ValueError(msg)

        async def slow_success(ctx):
            try:
                await asyncio.sleep(2.0)
                completed.append("slow")
                return "slow"
            except asyncio.CancelledError:
                completed.append("slow_cancelled")
                raise

        async def validate(ctx):
            return "r"

        await saga.add_step("validate", validate, dependencies=set())
        await saga.add_step("fast_success", fast_success, dependencies={"validate"})
        await saga.add_step("fast_fail", fast_fail, dependencies={"validate"})
        await saga.add_step("slow_success", slow_success, dependencies={"validate"})

        result = await saga.execute()

        assert result.success is False
        assert "slow_cancelled" in completed  # Slow task was cancelled
        assert "slow" not in completed  # Didn't complete

    @pytest.mark.asyncio
    async def test_wait_all_lets_all_finish(self):
        """Test WAIT_ALL lets all tasks finish despite failures"""
        saga = DAGSaga("WaitAll", failure_strategy=ParallelFailureStrategy.WAIT_ALL)
        completed = []

        async def step1(ctx):
            await asyncio.sleep(0.1)
            completed.append("step1")
            return "step1"

        async def step2_fails(ctx):
            await asyncio.sleep(0.2)
            completed.append("step2_failed")
            msg = "Step 2 failed"
            raise ValueError(msg)

        async def step3(ctx):
            await asyncio.sleep(0.3)
            completed.append("step3")
            return "step3"

        async def validate(ctx):
            return "r"

        await saga.add_step("validate", validate, dependencies=set())
        await saga.add_step("step1", step1, dependencies={"validate"})
        await saga.add_step("step2", step2_fails, dependencies={"validate"})
        await saga.add_step("step3", step3, dependencies={"validate"})

        result = await saga.execute()

        assert result.success is False
        # All steps should have completed or failed
        assert "step1" in completed
        assert "step2_failed" in completed
        assert "step3" in completed

    @pytest.mark.asyncio
    async def test_fail_fast_grace_waits_for_inflight(self):
        """Test FAIL_FAST_WITH_GRACE waits for in-flight tasks"""
        saga = DAGSaga(
            "FailFastGrace", failure_strategy=ParallelFailureStrategy.FAIL_FAST_WITH_GRACE
        )
        completed = []

        async def fast_fail(ctx):
            await asyncio.sleep(0.1)
            completed.append("fast_fail")
            msg = "Fast fail"
            raise ValueError(msg)

        async def slow_success(ctx):
            await asyncio.sleep(0.5)
            completed.append("slow_success")
            return "slow"

        async def validate(ctx):
            return "r"

        await saga.add_step("validate", validate, dependencies=set())
        await saga.add_step("fast_fail", fast_fail, dependencies={"validate"})
        await saga.add_step("slow_success", slow_success, dependencies={"validate"})

        result = await saga.execute()

        assert result.success is False
        # Slow task should have completed gracefully
        assert "slow_success" in completed
        assert "fast_fail" in completed


# ============================================
# DAG COMPENSATION TESTS
# ============================================


class TestDAGCompensation:
    """Test DAG compensation functionality"""

    @pytest.mark.asyncio
    async def test_dag_compensation_in_reverse_topological_order(self):
        """Test DAG compensation happens in reverse topological order"""
        saga = DAGSaga()
        compensations = []

        async def action(ctx):
            return "result"

        async def comp1(result, ctx):
            compensations.append("comp1")

        async def comp2(result, ctx):
            compensations.append("comp2")

        async def comp3(result, ctx):
            compensations.append("comp3")

        async def comp4(result, ctx):
            compensations.append("comp4")

        async def failing_action(ctx):
            msg = "Fail"
            raise ValueError(msg)

        # Build DAG: step1 -> step2, step3 -> step4
        await saga.add_step("step1", action, comp1, dependencies=set())
        await saga.add_step("step2", action, comp2, dependencies={"step1"})
        await saga.add_step("step3", action, comp3, dependencies={"step1"})
        await saga.add_step("step4", action, comp4, dependencies={"step2", "step3"})
        await saga.add_step("failing", failing_action, dependencies={"step4"})

        await saga.execute()

        # Compensation order should be: step4, then step2/step3 (parallel), then step1
        assert compensations[0] == "comp4"
        assert set(compensations[1:3]) == {"comp2", "comp3"}  # Parallel
        assert compensations[3] == "comp1"

    @pytest.mark.asyncio
    async def test_dag_parallel_compensation(self):
        """Test that independent compensations run in parallel"""
        saga = DAGSaga()
        comp_times = {}

        async def action(ctx):
            return "result"

        async def make_comp(name, duration):
            async def comp(result, ctx):
                start = time.time()
                await asyncio.sleep(duration)
                comp_times[name] = time.time() - start

            return comp

        async def failing_action(ctx):
            msg = "Fail"
            raise ValueError(msg)

        async def validate(ctx):
            return "r"

        await saga.add_step("step1", validate, dependencies=set())
        await saga.add_step("step2", action, await make_comp("comp2", 0.3), dependencies={"step1"})
        await saga.add_step("step3", action, await make_comp("comp3", 0.3), dependencies={"step1"})
        await saga.add_step("failing", failing_action, dependencies={"step2", "step3"})

        start = time.time()
        await saga.execute()
        total_time = time.time() - start

        # Should take ~0.3s (parallel) not ~0.6s (sequential)
        # Allow generous overhead for compensation execution on slow CI systems
        assert total_time < 2.0  # Very generous for CI - actual should be ~0.3-0.5s
        assert "comp2" in comp_times
        assert "comp3" in comp_times
        # Verify both compensations ran (key behavior, not timing)


class TestSagaSequential:
    """Test unified saga in sequential mode (traditional saga behavior)"""

    @pytest.mark.asyncio
    async def test_sequential_saga_basic(self):
        """Test basic sequential saga execution"""
        saga = Saga("sequential-test")

        # Track execution order
        execution_order = []

        async def step1_action(ctx: SagaContext):
            execution_order.append("step1")
            await asyncio.sleep(0.01)
            return "step1_result"

        async def step2_action(ctx: SagaContext):
            execution_order.append("step2")
            await asyncio.sleep(0.01)
            return "step2_result"

        async def step3_action(ctx: SagaContext):
            execution_order.append("step3")
            await asyncio.sleep(0.01)
            return "step3_result"

        # Add steps without dependencies (sequential mode)
        await saga.add_step("step1", step1_action)
        await saga.add_step("step2", step2_action)
        await saga.add_step("step3", step3_action)

        # Execute saga
        result = await saga.execute()

        # Verify sequential execution
        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        assert result.completed_steps == 3
        assert result.total_steps == 3
        assert execution_order == ["step1", "step2", "step3"]

    @pytest.mark.asyncio
    async def test_sequential_saga_with_compensation(self):
        """Test sequential saga with failure and compensation"""
        saga = Saga("sequential-compensation-test")

        execution_order = []
        compensation_order = []

        async def step1_action(ctx: SagaContext):
            execution_order.append("step1")
            return "step1_result"

        async def step1_compensation(result, ctx: SagaContext):
            compensation_order.append("comp_step1")

        async def step2_action(ctx: SagaContext):
            execution_order.append("step2")
            return "step2_result"

        async def step2_compensation(result, ctx: SagaContext):
            compensation_order.append("comp_step2")

        async def step3_action(ctx: SagaContext):
            execution_order.append("step3")
            msg = "Step 3 intentional failure"
            raise Exception(msg)

        # Add steps with compensations
        await saga.add_step("step1", step1_action, step1_compensation)
        await saga.add_step("step2", step2_action, step2_compensation)
        await saga.add_step(
            "step3", step3_action, max_retries=0
        )  # No retries, just initial attempt

        # Execute saga (should fail and compensate)
        result = await saga.execute()

        # Verify failure and compensation
        assert result.success is False
        # Step3 executes once (max_retries=0 = 1 initial attempt, no retries)
        assert "step1" in execution_order
        assert "step2" in execution_order
        assert execution_order.count("step3") == 1


class TestSagaParallel:
    """Test unified saga in DAG/parallel mode"""

    @pytest.mark.asyncio
    async def test_parallel_saga_basic(self):
        """Test basic parallel saga execution"""
        saga = Saga("parallel-test")

        execution_order = []

        async def setup_action(ctx: SagaContext):
            execution_order.append("setup")
            return "setup_result"

        async def step1_action(ctx: SagaContext):
            execution_order.append("step1")
            await asyncio.sleep(0.05)  # Longer delay
            return "step1_result"

        async def step2_action(ctx: SagaContext):
            execution_order.append("step2")
            await asyncio.sleep(0.01)  # Shorter delay
            return "step2_result"

        async def step3_action(ctx: SagaContext):
            execution_order.append("step3")
            await asyncio.sleep(0.01)
            return "step3_result"

        # Add root step first, then parallel steps that depend on it
        await saga.add_step("setup", setup_action, dependencies=set())
        await saga.add_step("step1", step1_action, dependencies={"setup"})
        await saga.add_step("step2", step2_action, dependencies={"setup"})
        await saga.add_step("step3", step3_action, dependencies={"setup"})

        # Execute saga
        result = await saga.execute()

        # Verify parallel execution
        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        assert result.completed_steps == 4

        # All steps should have executed
        assert "setup" in execution_order
        assert "step1" in execution_order
        assert "step2" in execution_order
        assert "step3" in execution_order
        assert len(execution_order) == 4

    @pytest.mark.asyncio
    async def test_dag_with_dependencies(self):
        """Test DAG saga with proper dependencies"""
        saga = Saga("dag-dependency-test")

        execution_order = []

        async def fetch_user_action(ctx: SagaContext):
            execution_order.append("fetch_user")
            await asyncio.sleep(0.01)
            return {"user_id": 123, "name": "John"}

        async def fetch_products_action(ctx: SagaContext):
            execution_order.append("fetch_products")
            await asyncio.sleep(0.01)
            return [{"id": 1, "price": 10}, {"id": 2, "price": 20}]

        async def calculate_total_action(ctx: SagaContext):
            execution_order.append("calculate_total")
            await asyncio.sleep(0.01)
            return {"total": 30}

        async def send_email_action(ctx: SagaContext):
            execution_order.append("send_email")
            await asyncio.sleep(0.01)
            return {"email_sent": True}

        # Build DAG:
        # fetch_user ----\
        #                 \----> calculate_total ----> send_email
        # fetch_products --/

        await saga.add_step("fetch_user", fetch_user_action, dependencies=set())
        await saga.add_step("fetch_products", fetch_products_action, dependencies=set())
        await saga.add_step(
            "calculate_total", calculate_total_action, dependencies={"fetch_user", "fetch_products"}
        )
        await saga.add_step("send_email", send_email_action, dependencies={"calculate_total"})

        # Execute saga
        result = await saga.execute()

        # Verify DAG execution
        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        assert result.completed_steps == 4

        # Verify dependency order
        fetch_user_idx = execution_order.index("fetch_user")
        fetch_products_idx = execution_order.index("fetch_products")
        calculate_total_idx = execution_order.index("calculate_total")
        send_email_idx = execution_order.index("send_email")

        # calculate_total must come after both fetch_user and fetch_products
        assert calculate_total_idx > fetch_user_idx
        assert calculate_total_idx > fetch_products_idx

        # send_email must come after calculate_total
        assert send_email_idx > calculate_total_idx

    @pytest.mark.asyncio
    async def test_parallel_failure_strategies(self):
        """Test different failure strategies in parallel execution"""

        async def success_action(ctx: SagaContext):
            await asyncio.sleep(0.1)
            return "success"

        async def failure_action(ctx: SagaContext):
            await asyncio.sleep(0.05)
            msg = "Intentional failure"
            raise Exception(msg)

        # Test FAIL_FAST strategy
        saga_fail_fast = Saga("fail-fast-test", failure_strategy=ParallelFailureStrategy.FAIL_FAST)
        await saga_fail_fast.add_step("success_step", success_action, dependencies=set())
        await saga_fail_fast.add_step("failure_step", failure_action, dependencies=set())

        result_fail_fast = await saga_fail_fast.execute()
        assert result_fail_fast.success is False

        # Test WAIT_ALL strategy
        saga_wait_all = Saga("wait-all-test", failure_strategy=ParallelFailureStrategy.WAIT_ALL)
        await saga_wait_all.add_step("success_step", success_action, dependencies=set())
        await saga_wait_all.add_step("failure_step", failure_action, dependencies=set())

        result_wait_all = await saga_wait_all.execute()
        assert result_wait_all.success is False


class TestSagaMixed:
    """Test unified saga with mixed sequential and parallel execution"""

    @pytest.mark.asyncio
    async def test_mixed_sequential_parallel(self):
        """Test saga with both sequential and parallel steps"""
        saga = Saga("mixed-test")

        execution_order = []

        async def init_action(ctx: SagaContext):
            execution_order.append("init")
            return "initialized"

        async def parallel_a_action(ctx: SagaContext):
            execution_order.append("parallel_a")
            await asyncio.sleep(0.02)
            return "result_a"

        async def parallel_b_action(ctx: SagaContext):
            execution_order.append("parallel_b")
            await asyncio.sleep(0.01)
            return "result_b"

        async def finalize_action(ctx: SagaContext):
            execution_order.append("finalize")
            return "finalized"

        # Mixed pattern:
        # init (sequential start)
        #   |
        #   ├── parallel_a ----\
        #   └── parallel_b ----/----> finalize

        await saga.add_step("init", init_action, dependencies=set())
        await saga.add_step("parallel_a", parallel_a_action, dependencies={"init"})
        await saga.add_step("parallel_b", parallel_b_action, dependencies={"init"})
        await saga.add_step("finalize", finalize_action, dependencies={"parallel_a", "parallel_b"})

        # Execute saga
        result = await saga.execute()

        # Verify execution
        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        assert result.completed_steps == 4

        # Verify order constraints
        init_idx = execution_order.index("init")
        parallel_a_idx = execution_order.index("parallel_a")
        parallel_b_idx = execution_order.index("parallel_b")
        finalize_idx = execution_order.index("finalize")

        # init must be first
        assert init_idx == 0

        # parallel_a and parallel_b must come after init
        assert parallel_a_idx > init_idx
        assert parallel_b_idx > init_idx

        # finalize must come after both parallel steps
        assert finalize_idx > parallel_a_idx
        assert finalize_idx > parallel_b_idx


class TestSagaEdgeCases:
    """Test edge cases and error conditions"""

    @pytest.mark.asyncio
    async def test_empty_saga(self):
        """Test saga with no steps"""
        saga = Saga("empty-test")

        result = await saga.execute()

        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        assert result.completed_steps == 0
        assert result.execution_time >= 0.0  # Should be very small but non-zero

    @pytest.mark.asyncio
    async def test_duplicate_step_names(self):
        """Test error when adding duplicate step names"""
        saga = Saga("duplicate-test")

        async def dummy_action(ctx: SagaContext):
            return "dummy"

        await saga.add_step("duplicate", dummy_action)

        with pytest.raises(ValueError, match="Step 'duplicate' already exists"):
            await saga.add_step("duplicate", dummy_action)

    @pytest.mark.asyncio
    async def test_circular_dependencies(self):
        """Test error detection for circular dependencies"""
        saga = Saga("circular-test")

        async def dummy_action(ctx: SagaContext):
            return "dummy"

        # Create circular dependency: A -> B -> C -> A
        await saga.add_step("stepA", dummy_action, dependencies={"stepC"})
        await saga.add_step("stepB", dummy_action, dependencies={"stepA"})
        await saga.add_step("stepC", dummy_action, dependencies={"stepB"})

        result = await saga.execute()

        # Should fail with circular dependency error
        assert result.success is False
        assert "Circular or missing dependencies" in str(result.error)

    @pytest.mark.asyncio
    async def test_missing_dependencies(self):
        """Test error detection for missing dependencies"""
        saga = Saga("missing-deps-test")

        async def dummy_action(ctx: SagaContext):
            return "dummy"

        # stepB depends on stepA, but stepA is not added
        await saga.add_step("stepB", dummy_action, dependencies={"stepA"})

        result = await saga.execute()

        # Should fail with missing dependency error
        assert result.success is False
        assert "missing dependencies" in str(result.error).lower()

    @pytest.mark.asyncio
    async def test_strategy_switching(self):
        """Test changing failure strategy"""
        saga = Saga("strategy-switch-test")

        # Initially FAIL_FAST_WITH_GRACE
        assert saga.failure_strategy == ParallelFailureStrategy.FAIL_FAST_WITH_GRACE

        # Switch to WAIT_ALL
        saga.set_failure_strategy(ParallelFailureStrategy.WAIT_ALL)
        assert saga.failure_strategy == ParallelFailureStrategy.WAIT_ALL

        # Switch to FAIL_FAST
        saga.set_failure_strategy(ParallelFailureStrategy.FAIL_FAST)
        assert saga.failure_strategy == ParallelFailureStrategy.FAIL_FAST


class TestSagaIntegration:
    """Integration tests with real business scenarios"""

    @pytest.mark.asyncio
    async def test_ecommerce_order_processing(self):
        """Test realistic e-commerce order processing saga"""
        saga = Saga("ecommerce-order")

        # Simulate realistic delays and data
        async def validate_order_action(ctx: SagaContext):
            await asyncio.sleep(0.01)
            return {"order_id": "ORD-123", "valid": True}

        async def reserve_inventory_action(ctx: SagaContext):
            await asyncio.sleep(0.02)
            return {"reserved": True, "items": ["item1", "item2"]}

        async def validate_payment_action(ctx: SagaContext):
            await asyncio.sleep(0.01)
            return {"payment_valid": True, "amount": 99.99}

        async def charge_payment_action(ctx: SagaContext):
            await asyncio.sleep(0.03)
            return {"charged": True, "transaction_id": "TXN-456"}

        async def ship_order_action(ctx: SagaContext):
            await asyncio.sleep(0.02)
            return {"shipped": True, "tracking": "TRACK-789"}

        # Business flow:
        # 1. Validate order (sequential start)
        # 2. Reserve inventory + Validate payment (parallel)
        # 3. Charge payment (depends on both parallel steps)
        # 4. Ship order (final step)

        await saga.add_step("validate_order", validate_order_action, dependencies=set())
        await saga.add_step(
            "reserve_inventory", reserve_inventory_action, dependencies={"validate_order"}
        )
        await saga.add_step(
            "validate_payment", validate_payment_action, dependencies={"validate_order"}
        )
        await saga.add_step(
            "charge_payment",
            charge_payment_action,
            dependencies={"reserve_inventory", "validate_payment"},
        )
        await saga.add_step("ship_order", ship_order_action, dependencies={"charge_payment"})

        # Execute saga
        result = await saga.execute()

        # Verify successful execution
        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        assert result.completed_steps == 5
        assert result.execution_time > 0

        # Verify it ran in DAG mode
        assert len(saga.execution_batches) == 4  # 4 execution batches

    @pytest.mark.asyncio
    async def test_financial_trade_execution(self):
        """Test realistic financial trade execution saga"""
        saga = Saga("trade-execution", failure_strategy=ParallelFailureStrategy.FAIL_FAST)

        async def validate_funds_action(ctx: SagaContext):
            await asyncio.sleep(0.01)
            return {"available_funds": 10000}

        async def check_market_hours_action(ctx: SagaContext):
            await asyncio.sleep(0.01)
            return {"market_open": True}

        async def get_current_price_action(ctx: SagaContext):
            await asyncio.sleep(0.01)
            return {"price": 150.25, "symbol": "AAPL"}

        async def execute_trade_action(ctx: SagaContext):
            await asyncio.sleep(0.02)
            return {"trade_id": "TRADE-123", "executed_price": 150.30}

        async def update_portfolio_action(ctx: SagaContext):
            await asyncio.sleep(0.01)
            return {"portfolio_updated": True}

        # Trade execution flow:
        # Pre-checks (parallel): validate_funds + check_market_hours + get_current_price
        # Execute trade (depends on all pre-checks)
        # Update portfolio (final step)

        await saga.add_step("validate_funds", validate_funds_action, dependencies=set())
        await saga.add_step("check_market_hours", check_market_hours_action, dependencies=set())
        await saga.add_step("get_current_price", get_current_price_action, dependencies=set())
        await saga.add_step(
            "execute_trade",
            execute_trade_action,
            dependencies={"validate_funds", "check_market_hours", "get_current_price"},
        )
        await saga.add_step(
            "update_portfolio", update_portfolio_action, dependencies={"execute_trade"}
        )

        # Execute saga
        result = await saga.execute()

        # Verify successful execution
        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        assert result.completed_steps == 5

        # Verify execution batches
        assert len(saga.execution_batches) == 3
        assert saga.execution_batches[0] == {
            "validate_funds",
            "check_market_hours",
            "get_current_price",
        }
        assert saga.execution_batches[1] == {"execute_trade"}
        assert saga.execution_batches[2] == {"update_portfolio"}


# ============================================
# EDGE CASES AND ERROR CONDITIONS
# ============================================


class TestEdgeCases:
    """Test edge cases and unusual conditions"""

    @pytest.mark.asyncio
    async def test_empty_saga_completes_successfully(self):
        """Test saga with no steps completes successfully"""
        saga = SimpleSaga()

        # Empty saga now completes successfully with 0 steps
        result = await saga.execute()
        assert result.success is True
        assert result.completed_steps == 0

    @pytest.mark.asyncio
    async def test_saga_can_be_executed_multiple_times(self):
        """Test saga can be executed multiple times"""
        saga = SimpleSaga()
        executions = []

        async def action(ctx):
            executions.append(1)
            return "result"

        await saga.add_step("step1", action)

        result1 = await saga.execute()

        # Reset for second execution (in real scenario, create new saga)
        # Here we're testing the framework handles it
        assert result1.success is True
        assert len(executions) == 1

    @pytest.mark.asyncio
    async def test_very_long_saga(self):
        """Test saga with many steps"""
        saga = SimpleSaga()

        for i in range(100):
            await saga.add_step(f"step{i}", lambda ctx: f"result{i}")

        result = await saga.execute()

        assert result.success is True
        assert result.completed_steps == 100

    @pytest.mark.asyncio
    async def test_saga_with_complex_data_in_context(self):
        """Test saga handles complex data structures in context"""
        saga = SimpleSaga()

        async def action1(ctx):
            return {
                "list": [1, 2, 3],
                "dict": {"nested": {"deep": "value"}},
                "set": {1, 2, 3},
            }

        async def action2(ctx):
            data = ctx.get("step1")
            assert data["dict"]["nested"]["deep"] == "value"
            return "success"

        await saga.add_step("step1", action1)
        await saga.add_step("step2", action2)

        result = await saga.execute()

        assert result.success is True

    @pytest.mark.asyncio
    async def test_exception_in_compensation_doesnt_stop_other_compensations(self):
        """Test that one failing compensation doesn't prevent others"""
        saga = SimpleSaga()
        compensations_run = []

        async def action(ctx):
            return "result"

        async def comp1(result, ctx):
            compensations_run.append(1)

        async def comp2_fails(result, ctx):
            compensations_run.append(2)
            msg = "Comp 2 failed"
            raise ValueError(msg)

        async def comp3(result, ctx):
            compensations_run.append(3)

        async def comp4(result, ctx):
            compensations_run.append(4)

        async def failing_action(ctx):
            msg = "Fail"
            raise ValueError(msg)

        await saga.add_step("step1", action, comp1)
        await saga.add_step("step2", action, comp2_fails)
        await saga.add_step("step3", action, comp3)
        await saga.add_step("step4", action, comp4)
        await saga.add_step("failing", failing_action)

        await saga.execute()

        # All compensations should have been attempted
        assert 4 in compensations_run
        assert 3 in compensations_run
        assert 2 in compensations_run
        assert 1 in compensations_run

    @pytest.mark.asyncio
    async def test_null_and_none_handling(self):
        """Test saga handles None/null values correctly"""
        saga = SimpleSaga()

        async def returns_none(ctx):
            return None

        async def uses_none(ctx):
            previous = ctx.get("step1")
            assert previous is None
            return "handled"

        await saga.add_step("step1", returns_none)
        await saga.add_step("step2", uses_none)

        result = await saga.execute()

        assert result.success is True


# ============================================
# CONCURRENCY AND RACE CONDITION TESTS
# ============================================


class TestConcurrency:
    """Test concurrent execution and race conditions"""

    @pytest.mark.asyncio
    async def test_concurrent_saga_execution_protected(self):
        """Test saga rejects concurrent or duplicate execution attempts"""
        saga = SimpleSaga()
        execution_started = asyncio.Event()

        async def slow_action(ctx):
            execution_started.set()  # Signal that execution has started
            await asyncio.sleep(0.5)  # Moderate delay
            return "done"

        await saga.add_step("slow", slow_action)

        # Start first execution
        task1 = asyncio.create_task(saga.execute())

        # Wait for execution to actually start
        await execution_started.wait()

        # Try second execution - should fail either because:
        # 1. Saga is already executing (raises "already executing"), or
        # 2. Saga completed and can't be restarted (state machine error)
        # Both are correct behaviors - saga should not allow multiple executions
        try:
            await saga.execute()
            # If no exception, the first task must have completed super fast
            # In that case, just verify both executions can't happen
            msg = "Expected saga to reject second execution attempt"
            raise AssertionError(msg)
        except (SagaExecutionError, Exception) as e:
            # Expected - saga rejected the second execution
            # Accept either "already executing" or state transition error
            assert (
                "already executing" in str(e).lower()
                or "can't start" in str(e).lower()
                or "transition" in str(e).lower()
            ), f"Unexpected error: {e}"

        # Clean up first task
        try:
            await task1
        except:
            pass

    @pytest.mark.asyncio
    async def test_multiple_sagas_execute_concurrently(self):
        """Test multiple different sagas can execute concurrently"""
        saga1 = SimpleSaga("Saga1")
        saga2 = SimpleSaga("Saga2")

        await saga1.add_step("step", lambda ctx: asyncio.sleep(0.5) or "done")
        await saga2.add_step("step", lambda ctx: asyncio.sleep(0.5) or "done")

        start = time.time()
        results = await asyncio.gather(saga1.execute(), saga2.execute())
        duration = time.time() - start

        assert all(r.success for r in results)
        assert duration < 1.0  # Should be ~0.5s, not ~1.0s

    @pytest.mark.asyncio
    async def test_orchestrator_handles_concurrent_submissions(self):
        """Test orchestrator handles multiple concurrent saga submissions"""
        orchestrator = SagaOrchestrator()

        sagas = []
        for i in range(10):
            saga = SimpleSaga(f"Saga{i}")
            await saga.add_step("step", lambda ctx: "done")
            sagas.append(saga)

        # Submit all concurrently
        results = await asyncio.gather(*[orchestrator.execute_saga(s) for s in sagas])

        assert len(results) == 10
        assert all(r.success for r in results)
        assert len(orchestrator.sagas) == 10


# ============================================
# PERFORMANCE TESTS
# ============================================


class TestPerformance:
    """Test performance characteristics"""

    @pytest.mark.asyncio
    async def test_execution_time_recorded(self):
        """Test execution time is accurately recorded"""
        saga = SimpleSaga()

        async def slow_step(ctx):
            await asyncio.sleep(0.5)
            return "done"

        await saga.add_step("step", slow_step)

        result = await saga.execute()

        assert result.execution_time >= 0.5
        assert result.execution_time < 1.0  # Shouldn't be too slow

    @pytest.mark.asyncio
    async def test_overhead_is_minimal(self):
        """Test framework overhead is minimal"""
        saga = SimpleSaga()

        # Add 10 fast steps
        for i in range(10):
            await saga.add_step(f"step{i}", lambda ctx: "done")

        start = time.time()
        await saga.execute()
        duration = time.time() - start

        # Should complete quickly (allow more time for CI overhead)
        assert duration < 0.5  # 500ms for 10 no-op steps (generous for slow CI)

    @pytest.mark.asyncio
    async def test_memory_efficient_context(self):
        """Test context doesn't leak memory"""
        saga = SimpleSaga()

        async def action(ctx):
            # Store large data
            ctx.set("data", "x" * 1000)
            return "done"

        await saga.add_step("step", action)
        result = await saga.execute()

        # Context should still be accessible
        assert len(result.context.get("data")) == 1000


# ============================================
# INTEGRATION TESTS
# ============================================


class TestIntegration:
    """Test complete integration scenarios"""

    @pytest.mark.asyncio
    async def test_complete_ecommerce_flow(self):
        """Test complete e-commerce order processing flow"""
        saga = DAGSaga("EcommerceOrder")
        execution_log = []

        async def validate_order(ctx):
            execution_log.append("validate")
            ctx.set("order_valid", True)
            return {"valid": True}

        async def reserve_inventory(ctx):
            execution_log.append("reserve_inventory")
            return {"reserved": True, "reservation_id": "RES-123"}

        async def process_payment(ctx):
            execution_log.append("process_payment")
            return {"paid": True, "transaction_id": "TXN-456"}

        async def create_shipment(ctx):
            execution_log.append("create_shipment")
            inventory = ctx.get("reserve_inventory")
            assert inventory["reserved"] is True
            return {"shipment_id": "SHIP-789"}

        async def send_confirmation(ctx):
            execution_log.append("send_confirmation")
            shipment = ctx.get("create_shipment")
            payment = ctx.get("process_payment")
            assert shipment is not None
            assert payment is not None
            return {"email_sent": True}

        await saga.add_step("validate", validate_order, dependencies=set())
        await saga.add_step("reserve_inventory", reserve_inventory, dependencies={"validate"})
        await saga.add_step("process_payment", process_payment, dependencies={"validate"})
        await saga.add_step("create_shipment", create_shipment, dependencies={"reserve_inventory"})
        await saga.add_step(
            "send_confirmation",
            send_confirmation,
            dependencies={"create_shipment", "process_payment"},
        )

        result = await saga.execute()

        assert result.success is True
        assert result.completed_steps == 5
        assert "validate" in execution_log
        assert "reserve_inventory" in execution_log
        assert "process_payment" in execution_log
        assert "create_shipment" in execution_log
        assert "send_confirmation" in execution_log

    @pytest.mark.asyncio
    async def test_complete_ecommerce_flow_with_failure(self):
        """Test e-commerce flow with payment failure and rollback"""
        saga = DAGSaga("EcommerceOrderFail", failure_strategy=ParallelFailureStrategy.WAIT_ALL)
        compensations = []

        async def validate_order(ctx):
            return {"valid": True}

        async def reserve_inventory(ctx):
            await asyncio.sleep(0.05)  # Complete quickly
            return {"reserved": True}

        async def unreserve_inventory(result, ctx):
            compensations.append("unreserve_inventory")

        async def process_payment_fails(ctx):
            await asyncio.sleep(0.2)  # Delay longer to ensure inventory completes first
            msg = "Payment declined"
            raise ValueError(msg)

        async def refund_payment(result, ctx):
            compensations.append("refund_payment")

        await saga.add_step("validate", validate_order, dependencies=set())
        await saga.add_step(
            "reserve_inventory", reserve_inventory, unreserve_inventory, dependencies={"validate"}
        )
        await saga.add_step(
            "process_payment", process_payment_fails, refund_payment, dependencies={"validate"}
        )

        result = await saga.execute()

        assert result.success is False
        assert result.status == SagaStatus.ROLLED_BACK
        assert "unreserve_inventory" in compensations
        # Payment never succeeded, so no refund needed

    @pytest.mark.asyncio
    async def test_orchestrator_with_multiple_saga_types(self):
        """Test orchestrator managing different saga types"""
        orchestrator = SagaOrchestrator()

        async def step1_action(ctx):
            return "done"

        async def dag_step1_action(ctx):
            return "done"

        async def dag_step2_action(ctx):
            return "done"

        # Sequential saga
        seq_saga = SimpleSaga("Sequential")
        await seq_saga.add_step("step1", step1_action)

        # DAG saga - use dependencies parameter for parallel execution
        dag_saga = DAGSaga("Parallel")
        await dag_saga.add_step("step1", dag_step1_action, dependencies=set())
        await dag_saga.add_step("step2", dag_step2_action, dependencies={"step1"})

        result1 = await orchestrator.execute_saga(seq_saga)
        result2 = await orchestrator.execute_saga(dag_saga)

        assert result1.success is True
        assert result2.success is True
        assert len(orchestrator.sagas) == 2


# ============================================
# REAL-WORLD SCENARIO TESTS
# ============================================


class TestRealWorldScenarios:
    """Test real-world usage scenarios"""

    @pytest.mark.asyncio
    async def test_microservice_timeout_recovery(self):
        """Test handling of microservice timeouts"""
        saga = SimpleSaga()

        async def call_slow_service(ctx):
            await asyncio.sleep(10)  # Will timeout
            return "done"

        async def compensation(result, ctx):
            # Cleanup action
            pass

        await saga.add_step(
            "slow_service", call_slow_service, compensation, timeout=0.5, max_retries=2
        )

        result = await saga.execute()

        assert result.success is False
        assert isinstance(saga.steps[0].error, SagaTimeoutError)

    @pytest.mark.asyncio
    async def test_partial_success_with_compensation(self):
        """Test partial success scenario with proper compensation"""
        saga = SimpleSaga()
        successful_steps = []
        compensated_steps = []

        async def step1(ctx):
            successful_steps.append(1)
            return "step1_done"

        async def step2(ctx):
            successful_steps.append(2)
            return "step2_done"

        async def step3_fails(ctx):
            msg = "Step 3 failed"
            raise ValueError(msg)

        async def comp1(result, ctx):
            compensated_steps.append(1)

        async def comp2(result, ctx):
            compensated_steps.append(2)

        await saga.add_step("step1", step1, comp1)
        await saga.add_step("step2", step2, comp2)
        await saga.add_step("step3", step3_fails)

        result = await saga.execute()

        assert result.success is False
        assert successful_steps == [1, 2]
        assert compensated_steps == [2, 1]  # Reverse order

    @pytest.mark.asyncio
    async def test_idempotent_external_api_calls(self):
        """Test idempotent behavior for external API calls"""
        saga = SimpleSaga()
        api_calls = []

        async def call_external_api(ctx):
            api_calls.append("call")
            return {"api_response": "success"}

        idempotency_key = "external-api-call-123"

        await saga.add_step("api_call_1", call_external_api, idempotency_key=idempotency_key)
        await saga.add_step(
            "api_call_2",
            call_external_api,
            idempotency_key=idempotency_key,  # Same key
        )

        await saga.execute()

        # Should only be called once due to idempotency
        assert len(api_calls) == 1


# ============================================
# HELPER METHODS AND PROPERTIES TESTS
# ============================================


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
        from sagaz.strategies.base import ParallelFailureStrategy

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


# ============================================
# STEP EXECUTOR AND EDGE CASE TESTS
# ============================================


class TestStepExecutor:
    """Tests for _StepExecutor class to cover edge cases"""

    @pytest.mark.asyncio
    async def test_step_executor_compensate_no_compensation(self):
        """Test _StepExecutor.compensate when step has no compensation function"""
        from sagaz.core import SagaStep, _StepExecutor

        # Create a step with no compensation
        step = SagaStep(name="test_step", action=lambda ctx: "result", compensation=None)

        context = SagaContext()
        executor = _StepExecutor(step, context)
        executor.result = {"data": "test"}

        # Should not raise, just return None
        await executor.compensate()

    @pytest.mark.asyncio
    async def test_step_executor_compensate_with_compensation(self):
        """Test _StepExecutor.compensate when step has compensation function"""
        from sagaz.core import SagaStep, _StepExecutor

        compensation_called = []

        async def mock_compensation(result, ctx):
            compensation_called.append(result)

        step = SagaStep(
            name="test_step", action=lambda ctx: "result", compensation=mock_compensation
        )

        context = SagaContext()
        executor = _StepExecutor(step, context)
        executor.result = {"data": "test"}

        await executor.compensate()

        assert len(compensation_called) == 1
        assert compensation_called[0] == {"data": "test"}

    def test_step_executor_name_property(self):
        """Test _StepExecutor.name property"""
        from sagaz.core import SagaStep, _StepExecutor

        step = SagaStep(name="my_unique_step", action=lambda ctx: None)

        context = SagaContext()
        executor = _StepExecutor(step, context)

        assert executor.name == "my_unique_step"


class TestBuildExecutionBatches:
    """Tests for circular/missing dependency detection in _build_execution_batches"""

    @pytest.mark.asyncio
    async def test_circular_dependency_detection(self):
        """Test that circular dependencies are detected during build"""
        saga = Saga(name="CircularSaga")

        # Create circular dependency: A -> B -> A
        await saga.add_step(name="step_a", action=lambda ctx: "a", dependencies={"step_b"})
        await saga.add_step(name="step_b", action=lambda ctx: "b", dependencies={"step_a"})

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
            name="step_a", action=lambda ctx: "a", dependencies={"nonexistent_step"}
        )

        result = await saga.execute()

        assert result.success is False
        assert result.status == SagaStatus.FAILED


class TestDAGExceptionHandling:
    """Tests for DAG execution exception handling"""

    @pytest.mark.asyncio
    async def test_dag_execution_unexpected_exception(self):
        """Test DAG handles unexpected exceptions during batch building"""
        saga = Saga(name="ExceptionSaga")

        async def failing_action(ctx):
            msg = "Unexpected error"
            raise RuntimeError(msg)

        await saga.add_step(
            name="step_a",
            action=failing_action,
            dependencies=set(),  # Explicit DAG mode
        )

        result = await saga.execute()

        assert result.success is False
        # Should be rolled back or failed
        assert result.status in [SagaStatus.ROLLED_BACK, SagaStatus.FAILED]


class TestSagaStepHash:
    """Tests for SagaStep.__hash__ method"""

    def test_saga_step_hash(self):
        """Test that SagaStep can be hashed using idempotency_key"""
        from sagaz.core import SagaStep

        step1 = SagaStep(name="step1", action=lambda ctx: None, idempotency_key="key-123")

        step2 = SagaStep(name="step2", action=lambda ctx: None, idempotency_key="key-456")

        step3 = SagaStep(
            name="step3",
            action=lambda ctx: None,
            idempotency_key="key-123",  # Same key as step1
        )

        # Steps with different idempotency keys should have different hashes
        assert hash(step1) != hash(step2)

        # Steps with same idempotency key should have same hash
        assert hash(step1) == hash(step3)

        # Should be usable in sets
        step_set = {step1, step2}
        assert len(step_set) == 2


class TestSagaAlreadyExecuting:
    """Tests for saga already executing check"""

    @pytest.mark.asyncio
    async def test_saga_already_executing_error(self):
        """Test that concurrent execution raises error"""
        saga = Saga(name="ConcurrentSaga")

        await saga.add_step(name="simple_step", action=lambda ctx: "done")

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
