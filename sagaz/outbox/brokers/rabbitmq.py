"""
RabbitMQ Message Broker - Production-ready RabbitMQ integration.

Uses aio-pika for async RabbitMQ access with publisher confirms.

Usage:
    >>> from sagaz.outbox.brokers import RabbitMQBroker
    >>>
    >>> broker = RabbitMQBroker(url="amqp://guest:guest@localhost/")
    >>> await broker.connect()
    >>> await broker.publish("orders", b'{"order_id": 1}')
"""

import logging
from dataclasses import dataclass
from typing import Any

from sagaz.core.exceptions import MissingDependencyError
from sagaz.outbox.brokers.base import (
    BaseBroker,
    BrokerConfig,
    BrokerConnectionError,
    BrokerPublishError,
)

# Check for aio-pika availability
try:
    import aio_pika
    from aio_pika import DeliveryMode, ExchangeType, Message
    from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractExchange

    RABBITMQ_AVAILABLE = True
except ImportError:  # pragma: no cover
    RABBITMQ_AVAILABLE = False
    aio_pika: Any = None  # type: ignore[no-redef]
    Message: Any = None  # type: ignore[no-redef]
    DeliveryMode: Any = None  # type: ignore[no-redef]
    ExchangeType: Any = None  # type: ignore[no-redef]


logger = logging.getLogger(__name__)


@dataclass
class RabbitMQBrokerConfig(BrokerConfig):
    """
    RabbitMQ-specific broker configuration.

    Attributes:
        url: AMQP URL (amqp://user:pass@host:port/vhost)
        exchange_name: Default exchange name
        exchange_type: Exchange type (direct, fanout, topic, headers)
        exchange_durable: Whether exchange survives broker restart
        confirm_delivery: Enable publisher confirms
        prefetch_count: Consumer prefetch count
        heartbeat: Heartbeat interval in seconds
        connection_timeout: Connection timeout in seconds
    """

    url: str = "amqp://guest:guest@localhost/"
    exchange_name: str = "sage.outbox"
    exchange_type: str = "topic"
    exchange_durable: bool = True
    confirm_delivery: bool = True
    prefetch_count: int = 100
    heartbeat: int = 60
    connection_timeout: float = 30.0


