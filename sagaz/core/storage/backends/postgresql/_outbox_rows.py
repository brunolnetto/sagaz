"""
Row mapping for ``PostgreSQLOutboxStorage``: converts ``saga_outbox`` rows into
``OutboxEvent`` instances.
"""

import json
from typing import TYPE_CHECKING

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.tenant import DEFAULT_TENANT

if TYPE_CHECKING:
    import asyncpg


class PostgreSQLOutboxRowMappingMixin:
    """Convert database rows to ``OutboxEvent`` objects."""

    def _row_to_event(self, row: "asyncpg.Record") -> OutboxEvent:
        """Convert database row to OutboxEvent."""

        def _row_value(key: str, default=None):
            if hasattr(row, "__contains__") and key in row:
                return row[key]
            if hasattr(row, "get"):
                return row.get(key, default)
            return default

        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)

        headers = row["headers"]
        if isinstance(headers, str):
            headers = json.loads(headers)

        return OutboxEvent(
            event_id=str(row["event_id"]),
            saga_id=row["saga_id"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            event_type=row["event_type"],
            payload=payload,
            headers=headers,
            status=OutboxStatus(row["status"]),
            created_at=row["created_at"],
            claimed_at=row["claimed_at"],
            sent_at=row["sent_at"],
            retry_count=row["retry_count"],
            last_error=row["last_error"],
            worker_id=row["worker_id"],
            dead_letter_at=_row_value("dead_letter_at"),
            dead_letter_reason=_row_value("dead_letter_reason"),
            error_type=_row_value("error_type"),
            error_classification=_row_value("error_classification"),
            error_fingerprint=_row_value("error_fingerprint"),
            replay_count=_row_value("replay_count", 0) or 0,
            routing_key=_row_value("routing_key"),
            partition_key=_row_value("partition_key"),
            tenant_id=_row_value("tenant_id") or DEFAULT_TENANT,
        )
