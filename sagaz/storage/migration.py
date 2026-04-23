"""Storage migration facade.

Provides ``SagaStorageMigrator`` plus ``MigrationResult`` / ``VerificationResult``
at the top-level ``sagaz.storage.migration`` path so tests can patch
``sagaz.storage.migration.transfer_data`` cleanly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sagaz.core.storage.transfer.service import TransferResult, transfer_data

if TYPE_CHECKING:
    from sagaz.core.storage.manager import StorageManager

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """Result of a complete migration run."""

    sagas_transferred: int = 0
    sagas_failed: int = 0
    events_transferred: int = 0
    events_failed: int = 0
    dry_run: bool = False

    @property
    def success(self) -> bool:
        return self.sagas_failed == 0 and self.events_failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sagas_transferred": self.sagas_transferred,
            "sagas_failed": self.sagas_failed,
            "events_transferred": self.events_transferred,
            "events_failed": self.events_failed,
            "dry_run": self.dry_run,
            "success": self.success,
        }


@dataclass
class VerificationResult:
    """Comparison of saga and event counts between two backends."""

    source_sagas: int = 0
    dest_sagas: int = 0
    source_events: int = 0
    dest_events: int = 0

    @property
    def sagas_match(self) -> bool:
        return self.source_sagas == self.dest_sagas

    @property
    def events_match(self) -> bool:
        return self.source_events == self.dest_events

    @property
    def ok(self) -> bool:
        return self.sagas_match and self.events_match

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_sagas": self.source_sagas,
            "dest_sagas": self.dest_sagas,
            "source_events": self.source_events,
            "dest_events": self.dest_events,
            "sagas_match": self.sagas_match,
            "events_match": self.events_match,
            "ok": self.ok,
        }


class SagaStorageMigrator:
    """Facade for migrating saga and outbox data between storage backends."""

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
        """Transfer all sagas and outbox events from source to destination."""
        result = MigrationResult(dry_run=dry_run)
        if dry_run:
            logger.info("[dry-run] skipping writes to destination")
            return result

        saga_result: TransferResult = await transfer_data(
            self._source.saga,
            self._destination.saga,
            batch_size=batch_size,
            validate=True,
            on_error=on_error,
        )
        result.sagas_transferred = saga_result.transferred
        result.sagas_failed = saga_result.failed

        outbox_result: TransferResult = await transfer_data(
            self._source.outbox,
            self._destination.outbox,
            batch_size=batch_size,
            validate=True,
            on_error=on_error,
        )
        result.events_transferred = outbox_result.transferred
        result.events_failed = outbox_result.failed

        logger.info(
            "Migration complete: sagas=%d(+%d failed), events=%d(+%d failed)",
            result.sagas_transferred,
            result.sagas_failed,
            result.events_transferred,
            result.events_failed,
        )
        return result

    async def verify(self) -> VerificationResult:
        """Compare record counts between source and destination."""
        vr = VerificationResult()
        try:
            src_saga_stats = await self._source.saga.get_statistics()
            vr.source_sagas = src_saga_stats.total_records
        except Exception:
            vr.source_sagas = -1
        try:
            dst_saga_stats = await self._destination.saga.get_statistics()
            vr.dest_sagas = dst_saga_stats.total_records
        except Exception:
            vr.dest_sagas = -1
        try:
            vr.source_events = await self._source.outbox.count()
        except Exception:
            vr.source_events = -1
        try:
            vr.dest_events = await self._destination.outbox.count()
        except Exception:
            vr.dest_events = -1
        return vr


__all__ = [
    "MigrationResult",
    "SagaStorageMigrator",
    "TransferResult",
    "VerificationResult",
    "transfer_data",
]
