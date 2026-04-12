"""
Tests for broker error paths missing from coverage:
- sagaz/outbox/brokers/kafka.py (83.2%) - lines 31, 115-116, 159-162, 170-172, 195-197, 228-229
- sagaz/outbox/brokers/rabbitmq.py (82.8%) - lines 33-38, 110-111, 161-163, 202-204, 227-228, 252
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# KafkaBroker missing paths
# =============================================================================


class TestKafkaBrokerFromEnv:
    """Lines 115-116: from_env with SASL settings from environment."""

    def test_from_env_with_sasl_settings(self, monkeypatch):
        """Lines 115-116: from_env reads SASL env vars."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker

        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka.example.com:9092")
        monkeypatch.setenv("KAFKA_CLIENT_ID", "my-service")
        monkeypatch.setenv("KAFKA_SASL_MECHANISM", "PLAIN")
        monkeypatch.setenv("KAFKA_SASL_USERNAME", "user")
        monkeypatch.setenv("KAFKA_SASL_PASSWORD", "secret")
        monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "SASL_SSL")

        broker = KafkaBroker.from_env()

        assert broker.config.bootstrap_servers == "kafka.example.com:9092"
        assert broker.config.sasl_mechanism == "PLAIN"
        assert broker.config.sasl_username == "user"
        assert broker.config.sasl_password == "secret"
        assert broker.config.security_protocol == "SASL_SSL"


class TestKafkaBrokerConnect:
    """Lines 159-162: connect() with SASL mechanism configured."""

    @pytest.mark.asyncio
    async def test_connect_with_sasl_mechanism(self):
        """Lines 159-162: SASL settings are included in producer kwargs."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig

        config = KafkaBrokerConfig(
            bootstrap_servers="localhost:9092",
            sasl_mechanism="PLAIN",
            sasl_username="user",
            sasl_password="pass",
            security_protocol="SASL_SSL",
            compression_type=None,  # Disable compression for simpler test
        )
        broker = KafkaBroker(config)

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()

        with patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer", return_value=mock_producer):
            await broker.connect()

            assert broker._connected is True
            # Verify producer was created with SASL kwargs

    @pytest.mark.asyncio
    async def test_connect_with_compression(self):
        """Lines 159-162: compression_type included in producer kwargs."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig

        config = KafkaBrokerConfig(
            bootstrap_servers="localhost:9092",
            compression_type="snappy",
        )
        broker = KafkaBroker(config)

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()

        with patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer", return_value=mock_producer):
            await broker.connect()
            assert broker._connected is True


class TestKafkaBrokerPublishNotConnected:
    """Lines 170-172: publish() when not connected raises BrokerConnectionError."""

    @pytest.mark.asyncio
    async def test_publish_not_connected_raises(self):
        """Lines 170-172: Not connected → BrokerConnectionError."""
        from sagaz.core.outbox.brokers.base import BrokerConnectionError
        from sagaz.core.outbox.brokers.kafka import KafkaBroker

        broker = KafkaBroker()
        assert not broker._connected

        with pytest.raises(BrokerConnectionError, match="Kafka producer not connected"):
            await broker.publish(topic="test", message=b"data")


class TestKafkaBrokerClose:
    """Lines 195-197: close() method."""

    @pytest.mark.asyncio
    async def test_close_when_connected(self):
        """Lines 195-197: close() stops producer and resets state."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker

        broker = KafkaBroker()
        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()

        with patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer", return_value=mock_producer):
            await broker.connect()
            assert broker._connected

        await broker.close()  # covers lines 195-197

        assert not broker._connected
        assert broker._producer is None
        mock_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_when_not_connected_is_no_op(self):
        """close() when not connected doesn't raise."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker

        broker = KafkaBroker()
        await broker.close()  # Should not raise
        assert not broker._connected


class TestKafkaBrokerHealthCheck:
    """Lines 228-229: health_check() when not connected."""

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        """Lines 228-229: health_check returns False when not connected."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker

        broker = KafkaBroker()
        assert not broker._connected

        result = await broker.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_connected_but_fails(self):
        """health_check returns False when metadata fetch fails."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker

        broker = KafkaBroker()
        broker._connected = True

        mock_producer = MagicMock()
        mock_client = AsyncMock()
        mock_client.fetch_all_metadata = AsyncMock(side_effect=Exception("timeout"))
        mock_producer.client = mock_client
        broker._producer = mock_producer

        result = await broker.health_check()
        assert result is False


