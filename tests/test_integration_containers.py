"""
Integration tests using testcontainers for infrastructure-dependent components.

These tests use Docker containers to test real PostgreSQL, Kafka, and RabbitMQ
integrations without requiring manual infrastructure setup.

Requires:
    - Docker running
    - testcontainers[postgres,kafka] installed

Run with:
    RUN_INTEGRATION=1 pytest tests/test_integration_containers.py -v

Skip during regular runs (default):
    pytest tests/  # These tests are skipped by default
"""

import asyncio
import os

import pytest

# Skip all tests in this module unless RUN_INTEGRATION env var is set
if not os.environ.get("RUN_INTEGRATION"):
    pytest.skip(
        "Skipping integration tests (set RUN_INTEGRATION=1 to run)", allow_module_level=True
    )


# Skip if testcontainers not available
pytest.importorskip("testcontainers")


# ============================================
# POSTGRESQL OUTBOX STORAGE TESTS
# ============================================


class TestPostgreSQLOutboxStorageIntegration:
    """Integration tests for PostgreSQL outbox storage using testcontainers."""

    @pytest.fixture
    def postgres_container(self):
        """Start a PostgreSQL container for testing."""
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:15") as postgres:
            yield postgres

    @pytest.mark.asyncio
    async def test_postgresql_storage_lifecycle(self, postgres_container):
        """Test full lifecycle: initialize, insert, claim, update, close."""
        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        storage = self._create_storage(postgres_container)

        try:
            await storage.initialize()
            event = await self._insert_test_event(storage)
            await self._verify_insert_and_claim(storage, event)
            await self._verify_update_and_query(storage, event)
        finally:
            await storage.close()

    def _create_storage(self, postgres_container):
        """Create PostgreSQL storage from container."""
        from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        return PostgreSQLOutboxStorage(
            connection_string=connection_string,
            pool_min_size=1,
            pool_max_size=5,
        )

    async def _insert_test_event(self, storage):
        """Insert a test event and return it."""
        from sagaz.outbox.types import OutboxEvent

        event = OutboxEvent(
            saga_id="saga-integration-test",
            event_type="order.created",
            payload={"order_id": "ORD-123", "amount": 99.99},
        )
        await storage.insert(event)
        return event

    async def _verify_insert_and_claim(self, storage, event):
        """Verify event was inserted and can be claimed."""
        from sagaz.outbox.types import OutboxStatus

        retrieved = await storage.get_by_id(event.event_id)
        assert retrieved is not None
        assert retrieved.saga_id == "saga-integration-test"

        count = await storage.get_pending_count()
        assert count >= 1

        claimed = await storage.claim_batch(worker_id="test-worker", batch_size=10)
        assert len(claimed) >= 1
        assert claimed[0].status == OutboxStatus.CLAIMED
        assert claimed[0].worker_id == "test-worker"

    async def _verify_update_and_query(self, storage, event):
        """Verify status update and saga query."""
        from sagaz.outbox.types import OutboxStatus

        # Need to re-claim since previous claim consumed the event
        claimed = await storage.claim_batch(worker_id="test-worker-2", batch_size=10)
        if claimed:
            updated = await storage.update_status(
                event_id=claimed[0].event_id, status=OutboxStatus.SENT
            )
            assert updated.status == OutboxStatus.SENT
            assert updated.sent_at is not None

        saga_events = await storage.get_events_by_saga("saga-integration-test")
        assert len(saga_events) >= 1

    @pytest.mark.asyncio
    async def test_postgresql_concurrent_claim(self, postgres_container):
        """Test that concurrent claims work correctly with FOR UPDATE SKIP LOCKED."""
        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE, PostgreSQLOutboxStorage
        from sagaz.outbox.types import OutboxEvent

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        storage = PostgreSQLOutboxStorage(connection_string=connection_string)

        try:
            await storage.initialize()

            # Insert multiple events
            for i in range(5):
                event = OutboxEvent(
                    saga_id=f"saga-concurrent-{i}", event_type="test.event", payload={"index": i}
                )
                await storage.insert(event)

            # Concurrent claims - each worker should get different events
            async def claim_worker(worker_id: str):
                return await storage.claim_batch(worker_id=worker_id, batch_size=2)

            results = await asyncio.gather(
                claim_worker("worker-1"),
                claim_worker("worker-2"),
                claim_worker("worker-3"),
            )

            # Collect all claimed event IDs
            all_claimed_ids = []
            for claimed in results:
                for event in claimed:
                    all_claimed_ids.append(event.event_id)

            # No duplicates - each event claimed by exactly one worker
            assert len(all_claimed_ids) == len(set(all_claimed_ids))

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_postgresql_stuck_events(self, postgres_container):
        """Test stuck event detection and release."""
        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE, PostgreSQLOutboxStorage
        from sagaz.outbox.types import OutboxEvent, OutboxStatus

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        storage = PostgreSQLOutboxStorage(connection_string=connection_string)

        try:
            await storage.initialize()

            # Insert and claim an event
            event = OutboxEvent(saga_id="saga-stuck-test", event_type="test.event", payload={})
            await storage.insert(event)
            claimed = await storage.claim_batch(worker_id="stuck-worker", batch_size=1)
            assert len(claimed) == 1

            # Get stuck events (with 0 seconds threshold - immediately stuck)
            stuck = await storage.get_stuck_events(claimed_older_than_seconds=0)
            assert len(stuck) >= 1

            # Release stuck events
            released_count = await storage.release_stuck_events(claimed_older_than_seconds=0)
            assert released_count >= 1

            # Verify event is back to PENDING
            retrieved = await storage.get_by_id(claimed[0].event_id)
            assert retrieved.status == OutboxStatus.PENDING
            assert retrieved.worker_id is None

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_postgresql_inbox_deduplication(self, postgres_container):
        """Test consumer inbox deduplication pattern."""

        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE, PostgreSQLOutboxStorage

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        storage = PostgreSQLOutboxStorage(connection_string=connection_string)

        try:
            await storage.initialize()

            # First insert - should not be duplicate
            is_duplicate = await storage.check_and_insert_inbox(
                event_id="evt-001",
                consumer_name="order-service",
                source_topic="orders",
                event_type="OrderCreated",
                payload={"order_id": "123"},
            )
            assert is_duplicate is False

            # Second insert with same event_id - should be duplicate
            is_duplicate = await storage.check_and_insert_inbox(
                event_id="evt-001",
                consumer_name="order-service",
                source_topic="orders",
                event_type="OrderCreated",
                payload={"order_id": "123"},
            )
            assert is_duplicate is True

            # Different event_id - should not be duplicate
            is_duplicate = await storage.check_and_insert_inbox(
                event_id="evt-002",
                consumer_name="order-service",
                source_topic="orders",
                event_type="OrderCreated",
                payload={"order_id": "456"},
            )
            assert is_duplicate is False

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_postgresql_inbox_with_connection(self, postgres_container):
        """Test inbox insert with provided connection (transactional)."""

        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE, PostgreSQLOutboxStorage

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        storage = PostgreSQLOutboxStorage(connection_string=connection_string)

        try:
            await storage.initialize()

            # Use a connection from the pool
            async with storage._pool.acquire() as conn, conn.transaction():
                is_duplicate = await storage.check_and_insert_inbox(
                    event_id="evt-transactional",
                    consumer_name="payment-service",
                    source_topic="payments",
                    event_type="PaymentProcessed",
                    payload={"payment_id": "pay-789"},
                    connection=conn,
                )
                assert is_duplicate is False

            # Verify it was committed
            is_duplicate = await storage.check_and_insert_inbox(
                event_id="evt-transactional",
                consumer_name="payment-service",
                source_topic="payments",
                event_type="PaymentProcessed",
                payload={"payment_id": "pay-789"},
            )
            assert is_duplicate is True

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_postgresql_update_inbox_duration(self, postgres_container):
        """Test updating processing duration for inbox events."""
        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE, PostgreSQLOutboxStorage

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        storage = PostgreSQLOutboxStorage(connection_string=connection_string)

        try:
            await storage.initialize()

            # Insert an event first
            await storage.check_and_insert_inbox(
                event_id="evt-duration",
                consumer_name="notification-service",
                source_topic="notifications",
                event_type="NotificationSent",
                payload={"notification_id": "notif-123"},
            )

            # Update duration
            await storage.update_inbox_duration(event_id="evt-duration", duration_ms=250)

            # Verify duration was updated (would require query to check)
            # For now, just verify no exception was raised

        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_postgresql_cleanup_inbox(self, postgres_container):
        """Test cleaning up old inbox entries."""
        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE, PostgreSQLOutboxStorage

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        storage = PostgreSQLOutboxStorage(connection_string=connection_string)

        try:
            await storage.initialize()

            # Insert some events
            for i in range(3):
                await storage.check_and_insert_inbox(
                    event_id=f"evt-cleanup-{i}",
                    consumer_name="cleanup-service",
                    source_topic="cleanup",
                    event_type="TestEvent",
                    payload={"test": i},
                )

            # Cleanup entries older than 30 days (should not delete our fresh entries)
            deleted_count = await storage.cleanup_inbox(
                consumer_name="cleanup-service", older_than_days=30
            )
            assert deleted_count == 0  # Nothing old enough to delete

            # Cleanup entries older than 0 days (should delete all)
            deleted_count = await storage.cleanup_inbox(
                consumer_name="cleanup-service", older_than_days=0
            )
            assert deleted_count == 3  # All three should be deleted

        finally:
            await storage.close()


