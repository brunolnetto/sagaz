"""
Tests for Redis Message Broker.

Tests written first following TDD approach.
"""

import os
from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest


# Test configuration
class TestRedisBrokerConfig:
    """Tests for RedisBrokerConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        from sagaz.outbox.brokers.redis import RedisBrokerConfig

        config = RedisBrokerConfig()

        assert config.url == "redis://localhost:6379/0"
        assert config.stream_name == "sage.outbox"
        assert config.max_stream_length == 10000
        assert config.consumer_group == "sage-workers"
        assert config.connection_timeout_seconds == 30.0

    def test_custom_values(self):
        """Test custom configuration values."""
        from sagaz.outbox.brokers.redis import RedisBrokerConfig

        config = RedisBrokerConfig(
            url="redis://custom:6380/1",
            stream_name="custom-stream",
            max_stream_length=5000,
            consumer_group="custom-group",
        )

        assert config.url == "redis://custom:6380/1"
        assert config.stream_name == "custom-stream"
        assert config.max_stream_length == 5000
        assert config.consumer_group == "custom-group"

    def test_from_env(self):
        """Test creating config from environment variables."""
        from sagaz.outbox.brokers.redis import RedisBrokerConfig

        with patch.dict(
            os.environ,
            {
                "REDIS_URL": "redis://env-host:6379/2",
                "REDIS_STREAM_NAME": "env-stream",
                "REDIS_MAX_STREAM_LENGTH": "20000",
            },
        ):
            config = RedisBrokerConfig.from_env()

            assert config.url == "redis://env-host:6379/2"
            assert config.stream_name == "env-stream"
            assert config.max_stream_length == 20000


class TestRedisBrokerConnection:
    """Tests for Redis broker connection handling."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection to Redis."""
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.ping = AsyncMock(return_value=True)

            config = RedisBrokerConfig()
            broker = RedisBroker(config)

            await broker.connect()

            assert broker.is_connected
            mock_redis.from_url.assert_called_once()
            mock_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure handling."""
        from sagaz.outbox.brokers.base import BrokerConnectionError
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            mock_redis.from_url.side_effect = Exception("Connection refused")

            config = RedisBrokerConfig()
            broker = RedisBroker(config)

            with pytest.raises(BrokerConnectionError):
                await broker.connect()

            assert not broker.is_connected

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing Redis connection."""
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client

            config = RedisBrokerConfig()
            broker = RedisBroker(config)

            await broker.connect()
            await broker.close()

            assert not broker.is_connected
            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """Test health check when Redis is healthy."""
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.ping = AsyncMock(return_value=True)

            config = RedisBrokerConfig()
            broker = RedisBroker(config)
            await broker.connect()

            is_healthy = await broker.health_check()

            assert is_healthy is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        """Test health check when Redis is unhealthy."""
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            # First ping succeeds (for connect), subsequent pings fail
            mock_client.ping = AsyncMock(side_effect=[True, Exception("Connection lost")])

            config = RedisBrokerConfig()
            broker = RedisBroker(config)
            await broker.connect()  # Uses first ping (succeeds)

            is_healthy = await broker.health_check()  # Uses second ping (fails)

            assert is_healthy is False