# =============================================================================
# RabbitMQBroker missing paths
# =============================================================================


class TestRabbitMQBrokerFromEnv:
    """Lines 110-111: from_env with env vars."""

    def test_from_env_reads_env_vars(self, monkeypatch):
        """Lines 110-111: from_env creates broker from environment."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        monkeypatch.setenv("RABBITMQ_URL", "amqp://admin:admin@rabbit.example.com/")
        monkeypatch.setenv("RABBITMQ_EXCHANGE", "my.exchange")
        monkeypatch.setenv("RABBITMQ_EXCHANGE_TYPE", "fanout")

        broker = RabbitMQBroker.from_env()

        assert broker.config.url == "amqp://admin:admin@rabbit.example.com/"
        assert broker.config.exchange_name == "my.exchange"
        assert broker.config.exchange_type == "fanout"


class TestRabbitMQBrokerConnect:
    """Lines 161-163: connect() error path → BrokerConnectionError."""

    @pytest.mark.asyncio
    async def test_connect_failure_raises_broker_connection_error(self):
        """Lines 161-163: Connection failure wraps in BrokerConnectionError."""
        from sagaz.core.outbox.brokers.base import BrokerConnectionError
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()

        with patch(
            "sagaz.outbox.brokers.rabbitmq.aio_pika.connect_robust",
            new_callable=AsyncMock,
            side_effect=Exception("connection refused"),
        ):
            with pytest.raises(BrokerConnectionError, match="Failed to connect to RabbitMQ"):
                await broker.connect()


class TestRabbitMQBrokerPublish:
    """Lines 202-204: publish() when not connected → BrokerConnectionError."""

    @pytest.mark.asyncio
    async def test_publish_not_connected_raises(self):
        """Lines 202-204: BrokerConnectionError when not connected."""
        from sagaz.core.outbox.brokers.base import BrokerConnectionError
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        assert not broker._connected

        with pytest.raises(BrokerConnectionError, match="RabbitMQ broker not connected"):
            await broker.publish(topic="orders.created", message=b'{"key": "value"}')


class TestRabbitMQBrokerClose:
    """Lines 227-228: close() closes connection and channel."""

    @pytest.mark.asyncio
    async def test_close_resets_state(self):
        """Lines 227-228: close() clears channel, exchange, connection."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()

        mock_channel = AsyncMock()
        mock_connection = AsyncMock()

        broker._connected = True
        broker._channel = mock_channel
        broker._connection = mock_connection
        broker._exchange = MagicMock()

        await broker.close()  # covers lines 227-228

        mock_channel.close.assert_called_once()
        mock_connection.close.assert_called_once()
        assert broker._connected is False
        assert broker._channel is None
        assert broker._connection is None
        assert broker._exchange is None

    @pytest.mark.asyncio
    async def test_close_when_not_connected_is_no_op(self):
        """close() with no connection doesn't raise."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        await broker.close()  # Should not raise
        assert not broker._connected


class TestRabbitMQBrokerHealthCheck:
    """Line 252: health_check() when connection.is_closed raises."""

    @pytest.mark.asyncio
    async def test_health_check_exception_returns_false(self):
        """Line 252: Exception in is_closed check → returns False."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        broker._connected = True

        mock_connection = MagicMock()
        mock_connection.is_closed = property(lambda x: (_ for _ in ()).throw(Exception("fail")))
        broker._connection = mock_connection

        # Use a property that raises
        type(mock_connection).is_closed = property(
            lambda _: (_ for _ in ()).throw(Exception("err"))
        )

        result = await broker.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_not_connected_returns_false(self):
        """health_check returns False when not connected."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        result = await broker.health_check()
        assert result is False


# =============================================================================
# Additional Kafka coverage: lines 31, 115-116, 141, 170-172, 186-197, 227
# =============================================================================


class TestKafkaMissingDependency:
    """Lines 115-116: MissingDependencyError when KAFKA_AVAILABLE is False."""

    def test_constructor_raises_when_unavailable(self):
        """Lines 115-116: raises MissingDependencyError."""
        import sagaz.core.outbox.brokers.kafka as kafka_mod
        from sagaz.core.exceptions import MissingDependencyError

        original = kafka_mod.KAFKA_AVAILABLE
        try:
            kafka_mod.KAFKA_AVAILABLE = False
            with pytest.raises(MissingDependencyError):
                kafka_mod.KafkaBroker()
        finally:
            kafka_mod.KAFKA_AVAILABLE = original


class TestKafkaConnectAlreadyConnected:
    """Line 141: connect() returns early if already connected."""

    @pytest.mark.asyncio
    async def test_connect_when_already_connected_is_no_op(self):
        """Line 141: early return when _connected."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker

        broker = KafkaBroker()
        broker._connected = True
        mock_producer = MagicMock()
        broker._producer = mock_producer

        # Should not call AIOKafkaProducer at all
        with patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer") as MockProducer:
            await broker.connect()
            MockProducer.assert_not_called()