class RabbitMQBroker(BaseBroker):
    """
    RabbitMQ message broker using aio-pika.

    Features:
        - Publisher confirms for reliable delivery
        - Persistent messages (survive broker restart)
        - Automatic exchange declaration
        - Dead letter exchange support
        - Graceful connection recovery

    Usage:
        >>> config = RabbitMQBrokerConfig(
        ...     url="amqp://guest:guest@localhost/",
        ...     exchange_name="sage.outbox",
        ... )
        >>> broker = RabbitMQBroker(config)
        >>> await broker.connect()
        >>>
        >>> # Publish to a routing key (topic)
        >>> await broker.publish(
        ...     topic="orders.created",
        ...     message=b'{"order_id": "123"}',
        ...     headers={"trace_id": "abc"},
        ... )
        >>>
        >>> await broker.close()
    """

    def __init__(self, config: RabbitMQBrokerConfig | None = None):
        """
        Initialize RabbitMQ broker.

        Args:
            config: RabbitMQ configuration

        Raises:
            MissingDependencyError: If aio-pika is not installed
        """
        if not RABBITMQ_AVAILABLE:
            msg = "aio-pika"
            raise MissingDependencyError(msg, "RabbitMQ message broker")  # pragma: no cover

        super().__init__(config)
        self.config: RabbitMQBrokerConfig = config or RabbitMQBrokerConfig()
        self._connection: AbstractConnection | None = None
        self._channel: AbstractChannel | None = None
        self._exchange: AbstractExchange | None = None
        self._connected = False

    @classmethod
    def from_env(cls) -> "RabbitMQBroker":
        """Create RabbitMQ broker from environment variables."""
        import os

        config = RabbitMQBrokerConfig(
            url=os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/"),
            exchange_name=os.getenv("RABBITMQ_EXCHANGE", "sage.outbox"),
            exchange_type=os.getenv("RABBITMQ_EXCHANGE_TYPE", "topic"),
        )
        return cls(config)

    async def connect(self) -> None:
        """Establish connection to RabbitMQ."""
        if self._connected:
            return

        try:  # pragma: no cover (RUN_INTEGRATION=1 with Docker)
            # Connect to RabbitMQ
            self._connection = await aio_pika.connect_robust(
                self.config.url,
                timeout=self.config.connection_timeout,
            )

            # Create channel with publisher confirms
            self._channel = await self._connection.channel()

            if self.config.confirm_delivery:
                await self._channel.set_qos(prefetch_count=self.config.prefetch_count)

            # Declare exchange
            exchange_type = getattr(ExchangeType, self.config.exchange_type.upper())
            self._exchange = await self._channel.declare_exchange(
                self.config.exchange_name,
                exchange_type,
                durable=self.config.exchange_durable,
            )

            self._connected = True
            logger.info(f"Connected to RabbitMQ at {self.config.url}")

        except Exception as e:  # pragma: no cover
            msg = f"Failed to connect to RabbitMQ: {e}"
            raise BrokerConnectionError(msg) from e

    async def publish(
        self,
        topic: str,
        message: bytes,
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        """
        Publish a message to RabbitMQ.

        Args:
            topic: Routing key for the message
            message: Message body as bytes
            headers: Optional message headers
            key: Optional message key (ignored for RabbitMQ, use topic as routing key)
        """
        if not self._connected or not self._exchange:
            msg = "RabbitMQ broker not connected"
            raise BrokerConnectionError(msg)

        try:  # pragma: no cover (RUN_INTEGRATION=1 with Docker)
            # Create message with persistent delivery mode
            rmq_message = Message(
                body=message,
                delivery_mode=DeliveryMode.PERSISTENT,
                headers=headers or {},  # type: ignore[arg-type]
                content_type="application/json",
            )

            # Publish to exchange with routing key
            await self._exchange.publish(
                rmq_message,
                routing_key=topic,
            )

            logger.debug(f"Published message to RabbitMQ routing key {topic}")

        except Exception as e:  # pragma: no cover
            msg = f"Failed to publish to RabbitMQ: {e}"
            raise BrokerPublishError(msg) from e

    async def close(self) -> None:  # pragma: no cover (RUN_INTEGRATION=1)
        """Close the RabbitMQ connection."""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._exchange = None

        if self._connection:
            await self._connection.close()
            self._connection = None

        self._connected = False
        logger.info("RabbitMQ connection closed")

    async def health_check(self) -> bool:
        """Check RabbitMQ connection health."""
        if not self._connected or not self._connection:  # pragma: no cover
            return False

        try:  # pragma: no cover (RUN_INTEGRATION=1 with Docker)
            return not self._connection.is_closed
        except Exception:  # pragma: no cover
            return False

    async def declare_queue(
        self,
        queue_name: str,
        routing_key: str,
        durable: bool = True,
        dead_letter_exchange: str | None = None,
    ) -> None:
        """
        Declare a queue and bind it to the exchange.

        Args:
            queue_name: Name of the queue
            routing_key: Routing key pattern to bind
            durable: Whether queue survives broker restart
            dead_letter_exchange: Optional DLX for rejected messages
        """
        if not self._channel or not self._exchange:  # pragma: no cover
            msg = "RabbitMQ broker not connected"
            raise BrokerConnectionError(msg)

        arguments = {}  # pragma: no cover
        if dead_letter_exchange:  # pragma: no cover
            arguments["x-dead-letter-exchange"] = dead_letter_exchange

        queue = await self._channel.declare_queue(  # pragma: no cover
            queue_name,
            durable=durable,
            arguments=arguments or None,  # type: ignore[arg-type]
        )

        await queue.bind(self._exchange, routing_key)  # pragma: no cover
        logger.info(f"Declared queue {queue_name} bound to {routing_key}")  # pragma: no cover


def is_rabbitmq_available() -> bool:
    """Check if RabbitMQ support is available."""
    return RABBITMQ_AVAILABLE
