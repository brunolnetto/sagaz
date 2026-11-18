"""Bronze-layer extraction from sagaz saga storage.

Turns the records a saga storage backend exports (``export_all()``: one dict
per saga with its ``steps``) into the raw saga and step records that
:meth:`SagaAnalyticsPipeline.load_from_records` promotes to Silver. The storage
is only read, never written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sagaz.versioning.registry import VERSION_RECORD_SAGA_NAME


def _value(raw: Any) -> Any:
    return raw.value if isinstance(raw, Enum) else raw


def _timestamp(raw: Any) -> datetime | None:
    """Normalise datetimes and ISO strings to naive UTC (DuckDB ``TIMESTAMP``)."""
    if raw is None or raw == "":
        return None
    parsed = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _saga_source(storage: Any) -> Any:
    """Accept a saga storage or a ``StorageManager`` (which exposes ``.saga``)."""
    if callable(getattr(storage, "export_all", None)):
        return storage
    saga_storage = getattr(storage, "saga", None)
    if callable(getattr(saga_storage, "export_all", None)):
        return saga_storage
    msg = f"{type(storage).__name__} does not expose export_all(); pass a saga storage"
    raise TypeError(msg)


def _step_record(saga: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    return {
        "saga_id": saga["saga_id"],
        "saga_name": saga.get("saga_name"),
        "step_name": step.get("name"),
        "action": step.get("name"),
        "outcome": _value(step.get("status")),
        "duration_ms": step.get("duration_ms"),
        "attempt": int(step.get("retry_count") or 0) + 1,
        "executed_at": _timestamp(step.get("executed_at")),
    }


async def bronze_records_from_storage(
    storage: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read every saga (and its steps) from ``storage`` as Bronze records."""
    saga_records: list[dict[str, Any]] = []
    step_records: list[dict[str, Any]] = []
    async for saga in _saga_source(storage).export_all():
        if saga.get("saga_name") == VERSION_RECORD_SAGA_NAME:
            continue  # saga-version registrations, not saga runs
        saga_records.append(
            {
                "saga_id": saga["saga_id"],
                "saga_name": saga.get("saga_name"),
                "status": _value(saga.get("status")),
                "created_at": _timestamp(saga.get("created_at")),
                "updated_at": _timestamp(saga.get("updated_at")),
            }
        )
        step_records.extend(_step_record(saga, step) for step in saga.get("steps") or [])
    return saga_records, step_records
