
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from sagaz.outbox.brokers.factory import create_broker_from_env, get_available_brokers
from sagaz.outbox.worker import OutboxWorker, OutboxConfig
from sagaz.outbox.types import OutboxStatus

class TestCoverageImprovements:
    
    @pytest.mark.asyncio
    async def test_worker_lifecycle(self):
        """Test worker start/stop loop coverage."""
        storage = AsyncMock()
        broker = AsyncMock()
        config = OutboxConfig(poll_interval_seconds=0.01)
        
        worker = OutboxWorker(storage, broker, config)
        
        # Mock process_batch to return 0 so it waits
        worker.process_batch = AsyncMock(return_value=0)
        
        # Mock signal handlers to avoid side effects
        from unittest.mock import MagicMock
        loop_mock = MagicMock()
        with patch("asyncio.get_event_loop", return_value=loop_mock):
            # Start worker in background
            task = asyncio.create_task(worker.start())
            
            # Allow it to run a loop iteration
            await asyncio.sleep(0.05)
            
            # Stop worker
            await worker.stop()
            
            # Wait for task to finish
            await task
            
        assert not worker._running
        assert worker.process_batch.called

    @pytest.mark.asyncio
    async def test_worker_shutdown_handler(self):
        """Test worker shutdown handler."""
        storage = AsyncMock()
        broker = AsyncMock()
        worker = OutboxWorker(storage, broker)
        
        # Mock create_task to verify it calls stop
        with patch("asyncio.create_task") as mock_create_task:
            worker._handle_shutdown()
            mock_create_task.assert_called_once()
    
    def test_broker_factory_from_env(self, monkeypatch):
        """Test create_broker_from_env with different types."""
        # Test Memory
        monkeypatch.setenv("BROKER_TYPE", "memory")
        broker = create_broker_from_env()
        assert broker.__class__.__name__ == "InMemoryBroker"
        
        # Test Kafka (Mock the availability and module)
        monkeypatch.setenv("BROKER_TYPE", "kafka")
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        with patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True), \
             patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"):
            broker = create_broker_from_env()
            assert broker.__class__.__name__ == "KafkaBroker"
        
        # Test RabbitMQ (Mock the availability and module)
        monkeypatch.setenv("BROKER_TYPE", "rabbitmq")
        with patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True), \
             patch("sagaz.outbox.brokers.rabbitmq.aio_pika"):
            broker = create_broker_from_env()
            assert broker.__class__.__name__ == "RabbitMQBroker"

    @pytest.mark.asyncio
    async def test_postgresql_status_updates(self):
        """Test coverage for PostgreSQL update_status branches."""
        from datetime import datetime
        
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage
        
            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/db")
            
            # Mock connection with fetchrow (direct connection path)
            conn = AsyncMock()
            # Mock row with all required fields
            mock_row = {
                "event_id": "evt-1",
                "saga_id": "saga-1",
                "aggregate_type": "agg",
                "aggregate_id": "1",
                "event_type": "type",
                "payload": "{}",
                "headers": "{}",
                "status": "pending",  # lowercase to match OutboxStatus enum values
                "created_at": datetime.now(),
                "claimed_at": None,
                "sent_at": None,
                "retry_count": 0,
                "last_error": None,
                "worker_id": None
            }
            conn.fetchrow = AsyncMock(return_value=mock_row)
            storage._pool = conn  # Use conn directly as pool since it has fetchrow
            
            # Test FAILED status
            await storage.update_status("evt-1", OutboxStatus.FAILED, error_message="Error")
            # Verify query contained 'last_error'
            call_args = conn.fetchrow.call_args[0]
            assert "last_error" in call_args[0]
            
            # Test PENDING status (release)
            await storage.update_status("evt-1", OutboxStatus.PENDING)
            call_args = conn.fetchrow.call_args[0]
            assert "worker_id = NULL" in call_args[0]

    @pytest.mark.asyncio
    async def test_kafka_broker_idempotency(self):
        """Test Kafka broker connect/close idempotency."""
        with patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True), \
             patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer") as MockProducer:
            from sagaz.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig
            
            config = KafkaBrokerConfig(bootstrap_servers="localhost:9092")
            broker = KafkaBroker(config)
            
            mock_producer = AsyncMock()
            MockProducer.return_value = mock_producer
            
            # Connect twice
            await broker.connect()
            assert broker._connected
            await broker.connect() # Should return early
            assert mock_producer.start.call_count == 1
            
            # Close twice
            await broker.close()
            assert not broker._connected
            await broker.close() # Should return early
            assert mock_producer.stop.call_count == 1

    @pytest.mark.asyncio
    async def test_rabbitmq_broker_idempotency(self):
        """Test RabbitMQ broker connect/close idempotency."""
        with patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True), \
             patch("sagaz.outbox.brokers.rabbitmq.aio_pika") as mock_aio_pika, \
             patch("sagaz.outbox.brokers.rabbitmq.ExchangeType") as mock_exchange_type:
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker
            
            # Mock ExchangeType.TOPIC
            mock_exchange_type.TOPIC = "topic"
            
            broker = RabbitMQBroker()
            broker._connection = AsyncMock()
            broker._channel = AsyncMock()
            
            # Mock connect_robust to avoid real networking
            mock_channel = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=AsyncMock())
            
            mock_connection = AsyncMock()
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_connection.close = AsyncMock()
            
            mock_aio_pika.connect_robust = AsyncMock(return_value=mock_connection)
            
            await broker.connect()
            assert broker._connected
            
            await broker.connect() # Should return early
            assert mock_aio_pika.connect_robust.call_count == 1
            
            await broker.close()
            assert not broker._connected
            
            await broker.close() # Should return early
            # Close call count on connection object
            assert mock_connection.close.call_count == 1

    @pytest.mark.asyncio
    async def test_compensation_graph_missing_dependency(self):
        """Test compensation graph with missing dependency."""
        from sagaz.compensation_graph import SagaCompensationGraph, MissingDependencyError
        
        graph = SagaCompensationGraph()
        
        # Register step that depends on non-existent step
        async def comp_fn(ctx):
            pass
        
        graph.register_compensation("step1", comp_fn, depends_on=["nonexistent"])
        
        # Should raise MissingDependencyError when validating
        with pytest.raises(MissingDependencyError):
            graph.validate()

    @pytest.mark.asyncio
    async def test_compensation_graph_circular_dependency(self):
        """Test compensation graph with circular dependency."""
        from sagaz.compensation_graph import SagaCompensationGraph, CircularDependencyError
        
        graph = SagaCompensationGraph()
        
        async def comp_fn(ctx):
            pass
        
        # Create circular dependency: A -> B -> A
        graph.register_compensation("step_a", comp_fn, depends_on=["step_b"])
        graph.register_compensation("step_b", comp_fn, depends_on=["step_a"])
        
        # Should raise CircularDependencyError when validating
        with pytest.raises(CircularDependencyError):
            graph.validate()

    @pytest.mark.asyncio
    async def test_core_saga_no_steps(self):
        """Test saga execution with no steps."""
        from sagaz.core import Saga as ClassicSaga
        
        saga = ClassicSaga(name="EmptySaga")
        result = await saga.execute()
        
        assert result.success
        assert result.completed_steps == 0
        assert result.total_steps == 0

    @pytest.mark.asyncio
    async def test_core_saga_planning_failure(self):
        """Test saga with circular dependency in planning phase."""
        from sagaz.core import Saga as ClassicSaga
        from sagaz import SagaContext
        
        saga = ClassicSaga(name="BadSaga")
        
        async def action(ctx: SagaContext):
            return {"result": "ok"}
        
        # Create circular dependency
        await saga.add_step("step_a", action, dependencies={"step_b"})
        await saga.add_step("step_b", action, dependencies={"step_a"})
        
        result = await saga.execute()
        
        assert not result.success
        assert result.status.value == "failed"
        assert "Circular or missing dependencies" in str(result.error)

    @pytest.mark.asyncio
    async def test_decorator_saga_timeout(self):
        """Test declarative saga step timeout."""
        from sagaz.decorators import Saga, step
        import asyncio
        
        class TimeoutSaga(Saga):
            @step(name="slow_step", timeout_seconds=0.1)
            async def slow_step(self, ctx):
                await asyncio.sleep(1)
                return {"done": True}
        
        saga = TimeoutSaga()
        
        with pytest.raises(TimeoutError):
            await saga.run({})

    @pytest.mark.asyncio
    async def test_decorator_saga_compensation_error(self):
        """Test declarative saga compensation error handling."""
        from sagaz.decorators import Saga, step, compensate
        
        class FailingSaga(Saga):
            @step(name="step1")
            async def step1(self, ctx):
                return {"step1": "done"}
            
            @compensate("step1")
            async def comp_step1(self, ctx):
                # Compensation fails
                raise Exception("Compensation failed")
            
            @step(name="step2", depends_on=["step1"])
            async def step2(self, ctx):
                raise Exception("Step2 failed")
        
        saga = FailingSaga()
        
        with pytest.raises(Exception):
            await saga.run({})

    @pytest.mark.asyncio
    async def test_storage_factory_postgresql(self):
        """Test storage factory with PostgreSQL."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.factory import create_storage
            
            storage = create_storage("postgresql", connection_string="postgresql://localhost:5432/test")
            assert storage.__class__.__name__ == "PostgreSQLSagaStorage"

    @pytest.mark.asyncio
    async def test_storage_factory_redis(self):
        """Test storage factory with Redis."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True), \
             patch("sagaz.storage.redis.redis"):
            from sagaz.storage.factory import create_storage
            
            storage = create_storage("redis", redis_url="redis://localhost:6379")
            assert storage.__class__.__name__ == "RedisSagaStorage"

    @pytest.mark.asyncio
    async def test_storage_factory_invalid_type(self):
        """Test storage factory with invalid type."""
        from sagaz.storage.factory import create_storage
        
        with pytest.raises(ValueError, match="Unknown storage backend"):
            create_storage("invalid")

    @pytest.mark.asyncio
    async def test_state_machine_no_saga(self):
        """Test state machine without saga instance."""
        from sagaz.state_machine import SagaStateMachine
        
        sm = SagaStateMachine(saga=None)
        
        # Guards should return True when no saga
        assert sm.has_steps()
        assert sm.has_completed_steps()

    @pytest.mark.asyncio
    async def test_orchestrator_statistics(self):
        """Test orchestrator statistics calculation."""
        from sagaz.orchestrator import SagaOrchestrator
        from sagaz.core import Saga as ClassicSaga
        from sagaz import SagaContext
        
        orch = SagaOrchestrator()
        
        # Create and execute a saga
        saga = ClassicSaga(name="TestSaga")
        
        async def action(ctx: SagaContext):
            return {"result": "ok"}
        
        await saga.add_step("step1", action)
        await orch.execute_saga(saga)
        
        # Get statistics
        stats = await orch.get_statistics()
        assert stats["total_sagas"] == 1
        assert stats["completed"] == 1

    @pytest.mark.asyncio
    async def test_outbox_worker_error_handling(self):
        """Test outbox worker error handling during processing."""
        from sagaz.outbox.worker import OutboxWorker, OutboxConfig
        from sagaz.outbox.types import OutboxEvent, OutboxStatus
        
        storage = AsyncMock()
        broker = AsyncMock()
        config = OutboxConfig(max_retries=2)
        
        worker = OutboxWorker(storage, broker, config)
        
        # Create event that will fail
        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
            retry_count=0
        )
        
        # Make broker.publish raise an error
        broker.publish.side_effect = Exception("Broker error")
        
        # Process should handle the error and update status
        await worker._process_event(event)
        
        # Should have called update_status with FAILED
        storage.update_status.assert_called()

    @pytest.mark.asyncio  
    async def test_compensation_graph_get_info(self):
        """Test compensation graph get_compensation_info."""
        from sagaz.compensation_graph import SagaCompensationGraph
        
        graph = SagaCompensationGraph()
        
        async def comp_fn(ctx):
            pass
        
        graph.register_compensation("step1", comp_fn)
        
        # Get info for existing step
        info = graph.get_compensation_info("step1")
        assert info is not None
        assert info.step_id == "step1"
        
        # Get info for non-existent step
        info = graph.get_compensation_info("nonexistent")
        assert info is None

    @pytest.mark.asyncio
    async def test_outbox_types_to_dict(self):
        """Test OutboxEvent to_dict method."""
        from sagaz.outbox.types import OutboxEvent
        from datetime import datetime, timezone
        
        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"}
        )
        
        event_dict = event.to_dict()
        assert event_dict["saga_id"] == "saga-1"
        assert event_dict["aggregate_type"] == "order"
        assert event_dict["event_type"] == "OrderCreated"
        assert isinstance(event_dict["created_at"], str)

    @pytest.mark.asyncio
    async def test_core_saga_step_already_exists(self):
        """Test adding duplicate step name."""
        from sagaz.core import Saga as ClassicSaga
        from sagaz import SagaContext
        
        saga = ClassicSaga(name="DupeSaga")
        
        async def action(ctx: SagaContext):
            return {}
        
        await saga.add_step("step1", action)
        
        # Adding same step name should raise ValueError
        with pytest.raises(ValueError, match="already exists"):
            await saga.add_step("step1", action)

    @pytest.mark.asyncio
    async def test_core_saga_add_step_while_executing(self):
        """Test that adding steps while saga is executing raises error."""
        from sagaz.core import Saga as ClassicSaga
        from sagaz import SagaContext, SagaExecutionError
        import asyncio
        
        saga = ClassicSaga(name="TestSaga")
        
        async def action(ctx: SagaContext):
            await asyncio.sleep(0.1)
            return {}
        
        await saga.add_step("step1", action)
        
        # Start execution in background
        task = asyncio.create_task(saga.execute())
        await asyncio.sleep(0.01)  # Let it start
        
        # Try to add step while executing
        with pytest.raises(SagaExecutionError, match="Cannot add steps while saga is executing"):
            await saga.add_step("step2", action)
        
        await task  # Clean up
