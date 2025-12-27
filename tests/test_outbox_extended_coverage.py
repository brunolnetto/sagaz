"""
Tests to cover the remaining 7% and push coverage to 95%+

Focuses on:
-sagaz/outbox/worker.py (85% -> 95%+)
-sagaz/outbox/brokers/kafka.py (80% -> 95%+)
-sagaz/outbox/brokers/rabbitmq.py (75% -> 95%+)
-sagaz/outbox/storage/postgresql.py (70% -> 95%+)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestOutboxWorkerCoverage:
    """Cover remaining worker scenarios"""

    @pytest.mark.asyncio
    async def test_worker_start_stop_lifecycle(self):
        """Test worker complete start/stop lifecycle"""
        from sagaz.outbox.worker import OutboxConfig, OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        storage.claim_and_lock.return_value = []  # No events

        config = OutboxConfig(poll_interval_seconds=0.01)
        worker = OutboxWorker(storage, broker, config)

        # Start worker
        task = asyncio.create_task(worker.start())

        # Let it run briefly
        await asyncio.sleep(0.05)

        # Check it's running
        assert worker._running

        # Stop worker
        await worker.stop()

        # Wait for task to complete
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except TimeoutError:
            task.cancel()

        assert not worker._running

    @pytest.mark.asyncio
    async def test_worker_max_retries_exceeded(self):
        """Test event that exceeds max retries goes to dead letter"""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.outbox.worker import OutboxConfig, OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        broker.publish_event.side_effect = Exception("Broker error")

        # Return an event from update_status
        updated_event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
            retry_count=10,  # Over max
        )
        storage.update_status.return_value = updated_event

        config = OutboxConfig(max_retries=2)
        worker = OutboxWorker(storage, broker, config)

        # Event that has already retried max times
        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
            retry_count=2,  # Already at max
        )

        await worker._process_event(event)

        # Should update to FAILED
        storage.update_status.assert_called()

    @pytest.mark.asyncio
    async def test_worker_successful_publish(self):
        """Test successful event publishing"""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.outbox.worker import OutboxConfig, OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()

        config = OutboxConfig()
        worker = OutboxWorker(storage, broker, config)

        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
        )

        await worker._process_event(event)

        # Should publish_event and mark as SENT
        broker.publish_event.assert_called_once()
        storage.update_status.assert_called()

    @pytest.mark.asyncio
    async def test_worker_config_defaults(self):
        """Test OutboxConfig default values"""
        from sagaz.outbox.worker import OutboxConfig

        config = OutboxConfig()
        assert config.batch_size == 100
        assert config.poll_interval_seconds == 1.0  # Fixed from 5.0
        assert config.max_retries == 10  # Fixed from 3
        assert config.claim_timeout_seconds == 300.0


class TestKafkaBrokerCoverage:
    """Cover remaining Kafka broker scenarios"""

    @pytest.mark.asyncio
    async def test_kafka_from_env_with_defaults(self):
        """Test creating Kafka broker from env with minimal config"""
        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.kafka import KafkaBroker

            with patch.dict(
                "os.environ", {"KAFKA_BOOTSTRAP_SERVERS": "localhost:9092"}, clear=False
            ):
                broker = KafkaBroker.from_env()
                assert broker.config.bootstrap_servers == "localhost:9092"
                assert broker.config.client_id is not None

    @pytest.mark.asyncio
    async def test_kafka_health_check_not_connected(self):
        """Test health check when not connected"""
        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig

            config = KafkaBrokerConfig(bootstrap_servers="localhost:9092")
            broker = KafkaBroker(config)

            # Health check should return False when not connected
            healthy = await broker.health_check()
            assert healthy is False

    @pytest.mark.asyncio
    async def test_kafka_close_when_not_connected(self):
        """Test closing broker that was never connected"""
        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig

            config = KafkaBrokerConfig(bootstrap_servers="localhost:9092")
            broker = KafkaBroker(config)

            # Should not raise error
            await broker.close()
            assert not broker._connected

    @pytest.mark.asyncio
    async def test_kafka_publish_not_connected(self):
        """Test publishing when broker not connected raises error"""
        from sagaz.outbox.brokers.base import BrokerConnectionError

        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig

            config = KafkaBrokerConfig(bootstrap_servers="localhost:9092")
            broker = KafkaBroker(config)

            with pytest.raises(BrokerConnectionError):
                await broker.publish(
                    topic="test",
                    message=b"data",
                )


class TestRabbitMQBrokerCoverage:
    """Cover remaining RabbitMQ broker scenarios"""

    @pytest.mark.asyncio
    async def test_rabbitmq_from_env(self):
        """Test creating RabbitMQ broker from environment"""
        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

            with patch.dict(
                "os.environ", {"RABBITMQ_URL": "amqp://guest:guest@localhost/"}, clear=False
            ):
                broker = RabbitMQBroker.from_env()
                assert broker.config.url == "amqp://guest:guest@localhost/"

    @pytest.mark.asyncio
    async def test_rabbitmq_health_check_not_connected(self):
        """Test health check when not connected"""
        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

            broker = RabbitMQBroker()

            # Health check should return False
            healthy = await broker.health_check()
            assert healthy is False

    @pytest.mark.asyncio
    async def test_rabbitmq_close_when_not_connected(self):
        """Test closing broker that was never connected"""
        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

            broker = RabbitMQBroker()

            # Should not raise error
            await broker.close()
            assert not broker._connected

    @pytest.mark.asyncio
    async def test_rabbitmq_publish_not_connected(self):
        """Test publishing when not connected raises error"""
        from sagaz.outbox.brokers.base import BrokerConnectionError

        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

            broker = RabbitMQBroker()

            with pytest.raises(BrokerConnectionError):
                await broker.publish(
                    topic="test",
                    message=b"data",
                )

    @pytest.mark.asyncio
    async def test_rabbitmq_declare_queue_not_connected(self):
        """Test declaring queue when not connected raises error"""
        from sagaz.outbox.brokers.base import BrokerConnectionError

        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

            broker = RabbitMQBroker()

            with pytest.raises(BrokerConnectionError):
                await broker.declare_queue(queue_name="test-queue", routing_key="test.*")


class TestPostgreSQLStorageCoverage:
    """Cover remaining PostgreSQL storage scenarios"""

    @pytest.mark.asyncio
    async def test_postgresql_get_events_by_saga(self):
        """Test getting events by saga ID"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")

            # Mock the pool with proper async context manager
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = []

            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_pool = MagicMock()
            mock_pool.acquire.return_value = mock_ctx
            storage._pool = mock_pool

            events = await storage.get_events_by_saga("saga-123")

            assert events == []

    @pytest.mark.asyncio
    async def test_postgresql_get_pending_count(self):
        """Test getting count of pending events"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")

            # Mock the pool with proper async context manager
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 42

            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_pool = MagicMock()
            mock_pool.acquire.return_value = mock_ctx
            storage._pool = mock_pool

            count = await storage.get_pending_count()

            assert count == 42

    @pytest.mark.asyncio
    async def test_postgresql_claim_and_lock(self):
        """Test claim batch mechanism"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")

            # Mock the pool with proper async context manager
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = []

            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_pool = MagicMock()
            mock_pool.acquire.return_value = mock_ctx
            storage._pool = mock_pool

            events = await storage.claim_batch("worker-1", batch_size=10)

            assert events == []
            mock_conn.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_postgresql_get_stuck_events(self):
        """Test getting stuck events"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")

            # Mock the pool with proper async context manager
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = []

            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_pool = MagicMock()
            mock_pool.acquire.return_value = mock_ctx
            storage._pool = mock_pool

            events = await storage.get_stuck_events(claimed_older_than_seconds=300)

            assert events == []

    @pytest.mark.asyncio
    async def test_postgresql_release_stuck_events(self):
        """Test releasing stuck events"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")

            # Mock the pool with proper async context manager
            mock_conn = AsyncMock()
            mock_conn.execute.return_value = "UPDATE 5"

            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_pool = MagicMock()
            mock_pool.acquire.return_value = mock_ctx
            storage._pool = mock_pool

            count = await storage.release_stuck_events(claimed_older_than_seconds=300)

            assert count == 5

    @pytest.mark.asyncio
    async def test_postgresql_get_by_id_not_found(self):
        """Test getting event by ID when not found"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")

            # Mock the pool with proper async context manager
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = None

            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_pool = MagicMock()
            mock_pool.acquire.return_value = mock_ctx
            storage._pool = mock_pool

            event = await storage.get_by_id("nonexistent")

            assert event is None


class TestCompensationGraphEdgeCases:
    """Cover remaining compensation graph edge cases"""

    @pytest.mark.asyncio
    async def test_compensation_graph_multiple_dependencies(self):
        """Test compensation with multiple dependencies"""
        from sagaz.compensation_graph import SagaCompensationGraph

        graph = SagaCompensationGraph()

        async def comp_fn(ctx):
            pass

        # Create a complex dependency graph
        graph.register_compensation("step_a", comp_fn)
        graph.register_compensation("step_b", comp_fn)
        graph.register_compensation("step_c", comp_fn, depends_on=["step_a", "step_b"])
        graph.register_compensation("step_d", comp_fn, depends_on=["step_c"])

        # Mark all as executed
        for step in ["step_a", "step_b", "step_c", "step_d"]:
            graph.mark_step_executed(step)

        # Get compensation order
        order = graph.get_compensation_order()

        # Should have multiple levels
        assert len(order) >= 3

        # step_d should be in first level (compensated first)
        assert "step_d" in order[0]

        # step_a and step_b should be in last level (compensated last)
        last_level = order[-1]
        assert "step_a" in last_level
        assert "step_b" in last_level


class TestStateElMachineEdgeCases:
    """Cover remaining state machine edge cases"""

    @pytest.mark.asyncio
    async def test_step_state_machine_failure_path(self):
        """Test step state machine failure path"""
        from sagaz.state_machine import SagaStepStateMachine

        sm = SagaStepStateMachine(step_name="test_step")
        await sm.activate_initial_state()

        # Start executing
        await sm.start()
        assert sm.current_state.id == "executing"

        # Fail directly (not compensate)
        await sm.fail()
        assert sm.current_state.id == "failed"

    @pytest.mark.asyncio
    async def test_step_state_machine_compensation_failure(self):
        """Test step state machine compensation failure"""
        from sagaz.state_machine import SagaStepStateMachine

        sm = SagaStepStateMachine(step_name="test_step")
        await sm.activate_initial_state()

        # Execute and complete
        await sm.start()
        await sm.succeed()

        # Start compensation
        await sm.compensate()
        assert sm.current_state.id == "compensating"

        # Compensation fails
        await sm.compensation_failure()
        assert sm.current_state.id == "failed"


class TestStorageFactoryEdgeCases:
    """Cover storage factory edge cases"""

    def test_storage_factory_postgresql_no_connection_string(self):
        """Test PostgreSQL creation without connection string"""
        from sagaz.storage.factory import create_storage

        with pytest.raises(ValueError, match="connection_string"):
            create_storage("postgresql")

    def test_storage_factory_redis_defaults(self):
        """Test Redis creation with default URL"""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True), patch("sagaz.storage.redis.redis"):
            from sagaz.storage.factory import create_storage

            storage = create_storage("redis")
            assert storage.__class__.__name__ == "RedisSagaStorage"


class TestBrokerFactoryEdgeCases:
    """Cover broker factory edge cases"""

    def test_print_available_brokers(self):
        """Test print_available_brokers function"""
        import io
        import sys

        from sagaz.outbox.brokers.factory import print_available_brokers

        # Capture stdout
        captured = io.StringIO()
        sys.stdout = captured

        try:
            print_available_brokers()
            output = captured.getvalue()

            # Should contain "memory"
            assert "memory" in output.lower()
        finally:
            sys.stdout = sys.__stdout__
