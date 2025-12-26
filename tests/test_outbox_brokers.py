"""
Tests for Outbox brokers and factory.
"""

import os
from unittest.mock import patch

import pytest

from sagaz.exceptions import MissingDependencyError
from sagaz.outbox import (
    InMemoryBroker,
    create_broker,
    get_available_brokers,
    print_available_brokers,
)


class TestBrokerFactory:
    """Tests for the broker factory."""

    def test_get_available_brokers_includes_memory(self):
        """Test that memory broker is always available."""
        available = get_available_brokers()
        assert "memory" in available

    def test_create_memory_broker(self):
        """Test creating in-memory broker."""
        broker = create_broker("memory")

        assert isinstance(broker, InMemoryBroker)

    def test_create_broker_unknown_type(self):
        """Test that unknown broker type raises error."""
        with pytest.raises(ValueError, match="Unknown broker type"):
            create_broker("unknown_broker")

    def test_create_broker_case_insensitive(self):
        """Test broker type is case insensitive."""
        broker = create_broker("MEMORY")
        assert isinstance(broker, InMemoryBroker)

        broker = create_broker("Memory")
        assert isinstance(broker, InMemoryBroker)

    def test_print_available_brokers(self, capsys):
        """Test printing available brokers."""
        print_available_brokers()

        captured = capsys.readouterr()
        assert "memory" in captured.out.lower()
        assert "Available Message Brokers" in captured.out

    def test_create_kafka_raises_when_unavailable(self):
        """Test that kafka broker raises when aiokafka not installed."""
        with patch.dict("sys.modules", {"aiokafka": None}):
            with patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", False):
                with pytest.raises(MissingDependencyError) as exc_info:
                    create_broker("kafka")

                assert "aiokafka" in str(exc_info.value)

    def test_create_rabbitmq_raises_when_unavailable(self):
        """Test that rabbitmq broker raises when aio-pika not installed."""
        with patch.dict("sys.modules", {"aio_pika": None}):
            with patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", False):
                with pytest.raises(MissingDependencyError) as exc_info:
                    create_broker("rabbitmq")

                assert "aio-pika" in str(exc_info.value)

    def test_create_broker_from_env_memory(self):
        """Test creating broker from environment variables."""
        from sagaz.outbox.brokers.factory import create_broker_from_env

        with patch.dict(os.environ, {"BROKER_TYPE": "memory"}):
            broker = create_broker_from_env()
            assert isinstance(broker, InMemoryBroker)

    def test_create_broker_from_env_default(self):
        """Test default broker type when not set."""
        from sagaz.outbox.brokers.factory import create_broker_from_env

        # Remove BROKER_TYPE if set
        env = os.environ.copy()
        env.pop("BROKER_TYPE", None)

        with patch.dict(os.environ, env, clear=True):
            broker = create_broker_from_env()
            assert isinstance(broker, InMemoryBroker)


class TestInMemoryBrokerAdvanced:
    """Additional tests for InMemoryBroker."""

    @pytest.mark.asyncio
    async def test_clear_messages(self):
        """Test clearing all messages."""
        broker = InMemoryBroker()
        await broker.connect()

        await broker.publish("topic1", b"msg1")
        await broker.publish("topic2", b"msg2")

        broker.clear()

        assert broker.get_messages("topic1") == []
        assert broker.get_messages("topic2") == []

    @pytest.mark.asyncio
    async def test_multiple_messages_same_topic(self):
        """Test multiple messages on same topic."""
        broker = InMemoryBroker()
        await broker.connect()

        for i in range(5):
            await broker.publish("topic", f"msg{i}".encode())

        messages = broker.get_messages("topic")
        assert len(messages) == 5

    @pytest.mark.asyncio
    async def test_close_resets_connected(self):
        """Test that close resets connected state."""
        broker = InMemoryBroker()
        await broker.connect()
        assert broker.is_connected is True

        await broker.close()
        assert broker.is_connected is False


class TestKafkaBrokerConfig:
    """Tests for KafkaBrokerConfig."""

    def test_default_values(self):
        """Test default configuration."""
        # Note: Only test if available to prevent import errors
        try:
            from sagaz.outbox.brokers.kafka import KafkaBrokerConfig

            config = KafkaBrokerConfig()

            assert config.bootstrap_servers == "localhost:9092"
            assert config.client_id == "sage-outbox"
            assert config.acks == "all"
            assert config.enable_idempotence is True
        except MissingDependencyError:
            pytest.skip("aiokafka not available")


class TestRabbitMQBrokerConfig:
    """Tests for RabbitMQBrokerConfig."""

    def test_default_values(self):
        """Test default configuration."""
        try:
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBrokerConfig

            config = RabbitMQBrokerConfig()

            assert config.url == "amqp://guest:guest@localhost/"
            assert config.exchange_name == "sage.outbox"
            assert config.exchange_type == "topic"
            assert config.exchange_durable is True
        except MissingDependencyError:
            pytest.skip("aio-pika not available")
