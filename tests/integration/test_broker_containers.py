"""
Integration tests for Kafka and RabbitMQ brokers using testcontainers.

Uses session-scoped fixtures from conftest.py for performance.
"""

import pytest

try:
    from testcontainers.kafka import KafkaContainer
    from testcontainers.rabbitmq import RabbitMqContainer
    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False

# Mark all tests in this module as integration tests (excluded by default)
pytestmark = pytest.mark.integration

@pytest.mark.xdist_group(name="containers")
class TestKafkaBrokerIntegration:
    """Integration tests for KafkaBroker with real Kafka container."""

    @pytest.mark.asyncio
    async def test_kafka_full_lifecycle(self, kafka_container):
        """Test complete Kafka broker lifecycle: connect, publish, health_check, close."""
        from sagaz.outbox.brokers.kafka import (
            KAFKA_AVAILABLE,
            KafkaBroker,
            KafkaBrokerConfig,
        )

        if not KAFKA_AVAILABLE:
            pytest.skip("aiokafka not installed")

        if kafka_container is None:
             pytest.skip("Kafka container not available")

        # Get bootstrap server from container
        bootstrap_server = kafka_container.get_bootstrap_server()

        config = KafkaBrokerConfig(
            bootstrap_servers=bootstrap_server,
            client_id="test-client",
            request_timeout_ms=60000,
        )

        broker = KafkaBroker(config)

        try:
            # Connect
            await broker.connect()
            assert broker._connected is True

            # Double connect should be no-op
            await broker.connect()
            assert broker._connected is True

            # Health check
            healthy = await broker.health_check()
            assert healthy is True

            # Publish a message
            await broker.publish(
                topic="test-topic",
                message=b'{"order_id": "ORD-123"}',
                headers={"trace_id": "test-trace"},
                key="order-123",
            )

            # Publish without headers or key
            await broker.publish(
                topic="test-topic",
                message=b'{"event": "test"}',
            )

        finally:
            # Close
            await broker.close()
            assert broker._connected is False

    @pytest.mark.asyncio
    async def test_kafka_publish_without_connection(self):
        """Test that publish raises error when not connected."""
        from sagaz.outbox.brokers.base import BrokerConnectionError
        from sagaz.outbox.brokers.kafka import KAFKA_AVAILABLE, KafkaBroker

        if not KAFKA_AVAILABLE:
            pytest.skip("aiokafka not installed")

        broker = KafkaBroker()

        with pytest.raises(BrokerConnectionError, match="not connected"):
            await broker.publish("topic", b"message")

    @pytest.mark.asyncio
    async def test_kafka_health_check_not_connected(self):
        """Test health check returns False when not connected."""
        from sagaz.outbox.brokers.kafka import KAFKA_AVAILABLE, KafkaBroker

        if not KAFKA_AVAILABLE:
            pytest.skip("aiokafka not installed")

        broker = KafkaBroker()
        healthy = await broker.health_check()
        assert healthy is False


@pytest.mark.xdist_group(name="containers")
class TestRabbitMQBrokerIntegration:
    """Integration tests for RabbitMQBroker with real RabbitMQ container."""

    def _get_amqp_url(self, container) -> str:
        """Get AMQP URL from container."""
        try:
            return container.get_connection_url()
        except AttributeError:
            host = container.get_container_host_ip()
            port = container.get_exposed_port(5672)
            return f"amqp://guest:guest@{host}:{port}/"

    @pytest.mark.asyncio
    async def test_rabbitmq_full_lifecycle(self, rabbitmq_container):
        """Test complete RabbitMQ broker lifecycle: connect, publish, health_check, close."""
        from sagaz.outbox.brokers.rabbitmq import (
            RABBITMQ_AVAILABLE,
            RabbitMQBroker,
            RabbitMQBrokerConfig,
        )

        if not RABBITMQ_AVAILABLE:
            pytest.skip("aio-pika not installed")

        if rabbitmq_container is None:
             pytest.skip("RabbitMQ container not available")

        amqp_url = self._get_amqp_url(rabbitmq_container)

        config = RabbitMQBrokerConfig(
            url=amqp_url,
            exchange_name="test-exchange",
            exchange_type="topic",
            connection_timeout=60.0,
        )

        broker = RabbitMQBroker(config)

        try:
            # Connect
            await broker.connect()
            assert broker._connected is True

            # Double connect should be no-op
            await broker.connect()
            assert broker._connected is True

            # Health check
            healthy = await broker.health_check()
            assert healthy is True

            # Declare a queue
            await broker.declare_queue(
                queue_name="test-orders",
                routing_key="orders.#",
            )

            # Publish a message
            await broker.publish(
                topic="orders.created",
                message=b'{"order_id": "ORD-456"}',
                headers={"trace_id": "test-trace"},
            )

            # Publish without headers
            await broker.publish(
                topic="orders.updated",
                message=b'{"event": "update"}',
            )

        finally:
            # Close
            await broker.close()
            assert broker._connected is False

    @pytest.mark.asyncio
    async def test_rabbitmq_publish_without_connection(self):
        """Test that publish raises error when not connected."""
        from sagaz.outbox.brokers.base import BrokerConnectionError
        from sagaz.outbox.brokers.rabbitmq import RABBITMQ_AVAILABLE, RabbitMQBroker

        if not RABBITMQ_AVAILABLE:
            pytest.skip("aio-pika not installed")

        broker = RabbitMQBroker()

        with pytest.raises(BrokerConnectionError, match="not connected"):
            await broker.publish("topic", b"message")

    @pytest.mark.asyncio
    async def test_rabbitmq_health_check_not_connected(self):
        """Test health check returns False when not connected."""
        from sagaz.outbox.brokers.rabbitmq import RABBITMQ_AVAILABLE, RabbitMQBroker

        if not RABBITMQ_AVAILABLE:
            pytest.skip("aio-pika not installed")

        broker = RabbitMQBroker()
        healthy = await broker.health_check()
        assert healthy is False

    @pytest.mark.asyncio
    async def test_rabbitmq_from_env(self, monkeypatch):
        """Test creating RabbitMQ broker from environment variables."""
        from sagaz.outbox.brokers.rabbitmq import RABBITMQ_AVAILABLE, RabbitMQBroker

        if not RABBITMQ_AVAILABLE:
            pytest.skip("aio-pika not installed")

        monkeypatch.setenv("RABBITMQ_URL", "amqp://admin:secret@rmq.example.com/vhost")
        monkeypatch.setenv("RABBITMQ_EXCHANGE", "my-exchange")
        monkeypatch.setenv("RABBITMQ_EXCHANGE_TYPE", "direct")

        broker = RabbitMQBroker.from_env()
        assert broker.config.url == "amqp://admin:secret@rmq.example.com/vhost"
        assert broker.config.exchange_name == "my-exchange"
        assert broker.config.exchange_type == "direct"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
