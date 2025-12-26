"""
Comprehensive tests for Redis broker and broker factory.

Covers:
- RedisBroker with mocked redis
- RedisBrokerConfig
- create_broker factory
- get_available_brokers
- create_broker_from_env
"""

from unittest.mock import AsyncMock, patch

import pytest

# ============================================
# REDIS BROKER MOCKED TESTS
# ============================================


class TestRedisBrokerConfig:
    """Test RedisBrokerConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBrokerConfig

            config = RedisBrokerConfig()

            assert config.url == "redis://localhost:6379/0"
            assert config.stream_name == "sage.outbox"
            assert config.max_stream_length == 10000
            assert config.consumer_group == "sage-workers"

    def test_from_env(self, monkeypatch):
        """Test creating config from environment variables."""
        monkeypatch.setenv("REDIS_URL", "redis://myhost:6380/1")
        monkeypatch.setenv("REDIS_STREAM_NAME", "my-stream")
        monkeypatch.setenv("REDIS_MAX_STREAM_LENGTH", "5000")
        monkeypatch.setenv("REDIS_CONSUMER_GROUP", "my-group")
        monkeypatch.setenv("REDIS_CONSUMER_NAME", "my-worker")
        monkeypatch.setenv("REDIS_SSL", "true")

        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBrokerConfig

            config = RedisBrokerConfig.from_env()

            assert config.url == "redis://myhost:6380/1"
            assert config.stream_name == "my-stream"
            assert config.max_stream_length == 5000
            assert config.ssl is True


class TestRedisBrokerMocked:
    """Test RedisBroker with mocked redis."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        client = AsyncMock()
        client.ping = AsyncMock(return_value=True)
        client.xadd = AsyncMock(return_value=b"1234567890-0")
        client.close = AsyncMock()
        client.xgroup_create = AsyncMock()
        client.xreadgroup = AsyncMock(return_value=[])
        client.xack = AsyncMock()
        client.xinfo_stream = AsyncMock(
            return_value={"length": 100, "first-entry": None, "last-entry": None, "groups": 1}
        )
        return client

    @pytest.mark.asyncio
    async def test_connect(self, mock_redis_client):
        """Test connecting to Redis."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

            mock_redis.from_url.return_value = mock_redis_client

            config = RedisBrokerConfig(url="redis://localhost:6379")
            broker = RedisBroker(config)

            await broker.connect()

            assert broker._connected is True
            mock_redis_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self, mock_redis_client):
        """Test connection failure handling."""
        from sagaz.outbox.brokers.base import BrokerConnectionError

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis_client.ping.side_effect = Exception("Connection refused")
            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()

            with pytest.raises(BrokerConnectionError):
                await broker.connect()

    @pytest.mark.asyncio
    async def test_publish(self, mock_redis_client):
        """Test publishing a message."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()

            await broker.publish(
                topic="test.event",
                message=b'{"data": "test"}',
                headers={"trace_id": "abc123"},
                key="event-key",
            )

            mock_redis_client.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_not_connected(self):
        """Test publish fails when not connected."""
        from sagaz.outbox.brokers.base import BrokerError

        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBroker

            broker = RedisBroker()

            with pytest.raises(BrokerError):
                await broker.publish("topic", b"message")

    @pytest.mark.asyncio
    async def test_publish_failure(self, mock_redis_client):
        """Test publish error handling."""
        from sagaz.outbox.brokers.base import BrokerPublishError

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis_client.xadd.side_effect = Exception("Stream error")
            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()

            with pytest.raises(BrokerPublishError):
                await broker.publish("topic", b"message")

    @pytest.mark.asyncio
    async def test_close(self, mock_redis_client):
        """Test closing the connection."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()
            await broker.close()

            assert broker._connected is False
            mock_redis_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_with_error(self, mock_redis_client):
        """Test close handles errors gracefully."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis_client.close.side_effect = Exception("Close error")
            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()

            # Should not raise
            await broker.close()

            assert broker._connected is False

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, mock_redis_client):
        """Test health check when healthy."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()

            result = await broker.health_check()

            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        """Test health check when not connected."""
        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBroker

            broker = RedisBroker()

            result = await broker.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_ping_fails(self, mock_redis_client):
        """Test health check when ping fails."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()

            mock_redis_client.ping.side_effect = Exception("Ping failed")

            result = await broker.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_ensure_consumer_group_new(self, mock_redis_client):
        """Test creating a new consumer group."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()
            await broker.ensure_consumer_group()

            mock_redis_client.xgroup_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_consumer_group_exists(self, mock_redis_client):
        """Test handling existing consumer group."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            # Simulate BUSYGROUP error (group already exists)
            mock_redis_client.xgroup_create.side_effect = mock_redis.ResponseError(
                "BUSYGROUP Consumer Group name already exists"
            )
            mock_redis.from_url.return_value = mock_redis_client
            mock_redis.ResponseError = type("ResponseError", (Exception,), {})
            mock_redis_client.xgroup_create.side_effect = mock_redis.ResponseError(
                "BUSYGROUP Consumer Group name already exists"
            )

            broker = RedisBroker()
            await broker.connect()

            # Should not raise
            await broker.ensure_consumer_group()

    @pytest.mark.asyncio
    async def test_ensure_consumer_group_not_connected(self):
        """Test ensure_consumer_group fails when not connected."""
        from sagaz.outbox.brokers.base import BrokerError

        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBroker

            broker = RedisBroker()

            with pytest.raises(BrokerError):
                await broker.ensure_consumer_group()

    @pytest.mark.asyncio
    async def test_read_messages(self, mock_redis_client):
        """Test reading messages from stream."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()

            await broker.read_messages(count=5)

            mock_redis_client.xreadgroup.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_messages_not_connected(self):
        """Test read_messages fails when not connected."""
        from sagaz.outbox.brokers.base import BrokerError

        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBroker

            broker = RedisBroker()

            with pytest.raises(BrokerError):
                await broker.read_messages()

    @pytest.mark.asyncio
    async def test_acknowledge(self, mock_redis_client):
        """Test acknowledging a message."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()

            await broker.acknowledge("1234567890-0")

            mock_redis_client.xack.assert_called_once()

    @pytest.mark.asyncio
    async def test_acknowledge_not_connected(self):
        """Test acknowledge fails when not connected."""
        from sagaz.outbox.brokers.base import BrokerError

        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBroker

            broker = RedisBroker()

            with pytest.raises(BrokerError):
                await broker.acknowledge("1234567890-0")

    @pytest.mark.asyncio
    async def test_get_stream_info(self, mock_redis_client):
        """Test getting stream info."""
        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            from sagaz.outbox.brokers.redis import RedisBroker

            mock_redis.from_url.return_value = mock_redis_client

            broker = RedisBroker()
            await broker.connect()

            info = await broker.get_stream_info()

            assert info["length"] == 100

    @pytest.mark.asyncio
    async def test_get_stream_info_not_connected(self):
        """Test get_stream_info fails when not connected."""
        from sagaz.outbox.brokers.base import BrokerError

        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBroker

            broker = RedisBroker()

            with pytest.raises(BrokerError):
                await broker.get_stream_info()

    def test_safe_url_masks_password(self):
        """Test that password is masked in URL for logging."""
        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

            config = RedisBrokerConfig(url="redis://user:secret123@localhost:6379/0")
            broker = RedisBroker(config)

            safe_url = broker._safe_url()

            assert "secret123" not in safe_url
            assert "****" in safe_url

    def test_safe_url_no_password(self):
        """Test safe URL with no password."""
        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

            config = RedisBrokerConfig(url="redis://localhost:6379/0")
            broker = RedisBroker(config)

            safe_url = broker._safe_url()

            assert safe_url == "redis://localhost:6379/0"

    def test_from_env(self, monkeypatch):
        """Test creating broker from environment."""
        monkeypatch.setenv("REDIS_URL", "redis://myhost:6380")

        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import RedisBroker

            broker = RedisBroker.from_env()

            assert broker.config.url == "redis://myhost:6380"

    def test_is_redis_available(self):
        """Test is_redis_available function."""
        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.redis import is_redis_available

            assert is_redis_available() is True


