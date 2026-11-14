"""Silver quality gate: accepted vocabularies, record validation and run stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sagaz.core.types import SagaStatus, SagaStepStatus

#: Saga statuses accepted by the Silver quality gate (lower-cased ``SagaStatus`` values).
SAGA_STATUSES: frozenset[str] = frozenset(status.value for status in SagaStatus)

#: Step outcomes accepted by the Silver quality gate. ``success`` is accepted as
#: an alias of ``completed`` for records produced outside sagaz.
STEP_OUTCOMES: frozenset[str] = frozenset(status.value for status in SagaStepStatus) | {"success"}


@dataclass
class PipelineStats:
    """Summary statistics produced after a pipeline run."""

    sagas_loaded: int = 0
    steps_loaded: int = 0
    facts_loaded: int = 0
    quality_errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.quality_errors) == 0


def validate_saga_record(rec: dict[str, Any]) -> str | None:
    for key in ("saga_id", "saga_name", "status"):
        if not rec.get(key):
            return f"Saga record missing required field '{key}': {rec!r}"
    if rec["status"] not in SAGA_STATUSES:
        return f"Saga record has unknown status {rec['status']!r}: {rec!r}"
    return None


def validate_step_record(rec: dict[str, Any]) -> str | None:
    for key in ("saga_id", "step_name", "outcome"):
        if not rec.get(key):
            return f"Step record missing required field '{key}': {rec!r}"
    if rec["outcome"] not in STEP_OUTCOMES:
        return f"Step record has unknown outcome {rec['outcome']!r}: {rec!r}"
    duration = rec.get("duration_ms", 0)
    if isinstance(duration, (int, float)) and duration < 0:
        return f"Step record has negative duration_ms={duration}: {rec!r}"
    return None
