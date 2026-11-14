"""Configuration, progress and result models for the storage transfer service."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


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
            return 0.0
        return self.transferred / elapsed

    @property
    def estimated_remaining_seconds(self) -> float:
        """Estimated remaining time in seconds."""
        rate = self.records_per_second
        if rate == 0:
            return 0.0
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
        """A transfer is successful only when no records failed or were skipped."""
        return self.failed == 0 and self.skipped == 0

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