class TestRedisBrokerPublish:
    """Tests for Redis broker publish operations."""

    @pytest.mark.asyncio
    async def test_publish_to_stream(self):
        """Test publishing message to Redis stream."""
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.xadd = AsyncMock(return_value=b"1234567890-0")

            config = RedisBrokerConfig()
            broker = RedisBroker(config)
            await broker.connect()

            await broker.publish(
                topic="test-topic",
                message=b'{"event": "test"}',
                headers={"event_id": "123"},
                key="aggregate-1",
            )

            mock_client.xadd.assert_called_once()
            call_args = mock_client.xadd.call_args
            assert call_args[0][0] == "sage.outbox"  # stream name
            # Check payload is in the fields dict
            fields = call_args[0][1]
            assert fields[b"payload"] == b'{"event": "test"}'

    @pytest.mark.asyncio
    async def test_publish_with_max_length(self):
        """Test that XADD respects maxlen for stream trimming."""
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.xadd = AsyncMock(return_value=b"1234567890-0")

            config = RedisBrokerConfig(max_stream_length=5000)
            broker = RedisBroker(config)
            await broker.connect()

            await broker.publish("topic", b"message")

            call_kwargs = mock_client.xadd.call_args[1]
            assert call_kwargs.get("maxlen") == 5000

    @pytest.mark.asyncio
    async def test_publish_not_connected_raises(self):
        """Test that publish raises when not connected."""
        from sagaz.outbox.brokers.base import BrokerError
        from sagaz.outbox.brokers.redis import REDIS_AVAILABLE, RedisBroker, RedisBrokerConfig

        if not REDIS_AVAILABLE:
            pytest.skip("redis not installed")

        config = RedisBrokerConfig()
        broker = RedisBroker(config)

        with pytest.raises(BrokerError, match="Not connected"):
            await broker.publish("topic", b"message")

    @pytest.mark.asyncio
    async def test_publish_failure_raises(self):
        """Test that publish failures are properly raised."""
        from sagaz.outbox.brokers.base import BrokerPublishError
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.xadd = AsyncMock(side_effect=Exception("Stream error"))

            config = RedisBrokerConfig()
            broker = RedisBroker(config)
            await broker.connect()

            with pytest.raises(BrokerPublishError):
                await broker.publish("topic", b"message")


class TestRedisBrokerEvent:
    """Tests for publishing OutboxEvent objects."""

    @pytest.mark.asyncio
    async def test_publish_outbox_event(self):
        """Test publishing an OutboxEvent."""
        from datetime import datetime

        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig
        from sagaz.outbox.types import OutboxEvent

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis") as mock_redis,
        ):
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.xadd = AsyncMock(return_value=b"1234567890-0")

            config = RedisBrokerConfig()
            broker = RedisBroker(config)
            await broker.connect()

            event = OutboxEvent(
                event_id="evt-123",
                saga_id="saga-456",
                aggregate_type="Order",
                aggregate_id="order-789",
                event_type="OrderCreated",
                payload={"amount": 100},
                headers={"correlation_id": "corr-1"},
                created_at=datetime.now(UTC),
            )

            await broker.publish_event(event)

            mock_client.xadd.assert_called_once()


class TestRedisBrokerFactory:
    """Tests for broker factory integration."""

    def test_create_redis_broker(self):
        """Test creating Redis broker via factory."""
        from sagaz.outbox import create_broker

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis"),
        ):
            broker = create_broker("redis")

            from sagaz.outbox.brokers.redis import RedisBroker

            assert isinstance(broker, RedisBroker)

    def test_redis_in_available_brokers(self):
        """Test that Redis appears in available brokers when installed."""
        from sagaz.outbox import get_available_brokers

        with (
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis"),
        ):
            available = get_available_brokers()
            assert "redis" in available

    def test_create_redis_raises_when_unavailable(self):
        """Test that Redis broker raises when redis-py not installed."""
        from sagaz.exceptions import MissingDependencyError
        from sagaz.outbox import create_broker

        with patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", False):
            with pytest.raises(MissingDependencyError) as exc_info:
                create_broker("redis")

            assert "redis" in str(exc_info.value).lower()


class TestRedisBrokerFromEnv:
    """Tests for creating Redis broker from environment."""

    def test_from_env(self):
        """Test creating broker from environment variables."""
        from sagaz.outbox.brokers.redis import RedisBroker

        with (
            patch.dict(
                os.environ,
                {
                    "REDIS_URL": "redis://test:6379/0",
                    "REDIS_STREAM_NAME": "test-stream",
                },
            ),
            patch("sagaz.outbox.brokers.redis.REDIS_AVAILABLE", True),
            patch("sagaz.outbox.brokers.redis.redis"),
        ):
            broker = RedisBroker.from_env()

            assert broker.config.url == "redis://test:6379/0"
            assert broker.config.stream_name == "test-stream"
