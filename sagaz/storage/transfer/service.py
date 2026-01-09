"""
Storage Transfer Service - Data Migration Between Backends.

Provides utilities for migrating saga and outbox data between
different storage backends (e.g., memory -> Redis, PostgreSQL -> Redis).

Usage:
    >>> from sagaz.storage.transfer import TransferService, TransferConfig
    >>>
    >>> # Configure transfer
    >>> config = TransferConfig(
    ...     batch_size=100,
    ...     validate=True,
    ...     on_error="skip",
    ... )
    >>>
    >>> # Migrate saga data
    >>> service = TransferService(source_storage, target_storage, config)
    >>> result = await service.transfer_all()
    >>>
    >>> print(f"Transferred {result.transferred} records")
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from enum import Enum
from typing import Any

from sagaz.storage.core import StorageError, TransferError

logger = logging.getLogger(__name__)


class TransferErrorPolicy(Enum):
    """Policy for handling transfer errors."""

    ABORT = "abort"  # Stop transfer on first error
    SKIP = "skip"  # Skip failed records, continue
    RETRY = "retry"  # Retry failed records


@dataclass
class TransferConfig:
    """
    Configuration for data transfer.

    Attributes:
        batch_size: Number of records to transfer per batch
        validate: Whether to validate records after transfer
        on_error: Error handling policy
        max_retries: Maximum retries for failed records
        retry_delay_seconds: Delay between retries
        progress_callback: Optional callback for progress updates
    """

    batch_size: int = 100
    validate: bool = True
    on_error: TransferErrorPolicy = TransferErrorPolicy.SKIP
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    progress_callback: Callable[[int, int, int], None] | None = None

    def __post_init__(self):
        if isinstance(self.on_error, str):
            self.on_error = TransferErrorPolicy(self.on_error)


@dataclass
class TransferProgress:
    """
    Progress information for an ongoing transfer.

    Attributes:
        total: Total records to transfer
        transferred: Successfully transferred
        failed: Failed to transfer
        skipped: Skipped records
        current_batch: Current batch number
        started_at: Transfer start time
        estimated_remaining_seconds: Estimated time remaining
    """

    total: int = 0
    transferred: int = 0
    failed: int = 0
    skipped: int = 0
    current_batch: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_complete(self) -> bool:
        """Check if transfer is complete."""
        return self.transferred + self.failed + self.skipped >= self.total

    @property
    def success_rate(self) -> float:
        """Success rate as percentage."""
        if self.total == 0:
            return 100.0
        return (self.transferred / self.total) * 100

    @property
    def elapsed_seconds(self) -> float:
        """Elapsed time in seconds."""
        return (datetime.now(UTC) - self.started_at).total_seconds()

    @property
    def records_per_second(self) -> float:
        """Transfer rate in records per second."""
        elapsed = self.elapsed_seconds
        if elapsed == 0:
            return 0.0  # pragma: no cover
        return self.transferred / elapsed

    @property
    def estimated_remaining_seconds(self) -> float:
        """Estimated remaining time in seconds."""
        rate = self.records_per_second
        if rate == 0:
            return 0.0  # pragma: no cover
        remaining = self.total - self.transferred - self.failed - self.skipped
        return remaining / rate

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total": self.total,
            "transferred": self.transferred,
            "failed": self.failed,
            "skipped": self.skipped,
            "current_batch": self.current_batch,
            "success_rate": round(self.success_rate, 2),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "records_per_second": round(self.records_per_second, 2),
            "estimated_remaining_seconds": round(self.estimated_remaining_seconds, 2),
            "is_complete": self.is_complete,
        }


@dataclass
class TransferResult:
    """
    Result of a completed transfer operation.

    Attributes:
        transferred: Number of records successfully transferred
        failed: Number of records that failed
        skipped: Number of records skipped
        errors: List of error messages
        duration_seconds: Total transfer duration
        source: Source backend name
        target: Target backend name
    """

    transferred: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    source: str = ""
    target: str = ""

    @property
    def total_processed(self) -> int:
        """Total records processed."""
        return self.transferred + self.failed + self.skipped

    @property
    def success(self) -> bool:
        """Check if transfer was successful (no failures)."""
        return self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "transferred": self.transferred,
            "failed": self.failed,
            "skipped": self.skipped,
            "total_processed": self.total_processed,
            "success": self.success,
            "duration_seconds": round(self.duration_seconds, 2),
            "source": self.source,
            "target": self.target,
            "errors": self.errors[:10],  # First 10 errors only
        }


class TransferService:
    """
    Service for transferring data between storage backends.

    Supports saga storage and outbox storage transfers with:
    - Batch processing for memory efficiency
    - Progress tracking with callbacks
    - Error handling with configurable policies
    - Validation after transfer

    Example:
        >>> source = InMemorySagaStorage()
        >>> target = RedisSagaStorage("redis://localhost")
        >>>
        >>> service = TransferService(source, target)
        >>> result = await service.transfer_all()
        >>>
        >>> print(f"Transferred {result.transferred} sagas")
    """

    def __init__(
        self,
        source,
        target,
        config: TransferConfig | None = None,
    ):
        """
        Initialize transfer service.

        Args:
            source: Source storage (must implement export_all)
            target: Target storage (must implement import_record)
            config: Transfer configuration
        """
        self.source = source
        self.target = target
        self.config = config or TransferConfig()
        self._progress = TransferProgress()
        self._cancelled = False

    @property
    def progress(self) -> TransferProgress:
        """Get current transfer progress."""
        return self._progress

    def cancel(self) -> None:
        """Cancel the current transfer operation."""
        self._cancelled = True
        logger.info("Transfer cancellation requested")

    async def transfer_all(self) -> TransferResult:
        """
        Transfer all records from source to target.

        Returns:
            TransferResult with transfer statistics

        Raises:
            TransferError: If transfer fails (depending on error policy)
        """
        start_time = datetime.now(UTC)
        self._cancelled = False
        self._progress = TransferProgress(started_at=start_time)

        source_name = self.source.__class__.__name__
        target_name = self.target.__class__.__name__

        logger.info(f"Starting transfer: {source_name} -> {target_name}")

        result = TransferResult(source=source_name, target=target_name)

        try:
            # Get total count if possible
            if hasattr(self.source, "count"):
                try:
                    self._progress.total = await self.source.count()
                    logger.info(f"Total records to transfer: {self._progress.total}")
                except Exception:
                    pass  # Count not available

            # Transfer records
            batch = []
            batch_num = 0

            async for record in self._export_records():
                if self._cancelled:
                    logger.info("Transfer cancelled by user")
                    break

                batch.append(record)

                if len(batch) >= self.config.batch_size:
                    batch_num += 1
                    self._progress.current_batch = batch_num
                    await self._transfer_batch(batch, result)
                    batch = []

                    # Notify progress
                    self._notify_progress()

            # Transfer remaining records
            if batch and not self._cancelled:
                batch_num += 1
                self._progress.current_batch = batch_num
                await self._transfer_batch(batch, result)
                self._notify_progress()

        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            if self.config.on_error == TransferErrorPolicy.ABORT:
                raise TransferError(
                    message=f"Transfer failed: {e}",
                    source=source_name,
                    target=target_name,
                    records_transferred=result.transferred,
                    records_failed=result.failed,
                ) from e
            result.errors.append(str(e))  # pragma: no cover

        # Finalize result
        result.duration_seconds = (datetime.now(UTC) - start_time).total_seconds()

        logger.info(
            f"Transfer complete: {result.transferred} transferred, "
            f"{result.failed} failed, {result.skipped} skipped "
            f"in {result.duration_seconds:.2f}s"
        )

        return result

    async def _export_records(self) -> AsyncIterator[dict[str, Any]]:
        """Export records from source storage."""
        if not hasattr(self.source, "export_all"):
            raise TransferError(
                message=f"{self.source.__class__.__name__} does not support export",
                source=self.source.__class__.__name__,
            )

        async for record in self.source.export_all():
            yield record

    async def _transfer_batch(
        self,
        batch: list[dict[str, Any]],
        result: TransferResult,
    ) -> None:
        """Transfer a batch of records."""
        for record in batch:
            try:
                await self._transfer_record(record)
                result.transferred += 1
                self._progress.transferred += 1

            except Exception as e:
                error_msg = f"Failed to transfer record: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)

                if self.config.on_error == TransferErrorPolicy.ABORT:
                    raise
                if self.config.on_error == TransferErrorPolicy.SKIP:
                    result.skipped += 1
                    self._progress.skipped += 1
                elif self.config.on_error == TransferErrorPolicy.RETRY:
                    # Attempt retry
                    success = await self._retry_transfer(record)
                    if success:
                        result.transferred += 1
                        self._progress.transferred += 1
                    else:
                        result.failed += 1
                        self._progress.failed += 1
                else:
                    result.failed += 1
                    self._progress.failed += 1

    async def _transfer_record(self, record: dict[str, Any]) -> None:
        """Transfer a single record to target."""
        if not hasattr(self.target, "import_record"):
            raise TransferError(
                message=f"{self.target.__class__.__name__} does not support import",
                target=self.target.__class__.__name__,
            )

        await self.target.import_record(record)

        # Validate if configured
        if self.config.validate:
            await self._validate_record(record)

    async def _validate_record(self, record: dict[str, Any]) -> None:
        """Validate a transferred record exists in target."""
        # Get record ID
        record_id = record.get("saga_id") or record.get("event_id") or record.get("id")
        if not record_id:
            return

        # Try to load from target
        if hasattr(self.target, "load_saga_state"):
            loaded = await self.target.load_saga_state(record_id)
            if loaded is None:
                raise TransferError(
                    message=f"Validation failed: record {record_id} not found in target",
                    target=self.target.__class__.__name__,
                )
        elif hasattr(self.target, "get_by_id"):
            loaded = await self.target.get_by_id(record_id)
            if loaded is None:
                raise TransferError(
                    message=f"Validation failed: record {record_id} not found in target",
                    target=self.target.__class__.__name__,
                )

    async def _retry_transfer(self, record: dict[str, Any]) -> bool:
        """Retry transfer with configured retries."""
        for attempt in range(self.config.max_retries):
            try:
                await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
                await self._transfer_record(record)
                return True
            except Exception as e:
                logger.warning(f"Retry {attempt + 1}/{self.config.max_retries} failed: {e}")

        return False  # pragma: no cover

    def _notify_progress(self) -> None:
        """Notify progress callback if configured."""
        if self.config.progress_callback:
            try:
                self.config.progress_callback(
                    self._progress.transferred,
                    self._progress.failed,
                    self._progress.total,
                )
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")


async def transfer_data(
    source,
    target,
    batch_size: int = 100,
    validate: bool = True,
    on_error: str = "skip",
) -> TransferResult:
    """
    Convenience function for transferring data between storages.

    Args:
        source: Source storage
        target: Target storage
        batch_size: Records per batch
        validate: Validate after transfer
        on_error: Error policy ("abort", "skip", "retry")

    Returns:
        TransferResult with statistics
    """
    config = TransferConfig(
        batch_size=batch_size,
        validate=validate,
        on_error=TransferErrorPolicy(on_error),
    )

    service = TransferService(source, target, config)
    return await service.transfer_all()