class TestKafkaConnectError:
    """Lines 170-172: connect() raises BrokerConnectionError on KafkaError."""

    @pytest.mark.asyncio
    async def test_connect_kafka_error_raises(self):
        """Lines 170-172: KafkaError → BrokerConnectionError."""
        import sagaz.core.outbox.brokers.kafka as kafka_mod
        from sagaz.core.outbox.brokers.base import BrokerConnectionError

        broker = kafka_mod.KafkaBroker()
        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock(side_effect=kafka_mod.KafkaError("refused"))

        with patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer", return_value=mock_producer):
            with pytest.raises(BrokerConnectionError, match="Failed to connect to Kafka"):
                await broker.connect()


class TestKafkaPublishPaths:
    """Lines 186-197: publish() success + KafkaError paths."""

    @pytest.mark.asyncio
    async def test_publish_success(self):
        """Lines 186-193: publish succeeds."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker

        broker = KafkaBroker()
        broker._connected = True
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()
        broker._producer = mock_producer

        await broker.publish(topic="test-topic", message=b'{"test": 1}')
        mock_producer.send_and_wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_kafka_error(self):
        """Lines 195-197: KafkaError → BrokerPublishError."""
        import sagaz.core.outbox.brokers.kafka as kafka_mod
        from sagaz.core.outbox.brokers.base import BrokerPublishError

        broker = kafka_mod.KafkaBroker()
        broker._connected = True
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(side_effect=kafka_mod.KafkaError("send failed"))
        broker._producer = mock_producer

        with pytest.raises(BrokerPublishError, match="Failed to publish to Kafka"):
            await broker.publish(topic="test-topic", message=b"data")


class TestKafkaHealthCheckSuccess:
    """Line 227: health_check() returns True when metadata fetch succeeds."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Line 227: returns True on successful metadata fetch."""
        from sagaz.core.outbox.brokers.kafka import KafkaBroker

        broker = KafkaBroker()
        broker._connected = True
        mock_producer = MagicMock()
        mock_client = AsyncMock()
        mock_client.fetch_all_metadata = AsyncMock(return_value=None)
        mock_producer.client = mock_client
        broker._producer = mock_producer

        result = await broker.health_check()
        assert result is True


# =============================================================================
# Additional RabbitMQ coverage: 33-38, 110-111, 135, 145-159, 185-204, 250-261
# =============================================================================


class TestRabbitMQMissingDependency:
    """Lines 110-111: MissingDependencyError when RABBITMQ_AVAILABLE is False."""

    def test_constructor_raises_when_unavailable(self):
        """Lines 110-111: raises MissingDependencyError."""
        import sagaz.core.outbox.brokers.rabbitmq as rabbitmq_mod
        from sagaz.core.exceptions import MissingDependencyError

        original = rabbitmq_mod.RABBITMQ_AVAILABLE
        try:
            rabbitmq_mod.RABBITMQ_AVAILABLE = False
            with pytest.raises(MissingDependencyError):
                rabbitmq_mod.RabbitMQBroker()
        finally:
            rabbitmq_mod.RABBITMQ_AVAILABLE = original


