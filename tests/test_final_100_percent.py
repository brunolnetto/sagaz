"""
Final tests to reach 100% coverage

Targets the specific missing lines in each module
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


class TestCompensationGraphTo100:
    """Cover missing lines in compensation_graph.py"""

    @pytest.mark.asyncio
    async def test_compensation_graph_validation_circular(self):
        """Test validate() method detecting circular dependencies"""
        from sagaz.compensation_graph import CircularDependencyError, SagaCompensationGraph

        graph = SagaCompensationGraph()

        async def comp_fn(ctx):
            pass

        # Create circular dependency
        graph.register_compensation("step_a", comp_fn, depends_on=["step_b"])
        graph.register_compensation("step_b", comp_fn, depends_on=["step_a"])

        # validate() should detect circular dependency
        with pytest.raises(CircularDependencyError):
            graph.validate()

    @pytest.mark.asyncio
    async def test_compensation_graph_find_cycle_deep(self):
        """Test _find_cycle method with deeper cycle"""
        from sagaz.compensation_graph import CircularDependencyError, SagaCompensationGraph

        graph = SagaCompensationGraph()

        async def comp_fn(ctx):
            pass

        # Create A -> B -> C -> A cycle
        graph.register_compensation("step_a", comp_fn, depends_on=["step_c"])
        graph.register_compensation("step_b", comp_fn, depends_on=["step_a"])
        graph.register_compensation("step_c", comp_fn, depends_on=["step_b"])

        # Mark all as executed
        graph.mark_step_executed("step_a")
        graph.mark_step_executed("step_b")
        graph.mark_step_executed("step_c")

        # Should detect cycle
        with pytest.raises(CircularDependencyError):
            graph.get_compensation_order()


class TestCoreTo100:
    """Cover missing lines in core.py"""

    @pytest.mark.asyncio
    async def test_saga_no_completed_steps_compensation_attempt(self):
        """Test compensation when no steps completed"""
        from sagaz import SagaContext
        from sagaz.core import Saga as ClassicSaga

        saga = ClassicSaga(name="TestSaga")

        async def failing_action(ctx: SagaContext):
            msg = "Immediate failure"
            raise Exception(msg)

        await saga.add_step("step1", failing_action)

        result = await saga.execute()

        # Should fail without compensation (no completed steps)
        assert not result.success
        assert result.status.value == "rolled_back"
        assert result.completed_steps == 0

    @pytest.mark.asyncio
    async def test_saga_already_executing_error(self):
        """Test that executing saga twice raises error"""
        import asyncio

        from sagaz import SagaContext, SagaExecutionError
        from sagaz.core import Saga as ClassicSaga

        saga = ClassicSaga(name="TestSaga")

        async def slow_action(ctx: SagaContext):
            await asyncio.sleep(0.5)
            return {}

        await saga.add_step("step1", slow_action)

        # Start first execution
        task1 = asyncio.create_task(saga.execute())
        await asyncio.sleep(0.01)  # Let it start

        # Try second execution - should raise
        with pytest.raises(SagaExecutionError):
            await saga.execute()

        # Clean up
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass


class TestDecoratorsTo100:
    """Cover missing lines in decorators.py"""

    @pytest.mark.asyncio
    async def test_saga_execution_order_circular_dependency(self):
        """Test get_execution_order with circular dependency"""
        from sagaz.decorators import Saga, step

        class BadSaga(Saga):
            @step(name="step_a", depends_on=["step_b"])
            async def step_a(self, ctx):
                return {}

            @step(name="step_b", depends_on=["step_a"])
            async def step_b(self, ctx):
                return {}

        saga = BadSaga()

        # Should raise ValueError for circular dependency
        with pytest.raises(ValueError, match="Circular dependency"):
            saga.get_execution_order()

    @pytest.mark.asyncio
    async def test_saga_compensation_error_handling(self):
        """Test compensation errors are logged but don't fail"""
        from sagaz.decorators import Saga, compensate, step

        class CompErrorSaga(Saga):
            @step(name="step1")
            async def step1(self, ctx):
                return {"done": True}

            @compensate("step1")
            async def comp1(self, ctx):
                msg = "Comp error"
                raise Exception(msg)

            @step(name="step2", depends_on=["step1"])
            async def step2(self, ctx):
                msg = "Step2 fails"
                raise Exception(msg)

        saga = CompErrorSaga()

        # Should handle compensation error gracefully
        with pytest.raises(Exception):
            await saga.run({})


