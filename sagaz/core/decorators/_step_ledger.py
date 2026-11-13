"""Per-run record of step outcomes, persisted with the saga state."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from sagaz.core.types import SagaStepStatus


class StepLedger:
    """Tracks each step's status, timing and error for one saga run.

    The records use the step shape the storage backends already persist
    (``name``, ``status``, ``error``, ``executed_at``, ``compensated_at``,
    ``retry_count``) plus ``started_at`` and ``duration_ms``, which analytics
    uses for latency percentiles.
    """

    def __init__(self, step_order: list[str]) -> None:
        self._order = step_order
        self._records: dict[str, dict[str, Any]] = {}
        self._clocks: dict[str, float] = {}

    def started(self, step_id: str) -> None:
        self._clocks[step_id] = time.perf_counter()
        self._records[step_id] = {
            "name": step_id,
            "status": SagaStepStatus.EXECUTING.value,
            "started_at": datetime.now(UTC),
            "error": None,
            "executed_at": None,
            "compensated_at": None,
            "duration_ms": None,
            "retry_count": 0,
        }

    def finished(self, step_id: str, error: BaseException | None = None) -> None:
        record = self._records.get(step_id)
        if record is None:
            return
        elapsed = time.perf_counter() - self._clocks.pop(step_id, time.perf_counter())
        record["executed_at"] = datetime.now(UTC)
        record["duration_ms"] = round(elapsed * 1000, 3)
        if error is None:
            record["status"] = SagaStepStatus.COMPLETED.value
        else:
            record["status"] = SagaStepStatus.FAILED.value
            record["error"] = str(error) or type(error).__name__

    def compensated(self, step_id: str) -> None:
        record = self._records.get(step_id)
        if record is not None:
            record["status"] = SagaStepStatus.COMPENSATED.value
            record["compensated_at"] = datetime.now(UTC)

    def snapshot(self) -> list[dict[str, Any]]:
        """Records of the steps that ran, in the saga's step order."""
        return [dict(self._records[name]) for name in self._order if name in self._records]
