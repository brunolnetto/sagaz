"""
Status-transition UPDATE builders for ``PostgreSQLOutboxStorage.update_status``.

Each builder returns the SQL statement and its positional parameters for one
target status.
"""

from typing import Any

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus


class PostgreSQLOutboxStatusQueryMixin:
    """Build the ``UPDATE ... RETURNING *`` statement for a status transition."""

    def _build_update_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> tuple[str, tuple[Any, ...]]:
        if status == OutboxStatus.SENT:
            return self._sent_status_query(event_id, status)
        if status == OutboxStatus.FAILED:
            return self._failed_status_query(event_id, status, error_message, event)
        if status == OutboxStatus.DEAD_LETTER:
            return self._dead_letter_status_query(event_id, status, error_message, event)
        if status == OutboxStatus.PENDING:
            return self._pending_status_query(event_id, status, event)
        return self._generic_status_query(event_id, status)

    def _sent_status_query(
        self, event_id: str, status: OutboxStatus
    ) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2, sent_at = NOW()
                WHERE event_id = $1
                RETURNING *
            """,
            (event_id, status.value),
        )

    def _failed_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2,
                retry_count = retry_count + 1,
                last_error = $3,
                error_type = $4,
                error_classification = $5,
                error_fingerprint = $6
                WHERE event_id = $1
                RETURNING *
            """,
            (
                event_id,
                status.value,
                error_message,
                event.error_type if event else None,
                event.error_classification if event else None,
                event.error_fingerprint if event else None,
            ),
        )

    def _dead_letter_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2,
                    dead_letter_at = COALESCE($3, NOW()),
                    dead_letter_reason = COALESCE($4, last_error, dead_letter_reason, 'max_retries_exceeded'),
                    error_type = COALESCE($5, error_type),
                    error_classification = COALESCE($6, error_classification),
                    error_fingerprint = COALESCE($7, error_fingerprint)
                WHERE event_id = $1
                RETURNING *
            """,
            (
                event_id,
                status.value,
                event.dead_letter_at if event else None,
                event.dead_letter_reason if event else error_message,
                event.error_type if event else None,
                event.error_classification if event else None,
                event.error_fingerprint if event else None,
            ),
        )

    def _pending_status_query(
        self, event_id: str, status: OutboxStatus, event: OutboxEvent | None
    ) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2,
                worker_id = NULL,
                claimed_at = NULL,
                dead_letter_at = NULL,
                dead_letter_reason = NULL,
                replay_count = COALESCE($3, replay_count)
                WHERE event_id = $1
                RETURNING *
            """,
            (event_id, status.value, event.replay_count if event else None),
        )

    def _generic_status_query(
        self, event_id: str, status: OutboxStatus
    ) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2
                WHERE event_id = $1
                RETURNING *
            """,
            (event_id, status.value),
        )