# ============================================
# BROKER FACTORY TESTS
# ============================================


class TestBrokerFactory:
    """Test broker factory functions."""

    def test_get_available_brokers_includes_memory(self):
        """Test memory broker is always available."""
        from sagaz.outbox.brokers.factory import get_available_brokers

        available = get_available_brokers()

        assert "memory" in available

    def test_get_available_brokers_with_all_deps(self):
        """Test get_available_brokers with all deps mocked."""
        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
        ):
            from sagaz.outbox.brokers.factory import get_available_brokers

            available = get_available_brokers()

            assert "memory" in available
            assert "kafka" in available or "rabbitmq" in available or "redis" in available

    def test_create_broker_memory(self):
        """Test creating memory broker."""
        from sagaz.outbox.brokers.factory import create_broker
        from sagaz.outbox.brokers.memory import InMemoryBroker

        broker = create_broker("memory")

        assert isinstance(broker, InMemoryBroker)

    def test_create_broker_kafka(self):
        """Test creating Kafka broker."""
        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.factory import create_broker

            broker = create_broker("kafka", bootstrap_servers="localhost:9092")

            assert broker is not None

    def test_create_broker_rabbitmq(self):
        """Test creating RabbitMQ broker."""
        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.factory import create_broker

            broker = create_broker("rabbitmq", url="amqp://localhost")

            assert broker is not None

    def test_create_broker_redis(self):
        """Test creating Redis broker."""
        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.factory import create_broker

            broker = create_broker("redis", url="redis://localhost")

            assert broker is not None

    def test_create_broker_unknown_type(self):
        """Test creating unknown broker type raises ValueError."""
        from sagaz.outbox.brokers.factory import create_broker

        with pytest.raises(ValueError, match="Unknown broker type"):
            create_broker("unknown_broker")

    def test_create_broker_missing_dependency(self):
        """Test creating broker with missing dependency."""
        from sagaz.exceptions import MissingDependencyError

        with patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", False):
            from sagaz.outbox.brokers.factory import create_broker

            with pytest.raises(MissingDependencyError):
                create_broker("kafka")

    def test_create_broker_case_insensitive(self):
        """Test create_broker is case insensitive."""
        from sagaz.outbox.brokers.factory import create_broker
        from sagaz.outbox.brokers.memory import InMemoryBroker

        broker1 = create_broker("MEMORY")
        broker2 = create_broker("Memory")
        broker3 = create_broker("  memory  ")

        assert isinstance(broker1, InMemoryBroker)
        assert isinstance(broker2, InMemoryBroker)
        assert isinstance(broker3, InMemoryBroker)

    def test_create_broker_from_env_memory(self, monkeypatch):
        """Test create_broker_from_env with memory."""
        monkeypatch.setenv("BROKER_TYPE", "memory")

        from sagaz.outbox.brokers.factory import create_broker_from_env
        from sagaz.outbox.brokers.memory import InMemoryBroker

        broker = create_broker_from_env()

        assert isinstance(broker, InMemoryBroker)

    def test_create_broker_from_env_kafka(self, monkeypatch):
        """Test create_broker_from_env with Kafka."""
        monkeypatch.setenv("BROKER_TYPE", "kafka")
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.factory import create_broker_from_env

            broker = create_broker_from_env()

            assert broker is not None

    def test_create_broker_from_env_rabbitmq(self, monkeypatch):
        """Test create_broker_from_env with RabbitMQ."""
        monkeypatch.setenv("BROKER_TYPE", "rabbitmq")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost")

        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.factory import create_broker_from_env

            broker = create_broker_from_env()

            assert broker is not None

    def test_create_broker_from_env_redis(self, monkeypatch):
        """Test create_broker_from_env with Redis."""
        monkeypatch.setenv("BROKER_TYPE", "redis")
        monkeypatch.setenv("REDIS_URL", "redis://localhost")

        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True):
            from sagaz.outbox.brokers.factory import create_broker_from_env

            broker = create_broker_from_env()

            assert broker is not None

    def test_create_broker_from_env_unknown(self, monkeypatch):
        """Test create_broker_from_env with unknown type."""
        monkeypatch.setenv("BROKER_TYPE", "unknown")

        from sagaz.outbox.brokers.factory import create_broker_from_env

        with pytest.raises(ValueError, match="Unknown BROKER_TYPE"):
            create_broker_from_env()

    def test_create_broker_from_env_default(self, monkeypatch):
        """Test create_broker_from_env defaults to memory."""
        monkeypatch.delenv("BROKER_TYPE", raising=False)

        from sagaz.outbox.brokers.factory import create_broker_from_env
        from sagaz.outbox.brokers.memory import InMemoryBroker

        broker = create_broker_from_env()

        assert isinstance(broker, InMemoryBroker)

    def test_print_available_brokers(self, capsys):
        """Test print_available_brokers outputs correctly."""
        from sagaz.outbox.brokers.factory import print_available_brokers

        # Should not raise
        print_available_brokers()

        captured = capsys.readouterr()
        assert "memory" in captured.out.lower()