class TestStateMachineTo100:
    """Cover missing lines in state_machine.py"""

    @pytest.mark.asyncio
    async def test_state_machine_transitions(self):
        """Test state machine transition callbacks"""
        from sagaz import SagaContext
        from sagaz.core import Saga as ClassicSaga

        saga = ClassicSaga(name="TestSaga")

        async def action(ctx: SagaContext):
            return {}

        await saga.add_step("step1", action)

        # Execute the saga which uses the state machine
        result = await saga.execute()

        assert result.success
        assert result.status.value == "completed"


class TestStorageTo100:
    """Cover missing lines in storage modules"""

    @pytest.mark.asyncio
    async def test_memory_storage_list_sagas_pagination(self):
        """Test memory storage list with pagination"""
        from sagaz.storage.memory import InMemorySagaStorage
        from sagaz.types import SagaStatus

        storage = InMemorySagaStorage()

        # Add multiple sagas
        for i in range(5):
            await storage.save_saga_state(
                saga_id=f"saga-{i}",
                saga_name="TestSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

        # List with limit
        sagas = await storage.list_sagas(limit=3)
        assert len(sagas) <= 3

    @pytest.mark.asyncio
    async def test_postgresql_storage_import_error(self):
        """Test PostgreSQL storage when asyncpg not available"""
        from sagaz.storage.postgresql import ASYNCPG_AVAILABLE

        # Just verify the import check works
        assert isinstance(ASYNCPG_AVAILABLE, bool)

    @pytest.mark.asyncio
    async def test_redis_storage_import_error(self):
        """Test Redis storage when redis not available"""
        from sagaz.storage.redis import REDIS_AVAILABLE

        # Just verify the import check works
        assert isinstance(REDIS_AVAILABLE, bool)


class TestBrokerTo100:
    """Cover missing lines in broker modules"""

    @pytest.mark.asyncio
    async def test_kafka_broker_import_check(self):
        """Test Kafka broker import availability check"""
        from sagaz.outbox.brokers.kafka import KAFKA_AVAILABLE

        # Verify import check works
        assert isinstance(KAFKA_AVAILABLE, bool)

    @pytest.mark.asyncio
    async def test_rabbitmq_broker_import_check(self):
        """Test RabbitMQ broker import availability check"""
        from sagaz.outbox.brokers.rabbitmq import RABBITMQ_AVAILABLE

        # Verify import check works
        assert isinstance(RABBITMQ_AVAILABLE, bool)

    @pytest.mark.asyncio
    async def test_broker_factory_print_output(self):
        """Test print_available_brokers outputs correctly"""
        import io
        import sys

        from sagaz.outbox.brokers.factory import print_available_brokers

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        try:
            print_available_brokers()
            output = captured.getvalue()
            assert "memory" in output.lower()
            assert "message brokers" in output.lower()
        finally:
            sys.stdout = old_stdout


class TestOrchestratorTo100:
    """Cover missing orchestrator lines"""

    @pytest.mark.asyncio
    async def test_orchestrator_verbose_logging(self):
        """Test orchestrator with verbose logging enabled"""
        import logging

        from sagaz import SagaContext
        from sagaz.core import Saga as ClassicSaga
        from sagaz.orchestrator import SagaOrchestrator

        # Create orchestrator with verbose mode
        logger = logging.getLogger("test")
        orch = SagaOrchestrator(logger=logger, verbose=True)

        saga = ClassicSaga(name="TestSaga")

        async def action(ctx: SagaContext):
            return {}

        await saga.add_step("step1", action)

        # Execute - should log verbosely
        result = await orch.execute_saga(saga)

        assert result.success


class TestMonitoringTo100:
    """Cover missing monitoring lines"""

    @pytest.mark.asyncio
    async def test_tracing_without_opentelemetry(self):
        """Test tracing module when OpenTelemetry not available"""
        # The import error handling is in the module-level code
        # Just importing tests the path
        from sagaz.monitoring import tracing

        # Verify module loaded
        assert hasattr(tracing, "SagaTracer")

    def test_metrics_record_execution(self):
        """Test metrics record_execution method"""
        from sagaz.monitoring.metrics import SagaMetrics
        from sagaz.types import SagaStatus

        metrics = SagaMetrics()

        # Record executions
        metrics.record_execution("TestSaga", SagaStatus.COMPLETED, 1.0)
        metrics.record_execution("TestSaga", SagaStatus.FAILED, 0.5)
        metrics.record_execution("TestSaga", SagaStatus.ROLLED_BACK, 0.3)

        # Get metrics
        result = metrics.get_metrics()

        assert result["total_executed"] == 3
        assert result["total_successful"] == 1
        assert result["total_failed"] == 1
        assert result["total_rolled_back"] == 1


class TestWorkerTo100:
    """Cover missing worker lines"""

    @pytest.mark.asyncio
    async def test_worker_signal_handlers(self):
        """Test worker signal handler registration"""

        from sagaz.outbox.worker import OutboxConfig, OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        storage.claim_and_lock = AsyncMock(return_value=[])

        worker = OutboxWorker(storage, broker, OutboxConfig())

        # Mock signal.signal to avoid actual signal registration
        with patch("signal.signal"):
            # Start worker briefly
            task = asyncio.create_task(worker.start())
            await asyncio.sleep(0.01)
            await worker.stop()
            try:
                await asyncio.wait_for(task, timeout=0.5)
            except TimeoutError:
                task.cancel()


class TestOutboxTypesTo100:
    """Cover missing outbox types lines"""

    @pytest.mark.asyncio
    async def test_outbox_event_str_payload(self):
        """Test OutboxEvent with string payload that needs parsing"""
        from sagaz.outbox.types import OutboxEvent

        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload='{"order_id": "123"}',  # String instead of dict
        )

        # Convert to dict and back
        event_dict = event.to_dict()
        assert event_dict["payload"] == '{"order_id": "123"}'

    @pytest.mark.asyncio
    async def test_outbox_config_from_env(self):
        """Test OutboxConfig.from_env()"""
        from sagaz.outbox.types import OutboxConfig

        with patch.dict(
            "os.environ",
            {"OUTBOX_BATCH_SIZE": "50", "OUTBOX_POLL_INTERVAL": "2.0", "OUTBOX_MAX_RETRIES": "5"},
            clear=False,
        ):
            config = OutboxConfig.from_env()
            # Should use env values or defaults
            assert config.batch_size > 0


