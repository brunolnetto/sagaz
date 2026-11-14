"""
Row mapping for ``SQLiteOutboxStorage``: converts ``outbox_events`` rows into
``OutboxEvent`` instances.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.core import deserialize
from sagaz.core.tenant import DEFAULT_TENANT

if TYPE_CHECKING:
    import aiosqlite


class SQLiteOutboxRowMappingMixin:
    """Convert database rows to ``OutboxEvent`` objects."""

    def _row_to_event(self, row: aiosqlite.Row) -> OutboxEvent:
        """Convert database row to OutboxEvent."""
        return OutboxEvent(
            event_id=str(row["event_id"]),
            saga_id=row["saga_id"],
            event_type=row["event_type"],
            payload=deserialize(row["payload"]),
            status=OutboxStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else datetime.now(UTC),
            claimed_at=datetime.fromisoformat(row["claimed_at"]) if row["claimed_at"] else None,
            sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
            worker_id=row["worker_id"],
            retry_count=row["retry_count"] or 0,
            last_error=row["last_error"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            headers=deserialize(row["headers"]) if row["headers"] else {},
            routing_key=row["routing_key"],
            partition_key=row["partition_key"],
            dead_letter_at=datetime.fromisoformat(row["dead_letter_at"])
            if row["dead_letter_at"]
            else None,
            dead_letter_reason=row["dead_letter_reason"],
            error_type=row["error_type"],
            error_classification=row["error_classification"],
            error_fingerprint=row["error_fingerprint"],
            replay_count=row["replay_count"] or 0,
            tenant_id=row["tenant_id"] or DEFAULT_TENANT,
        )
