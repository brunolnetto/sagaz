"""
Tests for broker module coverage.

These tests cover broker configuration, helper methods, and initialization
without requiring actual connections to external services.
"""

import pytest

from sagaz.outbox.brokers.kafka import (
    KAFKA_AVAILABLE,
    KafkaBroker,
    KafkaBrokerConfig,
    is_kafka_available,
)
from sagaz.outbox.brokers.memory import InMemoryBroker
from sagaz.outbox.brokers.rabbitmq import (
    RABBITMQ_AVAILABLE,
    RabbitMQBroker,
    RabbitMQBrokerConfig,
    is_rabbitmq_available,
)


class TestKafkaBrokerConfig:
    """Tests for KafkaBroker configuration."""

    def test_kafka_is_available(self):
        """Verify aiokafka is installed in test environment."""
        assert KAFKA_AVAILABLE is True
        assert is_kafka_available() is True

    def test_default_config(self):
        """Test KafkaBrokerConfig with defaults."""
        config = KafkaBrokerConfig()
        assert config.bootstrap_servers == "localhost:9092"
        assert config.client_id == "sage-outbox"
        assert config.acks == "all"
        assert config.enable_idempotence is True
        assert config.max_batch_size == 16384
        assert config.linger_ms == 5
        assert config.compression_type == "gzip"
        assert config.request_timeout_ms == 30000

    def test_custom_config(self):
        """Test KafkaBrokerConfig with custom values."""
        config = KafkaBrokerConfig(
            bootstrap_servers="kafka1:9092,kafka2:9092",
            client_id="my-app",
            acks="1",
            enable_idempotence=False,
            compression_type="snappy",
        )
        assert config.bootstrap_servers == "kafka1:9092,kafka2:9092"
        assert config.client_id == "my-app"
        assert config.acks == "1"
        assert config.enable_idempotence is False
        assert config.compression_type == "snappy"

    def test_sasl_config(self):
        """Test KafkaBrokerConfig with SASL settings."""
        config = KafkaBrokerConfig(
            sasl_mechanism="PLAIN",
            sasl_username="user",
            sasl_password="secret",
            security_protocol="SASL_SSL",
        )
        assert config.sasl_mechanism == "PLAIN"
        assert config.sasl_username == "user"
        assert config.sasl_password == "secret"
        assert config.security_protocol == "SASL_SSL"


