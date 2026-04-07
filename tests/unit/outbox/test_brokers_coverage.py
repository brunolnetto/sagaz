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


class TestRabbitMQImportErrorFallback:
    """Lines 33-38: RABBITMQ_AVAILABLE=False when aio_pika is absent."""

    def test_rabbitmq_unavailable_flag(self):
        """Lines 33-38: when ImportError, RABBITMQ_AVAILABLE is False."""
        import importlib
        import sys

        import sagaz.outbox.brokers.rabbitmq as rmq_mod

        original = sys.modules.get("aio_pika")
        try:
            sys.modules["aio_pika"] = None  # type: ignore[assignment]
            importlib.reload(rmq_mod)
            assert rmq_mod.RABBITMQ_AVAILABLE is False
            assert rmq_mod.aio_pika is None
        finally:
            if original is not None:
                sys.modules["aio_pika"] = original
            else:
                sys.modules.pop("aio_pika", None)
            importlib.reload(rmq_mod)

    @pytest.mark.asyncio
    async def test_connect_skips_confirm_delivery_when_false(self):
        """Line 147->151: confirm_delivery=False skips set_qos call."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker, RabbitMQBrokerConfig

        config = RabbitMQBrokerConfig(
            url="amqp://guest:guest@localhost/",
            confirm_delivery=False,
        )
        broker = RabbitMQBroker(config)

        mock_conn = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_conn.channel.return_value = mock_channel
        mock_channel.set_qos = AsyncMock()
        mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)

        with patch("aio_pika.connect_robust", return_value=mock_conn):
            await broker.connect()

        mock_channel.set_qos.assert_not_called()


class TestRedisBrokerMissingBranches:
    """Lines 37-39, 125-126, 240->exit, 290, 365->368 in redis broker."""

    def test_redis_unavailable_flag(self):
        """Lines 37-39: when ImportError, REDIS_AVAILABLE=False."""
        import importlib
        import sys

        import sagaz.outbox.brokers.redis as redis_broker_mod

        original = sys.modules.get("redis.asyncio")
        try:
            sys.modules["redis.asyncio"] = None  # type: ignore[assignment]
            importlib.reload(redis_broker_mod)
            assert redis_broker_mod.REDIS_AVAILABLE is False
        finally:
            if original is not None:
                sys.modules["redis.asyncio"] = original
            else:
                sys.modules.pop("redis.asyncio", None)
            importlib.reload(redis_broker_mod)

    @pytest.mark.asyncio
    async def test_connect_raises_when_redis_unavailable(self):
        """Lines 125-126: MissingDependencyError when REDIS_AVAILABLE=False."""
        from unittest.mock import patch

        import sagaz.outbox.brokers.redis as redis_broker_mod
        from sagaz.core.exceptions import MissingDependencyError
        from sagaz.outbox.brokers.redis import RedisBrokerConfig

        with patch.object(redis_broker_mod, "REDIS_AVAILABLE", False):
            with pytest.raises(MissingDependencyError):
                redis_broker_mod.RedisBroker(RedisBrokerConfig(url="redis://localhost"))

    @pytest.mark.asyncio
    async def test_close_when_client_is_none(self):
        """Line 240->exit: close() does nothing when _client is None."""
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        broker = RedisBroker(RedisBrokerConfig(url="redis://localhost"))
        # _client is None by default; close() should be a no-op
        await broker.close()  # must not raise

    @pytest.mark.asyncio
    async def test_ensure_consumer_group_raises_non_busygroup(self):
        """Line 290: re-raise ResponseError when not BUSYGROUP."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        broker = RedisBroker(RedisBrokerConfig(url="redis://localhost"))
        mock_client = AsyncMock()

        import redis.asyncio as real_redis

        err = real_redis.ResponseError("WRONGTYPE")
        mock_client.xgroup_create = AsyncMock(side_effect=err)
        broker._client = mock_client

        with pytest.raises(real_redis.ResponseError):
            await broker.ensure_consumer_group()

    def test_mask_url_no_colon_in_auth(self):
        """Lines 365->368: return url unchanged when no colon in auth part."""
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        config = RedisBrokerConfig(url="redis://user@host:6379/0")
        broker = RedisBroker(config)
        # parts[0] = "redis://user", no ":" after splitting on "@" from the left
        masked = broker._safe_url()
        assert "****" in masked or masked == config.url


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
