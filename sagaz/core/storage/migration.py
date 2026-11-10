"""
Storage Migration — Facade for cross-backend saga data transfer.

Wraps ``TransferService`` to provide a migration-oriented API with:
- ``migrate()`` — transfer all saga state and outbox events between backends
- ``verify()``  — compare record counts between source and destination
- Rich / plain-text progress output for CLI usage

Usage::

    from sagaz.storage.migration import SagaStorageMigrator

    migrator = SagaStorageMigrator(source_manager, dest_manager)
    result = await migrator.migrate(dry_run=False, batch_size=500)
    if result.success:
        print(f"Migrated {result.sagas_transferred} sagas, "
              f"{result.events_transferred} outbox events")
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sagaz.storage.transfer.service import (
    TransferResult,
    transfer_data,
)

if TYPE_CHECKING:
    from sagaz.storage.manager import StorageManager

logger = logging.getLogger(__name__)


def _canonical_checksum_value(value: Any) -> Any:
    """Convert storage values to a JSON-safe, deterministic representation."""
    if hasattr(value, "to_dict"):
        return _canonical_checksum_value(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _canonical_checksum_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_checksum_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_canonical_checksum_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


async def _storage_checksum(storage: Any, *, ignored_fields: frozenset[str] = frozenset()) -> tuple[int, str]:
    """Compute an order-independent checksum over all exported storage records."""
    if not hasattr(storage, "export_all"):
        raise TypeError(f"{storage.__class__.__name__} does not support export_all()")

    count = 0
    sum_digest = 0
    sum_squares = 0
    modulus = 1 << 256

    async for record in storage.export_all():
        normalized = _canonical_checksum_value(record)
        if isinstance(normalized, dict) and ignored_fields:
            normalized = {
                key: value for key, value in normalized.items() if key not in ignored_fields
            }
        serialized = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        digest = int.from_bytes(hashlib.sha256(serialized).digest(), "big")
        sum_digest = (sum_digest + digest) % modulus
        sum_squares = (sum_squares + digest * digest) % modulus
        count += 1

    checksum_payload = (
        count.to_bytes(8, "big")
        + sum_digest.to_bytes(32, "big")
        + sum_squares.to_bytes(32, "big")
    )
    return count, hashlib.sha256(checksum_payload).hexdigest()


@dataclass
class MigrationResult:
    """Result of a complete migration run."""

    sagas_transferred: int = 0
    sagas_failed: int = 0
    sagas_skipped: int = 0
    events_transferred: int = 0
    events_failed: int = 0
    events_skipped: int = 0
    dry_run: bool = False

    @property
    def success(self) -> bool:
        return (
            self.sagas_failed == 0
            and self.sagas_skipped == 0
            and self.events_failed == 0
            and self.events_skipped == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sagas_transferred": self.sagas_transferred,
            "sagas_failed": self.sagas_failed,
            "sagas_skipped": self.sagas_skipped,
            "events_transferred": self.events_transferred,
            "events_failed": self.events_failed,
            "events_skipped": self.events_skipped,
            "dry_run": self.dry_run,
            "success": self.success,
        }


@dataclass
class VerificationResult:
    """Result of a source-vs-destination count comparison."""

    source_sagas: int = 0
    dest_sagas: int = 0
    source_events: int = 0
    dest_events: int = 0
    source_saga_checksum: str = ""
    dest_saga_checksum: str = ""
    source_event_checksum: str = ""
    dest_event_checksum: str = ""

    @property
    def sagas_match(self) -> bool:
        return self.source_sagas == self.dest_sagas

    @property
    def events_match(self) -> bool:
        return self.source_events == self.dest_events

    @property
    def saga_checksums_match(self) -> bool:
        return (
            not self.source_saga_checksum
            and not self.dest_saga_checksum
        ) or (
            bool(self.source_saga_checksum)
            and self.source_saga_checksum == self.dest_saga_checksum
        )

    @property
    def event_checksums_match(self) -> bool:
        return (
            not self.source_event_checksum
            and not self.dest_event_checksum
        ) or (
            bool(self.source_event_checksum)
            and self.source_event_checksum == self.dest_event_checksum
        )

    @property
    def ok(self) -> bool:
        return (
            self.sagas_match
            and self.events_match
            and self.saga_checksums_match
            and self.event_checksums_match
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_sagas": self.source_sagas,
            "dest_sagas": self.dest_sagas,
            "source_events": self.source_events,
            "dest_events": self.dest_events,
            "sagas_match": self.sagas_match,
            "events_match": self.events_match,
            "source_saga_checksum": self.source_saga_checksum,
            "dest_saga_checksum": self.dest_saga_checksum,
            "saga_checksums_match": self.saga_checksums_match,
            "source_event_checksum": self.source_event_checksum,
            "dest_event_checksum": self.dest_event_checksum,
            "event_checksums_match": self.event_checksums_match,
            "ok": self.ok,
        }


class SagaStorageMigrator:
    """
    Facade for migrating saga and outbox data between storage backends.

    Parameters
    ----------
    source:
        StorageManager open against the source backend.
    destination:
        StorageManager open against the destination backend.
    """

    def __init__(self, source: StorageManager, destination: StorageManager) -> None:
        self._source = source
        self._destination = destination

    async def migrate(
        self,
        *,
        dry_run: bool = False,
        batch_size: int = 100,
        on_error: str = "skip",
        progress_callback: Any = None,
    ) -> MigrationResult:
        """
        Transfer all sagas and outbox events from source to destination.

        Parameters
        ----------
        dry_run:
            When *True*, perform all reads but skip writes to destination.
        batch_size:
            Records per batch.
        on_error:
            One of ``"skip"``, ``"abort"``, ``"retry"``.
        progress_callback:
            Optional ``(transferred, failed, total)`` callable for progress.

        Returns
        -------
        MigrationResult
        """
        result = MigrationResult(dry_run=dry_run)
        if dry_run:
            logger.info("[dry-run] skipping writes to destination")
            return result

        # Migrate saga state
        saga_result: TransferResult = await transfer_data(
            self._source.saga,
            self._destination.saga,
            batch_size=batch_size,
            validate=True,
            on_error=on_error,
            progress_callback=progress_callback,
        )
        result.sagas_transferred = saga_result.transferred
        result.sagas_failed = saga_result.failed
        result.sagas_skipped = saga_result.skipped

        # Migrate outbox events
        outbox_result: TransferResult = await transfer_data(
            self._source.outbox,
            self._destination.outbox,
            batch_size=batch_size,
            validate=True,
            on_error=on_error,
            progress_callback=progress_callback,
        )
        result.events_transferred = outbox_result.transferred
        result.events_failed = outbox_result.failed
        result.events_skipped = outbox_result.skipped

        logger.info(
            "Migration complete: sagas=%d(+%d failed), events=%d(+%d failed)",
            result.sagas_transferred,
            result.sagas_failed,
            result.events_transferred,
            result.events_failed,
        )
        return result

    async def verify(self) -> VerificationResult:
        """
        Compare record counts and deterministic content checksums.

        Saga storage timestamps managed by the destination backend
        (``created_at`` and ``updated_at``) are excluded from the Saga
        checksum. Outbox timestamps and all event metadata remain part of the
        checksum because they are part of the delivery/recovery state.
        """
        vr = VerificationResult()

        try:
            vr.source_sagas, vr.source_saga_checksum = await _storage_checksum(
                self._source.saga,
                ignored_fields=frozenset({"created_at", "updated_at"}),
            )
        except Exception:
            vr.source_sagas = -1

        try:
            vr.dest_sagas, vr.dest_saga_checksum = await _storage_checksum(
                self._destination.saga,
                ignored_fields=frozenset({"created_at", "updated_at"}),
            )
        except Exception:
            vr.dest_sagas = -1

        try:
            vr.source_events, vr.source_event_checksum = await _storage_checksum(
                self._source.outbox
            )
        except Exception:
            vr.source_events = -1

        try:
            vr.dest_events, vr.dest_event_checksum = await _storage_checksum(
                self._destination.outbox
            )
        except Exception:
            vr.dest_events = -1

        return vr
