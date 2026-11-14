"""
Event (de)serialization for ``RedisOutboxStorage``.

Events are stored as flat Redis hashes of strings; these helpers map an
``OutboxEvent`` to and from that representation.
"""

from datetime import UTC, datetime

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.redis._outbox_tenancy import RedisOutboxTenancyMixin
from sagaz.core.storage.core import deserialize, serialize
from sagaz.core.tenant import DEFAULT_TENANT


class RedisOutboxSerializationMixin(RedisOutboxTenancyMixin):
    """Key naming and hash (de)serialization for outbox events."""

    def _meta_key(self, event_id: str) -> str:
        """Get the metadata key of an event of the current tenant."""
        return f"{self._tenant_prefix()}:meta:{event_id}"

    @staticmethod
    def _optional_text(value: str | None) -> str:
        return value or ""

    @staticmethod
    def _optional_datetime(value: datetime | None) -> str:
        if value is None:
            return ""
        return value.isoformat()

    @staticmethod
    def _decode_hash(data: dict[bytes | str, bytes | str]) -> dict[str, str]:
        return {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in data.items()
        }

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def _none_if_empty(value: str) -> str | None:
        return value or None

    def _serialize_event(self, event: OutboxEvent) -> dict[str, str]:
        """Serialize event for Redis storage."""
        return {
            "event_id": event.event_id,
            "saga_id": event.saga_id,
            "aggregate_type": event.aggregate_type or "saga",
            "aggregate_id": self._optional_text(event.aggregate_id),
            "event_type": event.event_type,
            "payload": serialize(event.payload),
            "headers": serialize(event.headers),
            "status": event.status.value,
            "retry_count": str(event.retry_count),
            "created_at": self._optional_datetime(event.created_at),
            "claimed_at": self._optional_datetime(event.claimed_at),
            "sent_at": self._optional_datetime(event.sent_at),
            "last_error": self._optional_text(event.last_error),
            "worker_id": self._optional_text(event.worker_id),
            "routing_key": self._optional_text(event.routing_key),
            "partition_key": self._optional_text(event.partition_key),
            "dead_letter_at": self._optional_datetime(event.dead_letter_at),
            "dead_letter_reason": self._optional_text(event.dead_letter_reason),
            "error_type": self._optional_text(event.error_type),
            "error_classification": self._optional_text(event.error_classification),
            "error_fingerprint": self._optional_text(event.error_fingerprint),
            "replay_count": str(event.replay_count),
            "tenant_id": event.tenant_id,
        }

    def _deserialize_event(self, data: dict[bytes | str, bytes | str]) -> OutboxEvent:
        """Deserialize event from Redis storage."""
        decoded = self._decode_hash(data)

        return OutboxEvent(
            event_id=decoded.get("event_id", ""),
            saga_id=decoded.get("saga_id", ""),
            aggregate_type=decoded.get("aggregate_type", "saga"),
            aggregate_id=self._none_if_empty(decoded.get("aggregate_id", "")),
            event_type=decoded.get("event_type", ""),
            payload=deserialize(decoded.get("payload", "{}")),
            headers=deserialize(decoded.get("headers", "{}")),
            status=OutboxStatus(decoded.get("status", "pending")),
            retry_count=int(decoded.get("retry_count", 0)),
            created_at=self._parse_datetime(decoded.get("created_at", "")) or datetime.now(UTC),
            claimed_at=self._parse_datetime(decoded.get("claimed_at", "")),
            sent_at=self._parse_datetime(decoded.get("sent_at", "")),
            last_error=self._none_if_empty(decoded.get("last_error", "")),
            worker_id=self._none_if_empty(decoded.get("worker_id", "")),
            routing_key=self._none_if_empty(decoded.get("routing_key", "")),
            partition_key=self._none_if_empty(decoded.get("partition_key", "")),
            dead_letter_at=self._parse_datetime(decoded.get("dead_letter_at", "")),
            dead_letter_reason=self._none_if_empty(decoded.get("dead_letter_reason", "")),
            error_type=self._none_if_empty(decoded.get("error_type", "")),
            error_classification=self._none_if_empty(decoded.get("error_classification", "")),
            error_fingerprint=self._none_if_empty(decoded.get("error_fingerprint", "")),
            replay_count=int(decoded.get("replay_count", 0)),
            tenant_id=decoded.get("tenant_id") or DEFAULT_TENANT,
        )
