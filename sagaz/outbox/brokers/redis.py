"""
Redis Message Broker - Production-ready Redis Streams integration.

Uses redis-py for async Redis access with Streams support.

Usage:
    >>> from sagaz.outbox.brokers import RedisBroker, RedisBrokerConfig
    >>>
    >>> config = RedisBrokerConfig(
    ...     url="redis://localhost:6379/0",
    ...     stream_name="saga-events",
    ... )
    >>> broker = RedisBroker(config)
    >>> await broker.connect()
    >>> await broker.publish("order.created", b'{"order_id": "123"}')
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

from sagaz.exceptions import MissingDependencyError
from sagaz.outbox.brokers.base import (
    BaseBroker,
    BrokerConfig,
    BrokerConnectionError,
    BrokerError,
    BrokerPublishError,
)

# Try to import redis
try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None


logger = logging.getLogger(__name__)


@dataclass
class RedisBrokerConfig(BrokerConfig):
    """
    Redis-specific broker configuration.

    Attributes:
        url: Redis URL (redis://[user:pass@]host:port/db)
        stream_name: Default stream name for publishing
        max_stream_length: Maximum stream length (MAXLEN for XADD)
        consumer_group: Consumer group name for reading
        consumer_name: Consumer name within the group
        block_timeout_ms: Blocking timeout for XREAD
        connection_timeout_seconds: Connection timeout
    """

    url: str = "redis://localhost:6379/0"
    stream_name: str = "sage.outbox"
    max_stream_length: int = 10000
    consumer_group: str = "sage-workers"
    consumer_name: str = "worker-1"
    block_timeout_ms: int = 5000
    connection_timeout_seconds: float = 30.0
    # SSL/TLS options
    ssl: bool = False
    ssl_cert_reqs: str = "required"  # "required", "optional", "none"

    @classmethod
    def from_env(cls) -> "RedisBrokerConfig":
        """
        Create configuration from environment variables.

        Environment variables:
            REDIS_URL: Redis connection URL
            REDIS_STREAM_NAME: Stream name
            REDIS_MAX_STREAM_LENGTH: Maximum stream length
            REDIS_CONSUMER_GROUP: Consumer group name
            REDIS_SSL: Enable SSL (true/false)
        """
        return cls(
            url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            stream_name=os.environ.get("REDIS_STREAM_NAME", "sage.outbox"),
            max_stream_length=int(os.environ.get("REDIS_MAX_STREAM_LENGTH", "10000")),
            consumer_group=os.environ.get("REDIS_CONSUMER_GROUP", "sage-workers"),
            consumer_name=os.environ.get("REDIS_CONSUMER_NAME", "worker-1"),
            ssl=os.environ.get("REDIS_SSL", "false").lower() == "true",
        )


class RedisBroker(BaseBroker):
    """
    Redis Streams message broker.

    Features:
        - Uses Redis Streams for ordered, persistent messaging
        - Supports consumer groups for distributed processing
        - Auto-trimming with MAXLEN for memory management
        - Low latency (~1ms publish)
        - Built-in persistence (RDB/AOF)

    Example:
        >>> config = RedisBrokerConfig(url="redis://localhost:6379/0")
        >>> broker = RedisBroker(config)
        >>> await broker.connect()
        >>>
        >>> await broker.publish("events", b'{"type": "order.created"}')
        >>>
        >>> await broker.close()
    """

    def __init__(self, config: RedisBrokerConfig | None = None):
        """
        Initialize Redis broker.

        Args:
            config: Redis configuration

        Raises:
            MissingDependencyError: If redis-py is not installed
        """
        if not REDIS_AVAILABLE:
            msg = "redis"
            raise MissingDependencyError(
                msg,
                "Redis broker requires redis-py. Install with: pip install redis",
            )

        super().__init__(config)
        self.config: RedisBrokerConfig = config or RedisBrokerConfig()
        self._client = None

    @classmethod
    def from_env(cls) -> "RedisBroker":
        """Create Redis broker from environment variables."""
        return cls(RedisBrokerConfig.from_env())

    async def connect(self) -> None:
        """
        Establish connection to Redis.

        Raises:
            BrokerConnectionError: If connection fails
        """
        try:
            logger.info(f"Connecting to Redis: {self._safe_url()}")

            self._client = redis.from_url(
                self.config.url,
                socket_timeout=self.config.connection_timeout_seconds,
                socket_connect_timeout=self.config.connection_timeout_seconds,
                decode_responses=False,  # Work with bytes
            )

            # Verify connection
            await self._client.ping()  # type: ignore[attr-defined]

            self._connected = True
            logger.info("Connected to Redis")

        except Exception as e:
            self._connected = False
            msg = f"Failed to connect to Redis: {e}"
            raise BrokerConnectionError(msg) from e

    async def publish(
        self,
        topic: str,
        message: bytes,
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        """
        Publish a message to Redis Streams.

        Uses XADD to append to the stream with optional MAXLEN trimming.

        Args:
            topic: Used as field name within the stream entry
            message: Message payload as bytes
            headers: Optional message headers (added as fields)
            key: Optional key (used as stream key if configured)

        Raises:
            BrokerError: If not connected
            BrokerPublishError: If publishing fails
        """
        if not self._connected or self._client is None:
            msg = "Not connected to Redis"
            raise BrokerError(msg)

        try:
            fields = self._build_stream_fields(topic, message, headers, key)
            message_id = await self._client.xadd(
                self.config.stream_name,
                fields,
                maxlen=self.config.max_stream_length,
                approximate=True,
            )
            logger.debug(f"Published message to stream {self.config.stream_name}: {message_id}")

        except Exception as e:
            msg = f"Failed to publish to Redis stream: {e}"
            raise BrokerPublishError(msg) from e

    def _build_stream_fields(
        self, topic: str, message: bytes, headers: dict[str, str] | None, key: str | None
    ) -> dict[bytes, bytes]:
        """Build fields dict for Redis stream entry."""
        fields: dict[bytes, bytes] = {
            b"topic": self._encode_value(topic),
            b"payload": message,
        }
        self._add_key_field(fields, key)
        self._add_header_fields(fields, headers)
        return fields

    @staticmethod
    def _encode_value(value: str | bytes) -> bytes:
        """Encode a value to bytes."""
        return value.encode() if isinstance(value, str) else value

    def _add_key_field(self, fields: dict, key: str | None) -> None:
        """Add key field if provided."""
        if key:
            fields[b"key"] = self._encode_value(key)

    def _add_header_fields(self, fields: dict, headers: dict[str, str] | None) -> None:
        """Add header fields if provided."""
        if not headers:
            return
        for h_key, h_value in headers.items():
            field_name = f"header:{h_key}".encode()
            fields[field_name] = str(h_value).encode()

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            try:
                await self._client.close()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.warning(f"Error closing Redis connection: {e}")
            finally:
                self._client = None
                self._connected = False

    async def health_check(self) -> bool:
        """
        Check Redis connection health.

        Returns:
            True if Redis is healthy, False otherwise
        """
        if not self._client:
            return False

        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    async def ensure_consumer_group(self) -> None:
        """
        Ensure the consumer group exists.

        Creates the consumer group if it doesn't exist.
        Safe to call multiple times.
        """
        if not self._client:
            msg = "Not connected to Redis"
            raise BrokerError(msg)

        try:
            await self._client.xgroup_create(
                self.config.stream_name,
                self.config.consumer_group,
                id="0",
                mkstream=True,
            )
            logger.info(f"Created consumer group: {self.config.consumer_group}")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists, that's fine
                logger.debug(f"Consumer group already exists: {self.config.consumer_group}")
            else:
                raise

    async def read_messages(
        self,
        count: int = 10,
        block_ms: int | None = None,
    ) -> list:
        """
        Read messages from the stream as a consumer.

        Args:
            count: Maximum number of messages to read
            block_ms: Block timeout in milliseconds (None = use config default)

        Returns:
            List of (message_id, fields) tuples
        """
        if not self._client:
            msg = "Not connected to Redis"
            raise BrokerError(msg)

        block_ms = block_ms or self.config.block_timeout_ms

        messages = await self._client.xreadgroup(
            self.config.consumer_group,
            self.config.consumer_name,
            {self.config.stream_name: ">"},
            count=count,
            block=block_ms,
        )

        return messages or []

    async def acknowledge(self, message_id: str) -> None:
        """
        Acknowledge a message as processed.

        Args:
            message_id: The message ID to acknowledge
        """
        if not self._client:
            msg = "Not connected to Redis"
            raise BrokerError(msg)

        await self._client.xack(
            self.config.stream_name,
            self.config.consumer_group,
            message_id,
        )

    async def get_stream_info(self) -> dict[str, Any]:
        """
        Get information about the stream.

        Returns:
            Dict with stream length, groups, etc.
        """
        if not self._client:
            msg = "Not connected to Redis"
            raise BrokerError(msg)

        info = await self._client.xinfo_stream(self.config.stream_name)
        return {
            "length": info.get("length", 0),
            "first_entry": info.get("first-entry"),
            "last_entry": info.get("last-entry"),
            "groups": info.get("groups", 0),
        }

    def _safe_url(self) -> str:
        """Return URL with password masked for logging."""
        url = self.config.url
        if "@" in url:
            # Mask password in URL
            parts = url.split("@")
            if ":" in parts[0]:
                proto_user = parts[0].rsplit(":", 1)[0]
                return f"{proto_user}:****@{parts[1]}"
        return url


def is_redis_available() -> bool:
    """Check if Redis support is available."""
    return REDIS_AVAILABLE
