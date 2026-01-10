# ============================================
# FILE: sagaz/core/replay.py
# ============================================

"""
Saga Replay & Time-Travel Support

Enables:
1. Snapshot capture at checkpoints
2. Replay sagas from any checkpoint with context override
3. Time-travel queries to retrieve historical state
4. Audit trail for compliance
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class SnapshotStrategy(str, Enum):
    """When to capture snapshots"""

    BEFORE_EACH_STEP = "before_each_step"
    AFTER_EACH_STEP = "after_each_step"
    ON_FAILURE = "on_failure"
    ON_COMPLETION = "on_completion"
    MANUAL = "manual"


class ReplayStatus(str, Enum):
    """Status of replay execution"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ReplayConfig:
    """Configuration for saga replay features"""

    enable_snapshots: bool = False
    snapshot_strategy: SnapshotStrategy = SnapshotStrategy.ON_FAILURE
    retention_days: int = 30  # Default 30 days retention
    compression: str | None = None  # Optional: "zstd", "gzip"
    max_snapshots_per_saga: int | None = None  # Limit snapshots

    def get_retention_until(self) -> datetime:
        """Calculate retention_until timestamp"""
        return datetime.now(UTC) + timedelta(days=self.retention_days)


@dataclass
class SagaSnapshot:
    """Immutable snapshot of saga state at a point in time"""

    snapshot_id: UUID
    saga_id: UUID
    saga_name: str
    step_name: str
    step_index: int

    # State
    status: str  # SagaStatus value
    context: dict[str, Any]
    completed_steps: list[str]

    # Metadata
    created_at: datetime
    retention_until: datetime | None = None

    # External references (for large payloads)
    external_refs: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        saga_id: UUID,
        saga_name: str,
        step_name: str,
        step_index: int,
        status: str,
        context: dict[str, Any],
        completed_steps: list[str],
        retention_until: datetime | None = None,
    ) -> "SagaSnapshot":
        """Factory method to create a new snapshot"""
        return cls(
            snapshot_id=uuid4(),
            saga_id=saga_id,
            saga_name=saga_name,
            step_name=step_name,
            step_index=step_index,
            status=status,
            context=context.copy(),  # Defensive copy
            completed_steps=completed_steps.copy(),
            created_at=datetime.now(UTC),
            retention_until=retention_until,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to dictionary for storage"""
        return {
            "snapshot_id": str(self.snapshot_id),
            "saga_id": str(self.saga_id),
            "saga_name": self.saga_name,
            "step_name": self.step_name,
            "step_index": self.step_index,
            "status": self.status,
            "context": self.context,
            "completed_steps": self.completed_steps,
            "external_refs": self.external_refs,
            "created_at": self.created_at.isoformat(),
            "retention_until": self.retention_until.isoformat()
            if self.retention_until
            else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SagaSnapshot":
        """Reconstruct snapshot from dictionary"""
        return cls(
            snapshot_id=UUID(data["snapshot_id"]),
            saga_id=UUID(data["saga_id"]),
            saga_name=data["saga_name"],
            step_name=data["step_name"],
            step_index=data["step_index"],
            status=data["status"],
            context=data["context"],
            completed_steps=data["completed_steps"],
            external_refs=data.get("external_refs", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            retention_until=datetime.fromisoformat(data["retention_until"])
            if data.get("retention_until")
            else None,
        )


@dataclass
class ReplayRequest:
    """Request to replay a saga from a checkpoint"""

    original_saga_id: UUID
    checkpoint_step: str
    context_override: dict[str, Any] | None = None
    initiated_by: str = "system"
    dry_run: bool = False  # If True, don't execute, just validate

    def merge_context(self, original_context: dict[str, Any]) -> dict[str, Any]:
        """Merge context override with original context"""
        if not self.context_override:
            return original_context.copy()

        merged = original_context.copy()
        merged.update(self.context_override)
        return merged


@dataclass
class ReplayResult:
    """Result of a replay operation"""

    replay_id: UUID
    original_saga_id: UUID
    new_saga_id: UUID
    checkpoint_step: str
    replay_status: ReplayStatus
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def mark_success(self) -> None:
        """Mark replay as successful"""
        self.replay_status = ReplayStatus.SUCCESS
        self.completed_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        """Mark replay as failed"""
        self.replay_status = ReplayStatus.FAILED
        self.error_message = error
        self.completed_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "replay_id": str(self.replay_id),
            "original_saga_id": str(self.original_saga_id),
            "new_saga_id": str(self.new_saga_id),
            "checkpoint_step": self.checkpoint_step,
            "replay_status": self.replay_status.value,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class SnapshotCaptureError(Exception):
    """Raised when snapshot capture fails"""


class ReplayError(Exception):
    """Raised when replay operation fails"""


class SnapshotNotFoundError(Exception):
    """Raised when requested snapshot doesn't exist"""