# ============================================
# KAFKA BROKER TESTS
# ============================================


class TestKafkaBrokerIntegration:
    """Integration tests for Kafka broker using testcontainers."""

    @pytest.fixture
    def kafka_container(self):
        """Start a Kafka container for testing."""
        from testcontainers.kafka import KafkaContainer

        # Use the standard KafkaContainer with increased timeout
        kafka = KafkaContainer("confluentinc/cp-kafka:7.5.0")

        # The KafkaContainer class already has good defaults, but we can extend the startup timeout
        kafka.with_env("KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR", "1")
        kafka.with_env("KAFKA_TRANSACTION_STATE_LOG_MIN_ISR", "1")
        kafka.with_env("KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR", "1")

        with kafka:
            yield kafka

    @pytest.mark.asyncio
    async def test_kafka_broker_publish(self, kafka_container):
        """Test connecting and publishing to Kafka."""
        from sagaz.outbox.brokers.kafka import KAFKA_AVAILABLE, KafkaBroker, KafkaBrokerConfig

        if not KAFKA_AVAILABLE:
            pytest.skip("aiokafka not installed")

        bootstrap_servers = kafka_container.get_bootstrap_server()

        config = KafkaBrokerConfig(
            bootstrap_servers=bootstrap_servers,
            client_id="sage-test",
            enable_idempotence=True,
        )

        broker = KafkaBroker(config)

        try:
            # Connect
            await broker.connect()

            # Health check
            healthy = await broker.health_check()
            assert healthy is True

            # Publish a message
            await broker.publish(
                topic="test-orders",
                message=b'{"order_id": "ORD-123"}',
                headers={"trace_id": "test-trace"},
                key="order-123",
            )

            # Publish another without key/headers
            await broker.publish(
                topic="test-events",
                message=b'{"event": "test"}',
            )

        finally:
            await broker.close()

    @pytest.mark.asyncio
    async def test_kafka_broker_from_env(self, kafka_container, monkeypatch):
        """Test creating Kafka broker from environment variables."""
        from sagaz.outbox.brokers.kafka import KAFKA_AVAILABLE, KafkaBroker

        if not KAFKA_AVAILABLE:
            pytest.skip("aiokafka not installed")

        bootstrap_servers = kafka_container.get_bootstrap_server()

        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", bootstrap_servers)
        monkeypatch.setenv("KAFKA_CLIENT_ID", "env-test-client")

        broker = KafkaBroker.from_env()

        try:
            await broker.connect()
            assert await broker.health_check() is True
        finally:
            await broker.close()