class TestKafkaBrokerInitialization:
    """Tests for KafkaBroker initialization."""

    def test_broker_init_default_config(self):
        """Test initializing broker with default config."""
        broker = KafkaBroker()
        assert broker.config.bootstrap_servers == "localhost:9092"
        assert broker._producer is None
        assert broker._connected is False

    def test_broker_init_custom_config(self):
        """Test initializing broker with custom config."""
        config = KafkaBrokerConfig(bootstrap_servers="kafka:9092")
        broker = KafkaBroker(config)
        assert broker.config.bootstrap_servers == "kafka:9092"

    def test_from_env(self, monkeypatch):
        """Test creating broker from environment variables."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "env-kafka:9092")
        monkeypatch.setenv("KAFKA_CLIENT_ID", "env-client")

        broker = KafkaBroker.from_env()
        assert broker.config.bootstrap_servers == "env-kafka:9092"
        assert broker.config.client_id == "env-client"


class TestKafkaBrokerHelpers:
    """Tests for KafkaBroker helper methods."""

    def test_convert_headers_none(self):
        """Test header conversion with None."""
        result = KafkaBroker._convert_headers(None)
        assert result is None

    def test_convert_headers_empty(self):
        """Test header conversion with empty dict."""
        result = KafkaBroker._convert_headers({})
        assert result is None

    def test_convert_headers_with_values(self):
        """Test header conversion with string values."""
        headers = {"trace_id": "abc123", "source": "test"}
        result = KafkaBroker._convert_headers(headers)

        assert len(result) == 2
        assert ("trace_id", b"abc123") in result
        assert ("source", b"test") in result

    def test_encode_key_none(self):
        """Test key encoding with None."""
        result = KafkaBroker._encode_key(None)
        assert result is None

    def test_encode_key_with_value(self):
        """Test key encoding with string."""
        result = KafkaBroker._encode_key("order-123")
        assert result == b"order-123"


class TestRabbitMQBrokerConfig:
    """Tests for RabbitMQBroker configuration."""

    def test_rabbitmq_is_available(self):
        """Verify aio-pika is installed in test environment."""
        assert RABBITMQ_AVAILABLE is True
        assert is_rabbitmq_available() is True

    def test_default_config(self):
        """Test RabbitMQBrokerConfig with defaults."""
        config = RabbitMQBrokerConfig()
        assert config.url == "amqp://guest:guest@localhost/"
        assert config.exchange_name == "sage.outbox"
        assert config.exchange_type == "topic"
        assert config.connection_timeout == 30.0
        assert config.heartbeat == 60

    def test_custom_config(self):
        """Test RabbitMQBrokerConfig with custom values."""
        config = RabbitMQBrokerConfig(
            url="amqp://admin:secret@rmq.example.com:5672/vhost",
            exchange_name="orders",
            exchange_type="direct",
            connection_timeout=60.0,
        )
        assert config.url == "amqp://admin:secret@rmq.example.com:5672/vhost"
        assert config.exchange_name == "orders"
        assert config.exchange_type == "direct"
        assert config.connection_timeout == 60.0


class TestRabbitMQBrokerInitialization:
    """Tests for RabbitMQBroker initialization."""

    def test_broker_init_default_config(self):
        """Test initializing broker with default config."""
        broker = RabbitMQBroker()
        assert broker.config.url == "amqp://guest:guest@localhost/"
        assert broker._connection is None
        assert broker._channel is None
        assert broker._exchange is None

    def test_broker_init_custom_config(self):
        """Test initializing broker with custom config."""
        config = RabbitMQBrokerConfig(url="amqp://rmq:5672/")
        broker = RabbitMQBroker(config)
        assert broker.config.url == "amqp://rmq:5672/"

    def test_from_env(self, monkeypatch):
        """Test creating RabbitMQ broker from environment variables."""
        monkeypatch.setenv("RABBITMQ_URL", "amqp://admin:secret@rmq.example.com/vhost")
        monkeypatch.setenv("RABBITMQ_EXCHANGE", "my-exchange")
        monkeypatch.setenv("RABBITMQ_EXCHANGE_TYPE", "direct")

        broker = RabbitMQBroker.from_env()
        assert broker.config.url == "amqp://admin:secret@rmq.example.com/vhost"
        assert broker.config.exchange_name == "my-exchange"
        assert broker.config.exchange_type == "direct"


class TestKafkaBrokerNotConnected:
    """Tests for Kafka broker when not connected."""

    @pytest.mark.asyncio
    async def test_publish_without_connection(self):
        """Test that publish raises error when not connected."""
        from sagaz.outbox.brokers.base import BrokerConnectionError

        broker = KafkaBroker()
        with pytest.raises(BrokerConnectionError, match="not connected"):
            await broker.publish("topic", b"message")

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        """Test health check returns False when not connected."""
        broker = KafkaBroker()
        healthy = await broker.health_check()
        assert healthy is False


class TestRabbitMQBrokerNotConnected:
    """Tests for RabbitMQ broker when not connected."""

    @pytest.mark.asyncio
    async def test_publish_without_connection(self):
        """Test that publish raises error when not connected."""
        from sagaz.outbox.brokers.base import BrokerConnectionError

        broker = RabbitMQBroker()
        with pytest.raises(BrokerConnectionError, match="not connected"):
            await broker.publish("topic", b"message")

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        """Test health check returns False when not connected."""
        broker = RabbitMQBroker()
        healthy = await broker.health_check()
        assert healthy is False



class TestInMemoryBroker:
    """Tests for InMemoryBroker."""

    @pytest.mark.asyncio
    async def test_publish_and_get_messages(self):
        """Test publishing and retrieving messages."""
        broker = InMemoryBroker()

        await broker.connect()
        await broker.publish(
            topic="orders",
            message=b'{"order": "123"}',
            headers={"type": "created"},
        )

        messages = broker.get_messages("orders")
        assert len(messages) == 1
        assert messages[0]["message"] == b'{"order": "123"}'
        assert messages[0]["headers"] == {"type": "created"}

    @pytest.mark.asyncio
    async def test_clear_messages(self):
        """Test clearing messages."""
        broker = InMemoryBroker()

        await broker.connect()
        await broker.publish("orders", b"test1")
        await broker.publish("orders", b"test2")

        assert len(broker.get_messages("orders")) == 2

        broker.clear()
        assert len(broker.get_messages("orders")) == 0

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check."""
        broker = InMemoryBroker()
        await broker.connect()

        result = await broker.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing broker."""
        broker = InMemoryBroker()
        await broker.connect()
        await broker.close()
        # Should not raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