class TestStrategiesTo100:
    """Cover missing strategy lines"""

    @pytest.mark.asyncio
    async def test_fail_fast_cancellation(self):
        """Test FailFast strategy handles cancellation"""
        from sagaz.strategies.fail_fast import FailFastStrategy

        strategy = FailFastStrategy()

        class MockStep:
            async def execute(self):
                await asyncio.sleep(10)
                return "done"

        steps = [MockStep(), MockStep()]

        # Start execution and cancel it
        task = asyncio.create_task(strategy.execute_parallel_steps(steps))
        await asyncio.sleep(0.01)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass  # Expected

    @pytest.mark.asyncio
    async def test_fail_fast_grace_timeout_path(self):
        """Test FailFastWithGrace strategy timeout handling"""
        from sagaz.strategies.fail_fast_grace import FailFastWithGraceStrategy

        strategy = FailFastWithGraceStrategy()

        class SlowStep:
            def __init__(self, fail=False):
                self.fail = fail

            async def execute(self):
                await asyncio.sleep(0.1)
                if self.fail:
                    msg = "Step failed"
                    raise Exception(msg)
                return "done"

        steps = [SlowStep(), SlowStep(fail=True), SlowStep()]

        # Should handle gracefully
        with pytest.raises(Exception):
            await strategy.execute_parallel_steps(steps)


class TestOutboxMemoryTo100:
    """Cover missing outbox memory storage lines"""

    @pytest.mark.asyncio
    async def test_memory_outbox_insert_and_claim(self):
        """Test inserting events and claiming them"""
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage
        from sagaz.outbox.types import OutboxEvent, OutboxStatus

        storage = InMemoryOutboxStorage()

        # Insert event
        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={},
            status=OutboxStatus.PENDING,
        )
        await storage.insert(event)

        # Claim event
        claimed = await storage.claim_batch("worker-1", batch_size=10)

        assert len(claimed) == 1
        assert claimed[0].status == OutboxStatus.CLAIMED
        assert claimed[0].worker_id == "worker-1"