# ============================================
# RABBITMQ BROKER TESTS (if available)
# ============================================


class TestRabbitMQBrokerIntegration:
    """Integration tests for RabbitMQ broker using testcontainers."""

    @pytest.fixture
    def rabbitmq_container(self):
        """Start a RabbitMQ container for testing."""
        try:
            from testcontainers.rabbitmq import RabbitMqContainer
        except ImportError:
            pytest.skip("testcontainers[rabbitmq] not installed")

        # Use standard RabbitMQ container with management plugin
        rabbitmq = RabbitMqContainer("rabbitmq:3.12-management")

        with rabbitmq:
            yield rabbitmq

    @pytest.mark.asyncio
    async def test_rabbitmq_broker_publish(self, rabbitmq_container):
        """Test connecting and publishing to RabbitMQ."""
        from sagaz.outbox.brokers.rabbitmq import (
            RABBITMQ_AVAILABLE,
            RabbitMQBroker,
            RabbitMQBrokerConfig,
        )

        if not RABBITMQ_AVAILABLE:
            pytest.skip("aio-pika not installed")

        # Get AMQP URL from container (manually construct if get_connection_url missing)
        try:
            amqp_url = rabbitmq_container.get_connection_url()
        except AttributeError:
            # Fallback for older/newer versions
            host = rabbitmq_container.get_container_host_ip()
            port = rabbitmq_container.get_exposed_port(5672)
            amqp_url = f"amqp://guest:guest@{host}:{port}/"

        config = RabbitMQBrokerConfig(
            url=amqp_url,
            exchange_name="sage-test-exchange",
            exchange_type="topic",
            connection_timeout=30.0,  # Increase timeout for container
        )

        broker = RabbitMQBroker(config)

        try:
            # Connect (declares exchange)
            await broker.connect()

            # Health check
            healthy = await broker.health_check()
            assert healthy is True

            # Declare a test queue
            await broker.declare_queue(
                queue_name="test-orders-queue",
                routing_key="orders.#",
            )

            # Publish a message
            await broker.publish(
                topic="orders.created",
                message=b'{"order_id": "ORD-456"}',
                headers={"trace_id": "test-trace"},
            )

        finally:
            await broker.close()


