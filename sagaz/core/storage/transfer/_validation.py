"""Post-import validation for :class:`~sagaz.core.storage.transfer.service.TransferService`."""

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

from sagaz.core.storage.canonical import canonical_value
from sagaz.core.storage.core import TransferError


class _TransferValidationMixin:
    """Checks that each imported record exists (and matches) in the target."""

    target: Any

    def _get_validation_lookup(
        self,
        record: dict[str, Any],
    ) -> Callable[[str], Awaitable[Any]] | None:
        """Select the target lookup method according to record type."""
        if "event_id" in record:
            return self.target.get_by_id if hasattr(self.target, "get_by_id") else None

        if hasattr(self.target, "load_saga_state"):
            return cast("Callable[[str], Awaitable[Any]]", self.target.load_saga_state)

        if hasattr(self.target, "get_by_id"):
            return cast("Callable[[str], Awaitable[Any]]", self.target.get_by_id)

        return None

    async def _validate_record(self, record: dict[str, Any]) -> None:
        """Validate a transferred record exists and matches in target storage."""
        record_id = record.get("event_id") or record.get("saga_id") or record.get("id")
        if not record_id:
            return

        lookup = self._get_validation_lookup(record)
        if lookup is None:
            return

        loaded = await lookup(record_id)

        if loaded is None:
            raise TransferError(
                message=f"Validation failed: record {record_id} not found in target",
                target=self.target.__class__.__name__,
            )

        if "event_id" in record:
            self._validate_event_record(record, loaded, record_id)

    def _validate_event_record(
        self,
        expected_record: dict[str, Any],
        actual_record: Any,
        record_id: str,
    ) -> None:
        """Ensure an imported outbox event matches its source representation."""
        expected = self._canonical_record(expected_record)
        actual = self._canonical_record(actual_record)

        if expected != actual:
            raise TransferError(
                message=f"Validation failed: event {record_id} differs after import",
                target=self.target.__class__.__name__,
            )

    @staticmethod
    def _canonical_record(record: Any) -> str:
        """Serialize records with normalized timestamps for cross-backend comparison."""
        if hasattr(record, "to_dict"):
            record = record.to_dict()

        # Fill optional OutboxEvent fields with their canonical defaults so older
        # callers that export a minimal record remain comparable after import.
        if isinstance(record, dict) and {
            "event_id",
            "saga_id",
            "event_type",
            "payload",
        }.issubset(record):
            from sagaz.core.outbox.types import OutboxEvent

            record = OutboxEvent.from_dict(record).to_dict()

        return json.dumps(
            canonical_value(record),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
