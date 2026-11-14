"""
Status-transition UPDATE builders for ``SQLiteOutboxStorage.update_status``.

Each builder returns the SQL statement and its positional parameters for one
target status.
"""

from __future__ import annotations

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus


class SQLiteOutboxStatusQueryMixin:
    """Build the ``UPDATE`` statement for a status transition."""

    def _build_update_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
        now: str,
    ) -> tuple[str, tuple]:
        if status == OutboxStatus.FAILED:
            return self._failed_status_query(event_id, status, error_message, event)
        if status == OutboxStatus.DEAD_LETTER:
            return self._dead_letter_status_query(event_id, status, error_message, event, now)
        if status == OutboxStatus.PENDING:
            return self._pending_status_query(event_id, status, event)
        return self._default_status_query(event_id, status, error_message, now)

    def _failed_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> tuple[str, tuple]:
        return (
            """
                UPDATE outbox_events
                SET status = ?,
                    retry_count = retry_count + 1,
                    last_error = ?,
                    error_type = ?,
                    error_classification = ?,
                    error_fingerprint = ?
                WHERE event_id = ?
            """,
            (
                status.value,
                error_message,
                event.error_type if event else None,
                event.error_classification if event else None,
                event.error_fingerprint if event else None,
                event_id,
            ),
        )

    def _dead_letter_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
        now: str,
    ) -> tuple[str, tuple]:
        return (
            """
                UPDATE outbox_events
                SET status = ?,
                    dead_letter_at = COALESCE(?, ?),
                    dead_letter_reason = COALESCE(?, last_error, dead_letter_reason, 'max_retries_exceeded'),
                    error_type = COALESCE(?, error_type),
                    error_classification = COALESCE(?, error_classification),
                    error_fingerprint = COALESCE(?, error_fingerprint)
                WHERE event_id = ?
            """,
            (
                status.value,
                event.dead_letter_at.isoformat() if event and event.dead_letter_at else None,
                now,
                event.dead_letter_reason if event else error_message,
                event.error_type if event else None,
                event.error_classification if event else None,
                event.error_fingerprint if event else None,
                event_id,
            ),
        )

    def _pending_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        event: OutboxEvent | None,
    ) -> tuple[str, tuple]:
        return (
            """
                UPDATE outbox_events
                SET status = ?,
                    worker_id = NULL,
                    claimed_at = NULL,
                    dead_letter_at = NULL,
                    dead_letter_reason = NULL,
                    retry_count = COALESCE(?, retry_count),
                    replay_count = COALESCE(?, replay_count)
                WHERE event_id = ?
            """,
            (
                status.value,
                event.retry_count if event else None,
                event.replay_count if event else None,
                event_id,
            ),
        )

    def _default_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        now: str,
    ) -> tuple[str, tuple]:
        sent_at = now if status == OutboxStatus.SENT else None
        return (
            """
                UPDATE outbox_events
                SET status = ?, last_error = ?, sent_at = COALESCE(?, sent_at)
                WHERE event_id = ?
            """,
            (status.value, error_message, sent_at, event_id),
        )