# ============================================
# OUTBOX WORKER INTEGRATION TESTS
# ============================================


class TestOutboxWorkerIntegration:
    """Integration tests for the complete outbox worker flow."""

    @pytest.fixture
    def postgres_container(self):
        """Start a PostgreSQL container for testing."""
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:15") as postgres:
            yield postgres

    @pytest.mark.asyncio
    async def test_worker_process_batch(self, postgres_container):
        """Test worker processing a batch of events."""
        from sagaz.outbox.brokers.memory import InMemoryBroker
        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE, PostgreSQLOutboxStorage
        from sagaz.outbox.types import OutboxConfig, OutboxEvent
        from sagaz.outbox.worker import OutboxWorker

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not installed")

        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        storage = PostgreSQLOutboxStorage(connection_string=connection_string)
        broker = InMemoryBroker()

        try:
            await storage.initialize()
            await broker.connect()

            # Insert events
            for i in range(3):
                event = OutboxEvent(
                    saga_id=f"saga-worker-{i}", event_type="worker.test", payload={"index": i}
                )
                await storage.insert(event)

            # Create worker
            config = OutboxConfig(batch_size=10)
            worker = OutboxWorker(
                storage=storage,
                broker=broker,
                config=config,
            )

            # Process one batch
            processed = await worker.process_batch()

            # All 3 events should be processed
            assert processed == 3

            # Verify events are marked as SENT
            count = await storage.get_pending_count()
            assert count == 0

            # Verify messages were published to broker
            messages = broker.get_messages("worker.test")
            assert len(messages) == 3

        finally:
            await broker.close()
            await storage.close()
