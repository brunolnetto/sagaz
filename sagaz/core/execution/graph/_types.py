"""
Type definitions for the saga execution graph.

Defines enumerations, dataclasses, and context objects used by
the execution graph and compensation machinery.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class CompensationType(Enum):
    """Type of compensation action."""

    MECHANICAL = "mechanical"
    """Pure rollback - undo exactly what was done (e.g., delete created record)"""

    SEMANTIC = "semantic"
    """Business logic compensation - may differ from exact reverse (e.g., issue refund credit)"""

    MANUAL = "manual"
    """Requires human intervention (e.g., review by support team)"""


class CompensationFailureStrategy(Enum):
    """Strategy for handling compensation failures."""

    FAIL_FAST = "fail_fast"
    """Stop immediately on first failure, don't attempt remaining compensations"""

    CONTINUE_ON_ERROR = "continue_on_error"
    """Continue with remaining compensations, collect all errors"""

    RETRY_THEN_CONTINUE = "retry_then_continue"
    """Retry failed compensation (using max_retries), then continue if still fails"""

    SKIP_DEPENDENTS = "skip_dependents"
    """Skip compensations that depend on the failed one, continue with independent"""


@dataclass
class CompensationResult:
    """Result of compensation execution.

    Attributes:
        success: Whether all compensations succeeded
        executed: List of step IDs that were compensated successfully
        failed: List of step IDs that failed during compensation
        skipped: List of step IDs that were skipped due to dependency failure
        results: Dictionary mapping step IDs to their compensation return values
        errors: Dictionary mapping failed step IDs to their exceptions
        execution_time_ms: Total execution time in milliseconds
    """

    success: bool
    executed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, Exception] = field(default_factory=dict)
    execution_time_ms: float = 0.0


@dataclass
class SagaCompensationContext:
    """
    Context specifically for compensation execution.

    Separates compensation concerns from forward execution context,
    facilitating blob storage and snapshots.

    Attributes:
        saga_id: Unique identifier for the saga instance
        step_id: Current compensation step being executed
        original_context: Snapshot of the saga context at failure time
        compensation_results: Results from previously executed compensations
        metadata: Additional metadata (timestamps, retry counts, etc.)
    """

    saga_id: str
    step_id: str
    original_context: dict[str, Any] = field(default_factory=dict)
    compensation_results: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def get_result(self, step_id: str, default: Any = None) -> Any:
        """Get result from a previously executed compensation."""
        return self.compensation_results.get(step_id, default)

    def set_result(self, step_id: str, result: Any) -> None:
        """Store result from a compensation."""
        self.compensation_results[step_id] = result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "saga_id": self.saga_id,
            "step_id": self.step_id,
            "original_context": self.original_context,
            "compensation_results": self.compensation_results,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SagaCompensationContext":
        """Restore from dictionary (e.g., from blob storage)."""
        created_at_str = data.get("created_at")
        return cls(
            saga_id=data["saga_id"],
            step_id=data["step_id"],
            original_context=data.get("original_context", {}),
            compensation_results=data.get("compensation_results", {}),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(created_at_str) if created_at_str else datetime.now(),
        )


@dataclass
class CompensationNode:
    """
    Node in compensation dependency graph.

    Represents a single compensation action with its dependencies
    and metadata for execution.

    Attributes:
        step_id: Unique identifier for this step
        compensation_fn: Async function to execute compensation
        depends_on: List of step IDs that must be compensated first
        compensation_type: Type of compensation (mechanical, semantic, manual)
        description: Human-readable description for logging/monitoring
        max_retries: Maximum retry attempts for this compensation
        timeout_seconds: Timeout for compensation execution
    """

    step_id: str
    compensation_fn: Callable[..., Awaitable[Any]]
    depends_on: list[str] = field(default_factory=list)
    compensation_type: CompensationType = CompensationType.MECHANICAL
    description: str | None = None
    max_retries: int = 3
    timeout_seconds: float = 30.0
