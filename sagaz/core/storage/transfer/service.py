"""
Storage Transfer Service - Data Migration Between Backends.

Provides utilities for migrating saga and outbox data between
different storage backends (e.g., memory -> Redis, PostgreSQL -> Redis).

Usage:
    >>> from sagaz.core.storage.transfer import TransferService, TransferConfig
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
from datetime import UTC, datetime
from typing import Any

from sagaz.core.storage.core import TransferError
from sagaz.core.storage.transfer._models import (
    TransferConfig,
    TransferErrorPolicy,
    TransferProgress,
    TransferResult,
)
from sagaz.core.storage.transfer._validation import _TransferValidationMixin

logger = logging.getLogger(__name__)


class TransferService(_TransferValidationMixin):
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
            result.errors.append(str(e))

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

    async def _retry_transfer(self, record: dict[str, Any]) -> bool:
        """Retry transfer with configured retries."""
        for attempt in range(self.config.max_retries):
            try:
                await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
                await self._transfer_record(record)
                return True
            except Exception as e:
                logger.warning(f"Retry {attempt + 1}/{self.config.max_retries} failed: {e}")

        return False

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
    progress_callback: Callable[[int, int, int], None] | None = None,
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
        progress_callback=progress_callback,
    )

    service = TransferService(source, target, config)
    return await service.transfer_all()
