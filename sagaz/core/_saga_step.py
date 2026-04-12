"""SagaStep dataclass - single step metadata for imperative Saga API."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from sagaz.core.types import SagaStepStatus


@dataclass
class SagaStep:
    """
    Represents a single step in a saga with full metadata.

    Extended in v1.3.0 with pivot support:
    - pivot: Mark step as point of no return
    - tainted: Step is locked from rollback (ancestor of completed pivot)

    Example:
        step = SagaStep(
            name="charge_payment",
            action=charge_fn,
            compensation=refund_fn,
            pivot=True  # Point of no return
        )
    """

    name: str
    action: Callable[..., Any]  # Forward action
    compensation: Callable[..., Any] | None = None  # Rollback action
    status: SagaStepStatus = field(default=SagaStepStatus.PENDING)
    result: Any | None = None
    error: Exception | None = None
    executed_at: datetime | None = None
    compensated_at: datetime | None = None
    idempotency_key: str = field(default_factory=lambda: str(uuid4()))
    retry_attempts: int = 0
    max_retries: int = 3
    timeout: float = 30.0  # seconds
    compensation_timeout: float = 30.0
    retry_count: int = 0

    # v1.3.0: Pivot support
    pivot: bool = False
    """True if this step is a point of no return (irreversible)."""

    tainted: bool = False
    """True if this step is locked from rollback (ancestor of completed pivot)."""

    def __hash__(self):
        return hash(self.idempotency_key)

    def can_compensate(self) -> bool:
        """
        Check if this step can be compensated.

        Returns:
            True if compensation is allowed (not tainted and has compensation)
        """
        return not self.tainted and self.compensation is not None

    def mark_tainted(self) -> None:
        """Mark this step as tainted (locked from rollback)."""
        self.tainted = True
        self.status = SagaStepStatus.TAINTED
