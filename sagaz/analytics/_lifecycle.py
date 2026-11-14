"""Lifecycle accumulation: ``fact_saga_lifecycle`` snapshots from Silver records."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_lifecycle_records(
    saga_records: list[dict[str, Any]],
    step_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate step events into ``FactSagaLifecycle`` accumulating snapshots.

    Each record represents one saga with milestone timestamps and
    aggregated metrics derived from its step executions.
    """
    saga_index = {r["saga_id"]: r for r in saga_records}
    step_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in step_records:
        step_groups[rec["saga_id"]].append(rec)

    return [
        build_single_lifecycle_record(saga_id, saga, step_groups.get(saga_id, []))
        for saga_id, saga in saga_index.items()
    ]


def build_single_lifecycle_record(
    saga_id: str,
    saga: dict[str, Any],
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one ``FactSagaLifecycle`` record from a saga and its steps."""
    exec_times = [s["executed_at"] for s in steps if s.get("executed_at")]
    status = saga.get("status", "")
    completed_at = saga.get("updated_at") if status == "completed" else None
    rolled_back_at = saga.get("updated_at") if status in ("rolled_back", "compensating") else None
    return {
        "saga_id": saga_id,
        "created_at": saga.get("created_at"),
        "started_at": min(exec_times) if exec_times else None,
        "completed_at": completed_at,
        "rolled_back_at": rolled_back_at,
        "total_duration_ms": sum(float(s.get("duration_ms") or 0) for s in steps),
        "step_count": len(steps),
        "compensation_count": sum(1 for s in steps if s.get("outcome") == "compensated"),
    }