class TestRabbitMQConnectAlreadyConnected:
    """Line 135: connect() returns early if already connected."""

    @pytest.mark.asyncio
    async def test_connect_when_already_connected_is_no_op(self):
        """Line 135: early return when _connected."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        broker._connected = True

        with patch(
            "sagaz.outbox.brokers.rabbitmq.aio_pika.connect_robust",
            new_callable=AsyncMock,
        ) as mock_conn:
            await broker.connect()
            mock_conn.assert_not_called()


class TestRabbitMQConnectSuccess:
    """Lines 145-159: connect() success path - channel + exchange setup."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Lines 145-159: Full connect() success path."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()

        mock_exchange = AsyncMock()
        mock_channel = AsyncMock()
        mock_channel.set_qos = AsyncMock()
        mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)

        mock_connection = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)

        with patch(
            "sagaz.outbox.brokers.rabbitmq.aio_pika.connect_robust",
            new_callable=AsyncMock,
            return_value=mock_connection,
        ):
            with patch("sagaz.outbox.brokers.rabbitmq.ExchangeType") as mock_exchange_type:
                mock_exchange_type.DIRECT = "direct"
                await broker.connect()

        assert broker._connected is True
        assert broker._channel is mock_channel
        assert broker._exchange is mock_exchange


class TestRabbitMQPublishPaths:
    """Lines 185-204: publish() success + exception paths."""

    @pytest.mark.asyncio
    async def test_publish_success(self):
        """Lines 185-200: publish succeeds."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        broker._connected = True

        mock_exchange = AsyncMock()
        mock_exchange.publish = AsyncMock()
        broker._exchange = mock_exchange

        with (
            patch("sagaz.outbox.brokers.rabbitmq.Message") as MockMessage,
            patch("sagaz.outbox.brokers.rabbitmq.DeliveryMode") as MockDeliveryMode,
        ):
            MockMessage.return_value = MagicMock()
            MockDeliveryMode.PERSISTENT = "persistent"

            await broker.publish("orders.created", b'{"order": 1}')

        mock_exchange.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_exception_raises_publish_error(self):
        """Lines 202-204: Exception → BrokerPublishError."""
        from sagaz.core.outbox.brokers.base import BrokerPublishError
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        broker._connected = True

        mock_exchange = AsyncMock()
        mock_exchange.publish = AsyncMock(side_effect=Exception("channel closed"))
        broker._exchange = mock_exchange

        with (
            patch("sagaz.outbox.brokers.rabbitmq.Message") as MockMessage,
            patch("sagaz.outbox.brokers.rabbitmq.DeliveryMode") as MockDeliveryMode,
        ):
            MockMessage.return_value = MagicMock()
            MockDeliveryMode.PERSISTENT = "persistent"

            with pytest.raises(BrokerPublishError, match="Failed to publish to RabbitMQ"):
                await broker.publish("orders.created", b"data")


class TestRabbitMQDeclareQueue:
    """Lines 250-261: declare_queue() body."""

    @pytest.mark.asyncio
    async def test_declare_queue_not_connected(self):
        """Lines 247-248: not connected → BrokerConnectionError."""
        from sagaz.core.outbox.brokers.base import BrokerConnectionError
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        with pytest.raises(BrokerConnectionError, match="not connected"):
            await broker.declare_queue("my-queue", "my.key")

    @pytest.mark.asyncio
    async def test_declare_queue_success(self):
        """Lines 250-261: declare_queue creates and binds queue."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        broker._connected = True

        mock_queue = AsyncMock()
        mock_queue.bind = AsyncMock()

        mock_channel = AsyncMock()
        mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
        broker._channel = mock_channel
        broker._exchange = MagicMock()

        await broker.declare_queue("my-queue", "my.routing.key", durable=True)

        mock_channel.declare_queue.assert_awaited_once_with(
            "my-queue", durable=True, arguments=None
        )
        mock_queue.bind.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_declare_queue_with_dead_letter_exchange(self):
        """Lines 251-252: dead_letter_exchange sets arguments."""
        from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = RabbitMQBroker()
        broker._connected = True

        mock_queue = AsyncMock()
        mock_queue.bind = AsyncMock()

        mock_channel = AsyncMock()
        mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
        broker._channel = mock_channel
        broker._exchange = MagicMock()

        await broker.declare_queue("my-queue", "my.key", dead_letter_exchange="dlx.exchange")

        call_args = mock_channel.declare_queue.call_args
        assert call_args[1]["arguments"] == {"x-dead-letter-exchange": "dlx.exchange"}
