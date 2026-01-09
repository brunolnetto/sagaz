"""
Message Broker Protocol - Abstract interface for message brokers.

This module defines the protocol that all message broker implementations
must follow, enabling support for Kafka, RabbitMQ, NATS, and others.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sagaz.outbox.types import OutboxEvent


@runtime_checkable
class MessageBroker(Protocol):
    """
    Protocol for message broker implementations.

    All broker implementations (Kafka, RabbitMQ, NATS, etc.) must
    implement this protocol to be usable with the outbox pattern.
    """

    async def connect(self) -> None:
        """
        Connect to the message broker.

        Establishes the connection and prepares for publishing.

        Raises:
            BrokerConnectionError: If connection fails
        """
        ...

    async def publish(
        self,
        topic: str,
        message: bytes,
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        """
        Publish a message to the broker.

        Args:
            topic: Topic/queue/exchange to publish to
            message: Message payload as bytes
            headers: Optional message headers
            key: Optional message key for partitioning

        Raises:
            BrokerError: If publishing fails
        """
        ...

    async def close(self) -> None:
        """Close the broker connection."""
        ...

    async def health_check(self) -> bool:
        """
        Check if the broker connection is healthy.

        Returns:
            True if healthy, False otherwise
        """
        ...


class BrokerError(Exception):
    """Base exception for broker errors."""


class BrokerConnectionError(BrokerError):
    """Error connecting to the broker."""


class BrokerPublishError(BrokerError):
    """Error publishing a message."""


@dataclass
class BrokerConfig:
    """
    Base configuration for message brokers.

    Subclass for broker-specific config.
    """

    # Common settings
    connection_timeout_seconds: float = 30.0
    publish_timeout_seconds: float = 10.0
    retry_count: int = 3
    retry_backoff_seconds: float = 1.0


class BaseBroker(ABC):
    """
    Abstract base class for message broker implementations.

    Provides common functionality and enforces the MessageBroker protocol.
    """

    def __init__(self, config: BrokerConfig | None = None):
        self.config = config or BrokerConfig()
        self._connected = False

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the broker."""
        ...

    @abstractmethod
    async def publish(
        self,
        topic: str,
        message: bytes,
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        """Publish a message to the broker."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the broker connection."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check broker health."""
        ...

    @property
    def is_connected(self) -> bool:
        """Check if broker is connected."""
        return self._connected

    async def publish_event(
        self,
        event: OutboxEvent,
        topic: str | None = None,
    ) -> None:
        """
        Publish an outbox event to the broker.

        This is a convenience method that serializes the event
        and publishes it with appropriate headers.

        Args:
            event: The outbox event to publish
            topic: Optional topic override (defaults to event_type)
        """
        import json

        topic = topic or event.event_type

        # Build message payload
        payload = {
            "event_id": event.event_id,
            "saga_id": event.saga_id,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "event_type": event.event_type,
            "payload": event.payload,
            "timestamp": event.created_at.isoformat() if event.created_at else None,
        }

        message = json.dumps(payload).encode("utf-8")

        # Merge headers
        headers = {
            "event_id": event.event_id,
            "saga_id": event.saga_id,
            "event_type": event.event_type,
            "content_type": "application/json",
            **event.headers,
        }

        await self.publish(
            topic=topic,
            message=message,
            headers=headers,
            key=event.aggregate_id,
        )
