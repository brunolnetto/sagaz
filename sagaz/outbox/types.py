"""
Outbox Pattern - Transactional Outbox for Reliable Message Publishing

This module provides the transactional outbox pattern implementation for
exactly-once message delivery semantics in saga executions.

The outbox pattern ensures that:
1. Messages are stored atomically with saga state changes
2. Messages are published at-least-once (with deduplication on consumer)
3. No messages are lost even if the broker is unavailable

Quick Start:
    >>> from sagaz.outbox import OutboxEvent, OutboxStatus
    >>> 
    >>> # Create an outbox event during saga execution
    >>> event = OutboxEvent(
    ...     saga_id="order-123",
    ...     event_type="OrderCreated",
    ...     payload={"order_id": "ORD-456", "items": [...]},
    ... )
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class OutboxStatus(Enum):
    """
    Status of an outbox event in its lifecycle.
    
    State transitions:
        PENDING → CLAIMED → SENT
                ↓         ↓
              FAILED → DEAD_LETTER
    """

    PENDING = "pending"
    """Event is waiting to be published"""

    CLAIMED = "claimed"
    """Event has been claimed by a worker for publishing"""

    SENT = "sent"
    """Event was successfully published to the broker"""

    FAILED = "failed"
    """Event failed to publish (will retry)"""

    DEAD_LETTER = "dead_letter"
    """Event exceeded max retries, moved to dead letter queue"""


@dataclass
class OutboxEvent:
    """
    Represents a message in the transactional outbox.
    
    Events are stored atomically with saga state changes and then
    published to the message broker by the outbox worker.
    
    Attributes:
        event_id: Unique identifier for this event
        saga_id: ID of the saga that produced this event
        aggregate_type: Type of aggregate (e.g., "order", "payment")
        aggregate_id: ID of the aggregate instance
        event_type: Type of event (e.g., "OrderCreated", "PaymentCharged")
        payload: Event data payload (will be serialized to JSON)
        headers: Message headers for broker (trace IDs, etc.)
        status: Current status of the event
        created_at: When the event was created
        claimed_at: When the event was claimed by a worker
        sent_at: When the event was successfully sent
        retry_count: Number of publish attempts
        last_error: Last error message on failure
        worker_id: ID of worker that claimed this event
        
    Example:
        >>> event = OutboxEvent(
        ...     saga_id="order-123",
        ...     aggregate_type="order",
        ...     aggregate_id="ORD-456",
        ...     event_type="OrderCreated",
        ...     payload={"items": [{"sku": "WIDGET-001", "qty": 2}]},
        ...     headers={"trace_id": "abc123"}
        ... )
    """

    saga_id: str
    event_type: str
    payload: dict[str, Any]

    # Optional fields with defaults
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    aggregate_type: str = "saga"
    aggregate_id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    status: OutboxStatus = OutboxStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    claimed_at: datetime | None = None
    sent_at: datetime | None = None
    retry_count: int = 0
    last_error: str | None = None
    worker_id: str | None = None
    routing_key: str | None = None
    partition_key: str | None = None

    def __post_init__(self):
        """Set aggregate_id to saga_id if not specified."""
        if self.aggregate_id is None:
            self.aggregate_id = self.saga_id

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "saga_id": self.saga_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "headers": self.headers,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "claimed_at": self.claimed_at.isoformat() if self.claimed_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "worker_id": self.worker_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutboxEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            saga_id=data["saga_id"],
            aggregate_type=data.get("aggregate_type", "saga"),
            aggregate_id=data.get("aggregate_id"),
            event_type=data["event_type"],
            payload=data["payload"],
            headers=data.get("headers", {}),
            status=cls._parse_status(data.get("status", "pending")),
            created_at=cls._parse_datetime(data.get("created_at")) or datetime.now(UTC),
            claimed_at=cls._parse_datetime(data.get("claimed_at")),
            sent_at=cls._parse_datetime(data.get("sent_at")),
            retry_count=data.get("retry_count", 0),
            last_error=data.get("last_error"),
            worker_id=data.get("worker_id"),
        )

    @staticmethod
    def _parse_status(status: str | OutboxStatus) -> OutboxStatus:
        """Parse status from string or OutboxStatus."""
        if isinstance(status, str):
            return OutboxStatus(status)
        return status

    @staticmethod
    def _parse_datetime(value: str | datetime | None) -> datetime | None:
        """Parse datetime from string or return as-is."""
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value


@dataclass
class OutboxConfig:
    """
    Configuration for the outbox pattern.
    
    Attributes:
        batch_size: Number of events to claim per batch
        poll_interval_seconds: Seconds between polling for events
        claim_timeout_seconds: Seconds before a claimed event is considered stuck
        max_retries: Maximum retry attempts before moving to dead letter
        optimistic_publish: Whether to attempt immediate publish after commit
        optimistic_timeout_ms: Timeout for optimistic publish in milliseconds
        archive_after_days: Days to keep sent events before archiving
    """

    batch_size: int = 100
    poll_interval_seconds: float = 1.0
    claim_timeout_seconds: float = 300.0  # 5 minutes
    max_retries: int = 10
    optimistic_publish: bool = True
    optimistic_timeout_ms: int = 500
    archive_after_days: int = 7

    @classmethod
    def from_env(cls) -> "OutboxConfig":
        """Create config from environment variables."""
        import os

        return cls(
            batch_size=int(os.getenv("OUTBOX_BATCH_SIZE", 100)),
            poll_interval_seconds=float(os.getenv("OUTBOX_POLL_INTERVAL", 1.0)),
            claim_timeout_seconds=float(os.getenv("OUTBOX_CLAIM_TIMEOUT", 300.0)),
            max_retries=int(os.getenv("OUTBOX_MAX_RETRIES", 10)),
            optimistic_publish=os.getenv("OUTBOX_OPTIMISTIC", "true").lower() == "true",
            optimistic_timeout_ms=int(os.getenv("OUTBOX_OPTIMISTIC_TIMEOUT_MS", 500)),
            archive_after_days=int(os.getenv("OUTBOX_ARCHIVE_DAYS", 7)),
        )


class OutboxError(Exception):
    """Base exception for outbox errors."""


class OutboxPublishError(OutboxError):
    """Error publishing message to broker."""

    def __init__(self, event: OutboxEvent, message: str, cause: Exception | None = None):
        self.event = event
        self.cause = cause
        super().__init__(f"Failed to publish event {event.event_id}: {message}")


class OutboxClaimError(OutboxError):
    """Error claiming events from outbox."""
