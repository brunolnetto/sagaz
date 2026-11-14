"""
Status-transition hash updates for ``RedisOutboxStorage.update_status``.

Builds the field mapping written to an event's metadata hash for each target
status, mirroring the column updates performed by the SQL backends.
"""

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.redis._outbox_serialization import (
    RedisOutboxSerializationMixin,
)


class RedisOutboxStatusUpdatesMixin(RedisOutboxSerializationMixin):
    """Builders for the metadata updates applied on a status transition."""

    async def _build_status_updates(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
        now: str,
    ) -> dict[str, str]:
        updates = {"status": status.value}
        if status == OutboxStatus.SENT:
            updates["sent_at"] = now
            return updates
        if status == OutboxStatus.FAILED:
            updates.update(await self._failed_updates(event_id, error_message, event))
            return updates
        if status == OutboxStatus.DEAD_LETTER:
            updates.update(self._dead_letter_updates(now, error_message, event))
            return updates
        if status == OutboxStatus.PENDING and event:
            updates.update(self._pending_replay_updates(event))
        return updates

    async def _failed_updates(
        self,
        event_id: str,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> dict[str, str]:
        # Like the SQL backends, every FAILED transition counts as a retry.
        current = await self.get_by_id(event_id)
        updates = {"retry_count": str((current.retry_count if current else 0) + 1)}
        if error_message:
            updates["last_error"] = error_message
        updates.update(self._error_metadata_updates(event))
        return updates

    def _dead_letter_updates(
        self,
        now: str,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> dict[str, str]:
        reason = ""
        if event and event.dead_letter_reason:
            reason = event.dead_letter_reason
        elif error_message:
            reason = error_message
        return {
            # Same as COALESCE(dead_letter_at, NOW()) in the SQL backends.
            "dead_letter_at": (
                event.dead_letter_at.isoformat() if event and event.dead_letter_at else now
            ),
            "dead_letter_reason": reason,
            **self._error_metadata_updates(event),
        }

    def _pending_replay_updates(self, event: OutboxEvent) -> dict[str, str]:
        return {
            "replay_count": str(event.replay_count),
            "dead_letter_at": "",
            "dead_letter_reason": "",
        }

    def _error_metadata_updates(self, event: OutboxEvent | None) -> dict[str, str]:
        return {
            "error_type": self._optional_text(event.error_type if event else None),
            "error_classification": self._optional_text(
                event.error_classification if event else None
            ),
            "error_fingerprint": self._optional_text(event.error_fingerprint if event else None),
        }

    @staticmethod
    def _decode_status(value: bytes | str | None) -> OutboxStatus | None:
        """The ``OutboxStatus`` stored in a metadata hash field, if any."""
        if value is None:
            return None
        text = value.decode() if isinstance(value, bytes) else value
        try:
            return OutboxStatus(text)
        except ValueError:
            return None

    async def _enqueue_for_delivery(self, event: OutboxEvent) -> None:
        """Append a stream entry so a consumer group delivers ``event`` (again).

        ``claim_batch`` only reads entries not yet delivered to the group, so an
        event that returns to PENDING (retry after a failed publish, DLQ
        requeue) needs a fresh entry in its tenant's stream (#401).
        """
        assert self._redis is not None
        await self._redis.xadd(
            self._scoped_stream_key(),
            {"event_id": event.event_id, "saga_id": event.saga_id, "event_type": event.event_type},
            maxlen=self._max_stream_length,
        )
