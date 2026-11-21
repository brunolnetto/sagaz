"""Bronze-layer extraction from sagaz saga storage.

Turns the records a saga storage backend exports (``export_all()``: one dict
per saga with its ``steps``) into the raw saga and step records that
:meth:`SagaAnalyticsPipeline.load_from_records` promotes to Silver. The storage
is only read, never written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from sagaz.choreography.tracker import RECORD_NAME as CHOREOGRAPHY_RECORD_NAME
from sagaz.versioning.registry import VERSION_RECORD_SAGA_NAME

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces import SagaStorage
    from sagaz.core.storage.saga_log import SagaLogStore
    from sagaz.core.storage.saga_log._model import Activity, Transaction


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


def _saga_source(storage: object) -> SagaStorage:
    """Accept a saga storage or a ``StorageManager`` (which exposes ``.saga``)."""
    if callable(getattr(storage, "export_all", None)):
        return cast("SagaStorage", storage)  # duck-typed: it has export_all()
    saga_storage = getattr(storage, "saga", None)
    if callable(getattr(saga_storage, "export_all", None)):
        return cast("SagaStorage", saga_storage)
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
    storage: object,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read every orchestrated saga (and its steps) from ``storage`` as Bronze records."""
    sagas, steps, _choreography = await read_storage(storage)
    return sagas, steps


async def read_storage(
    storage: object,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """One pass over ``storage``: orchestrated sagas, their steps, and the
    choreographed transactions a ``ChoreographyTracker`` saved (#459)."""
    saga_records: list[dict[str, Any]] = []
    step_records: list[dict[str, Any]] = []
    choreography: list[dict[str, Any]] = []
    async for saga in _saga_source(storage).export_all():
        if saga.get("saga_name") == VERSION_RECORD_SAGA_NAME:
            continue  # saga-version registrations, not saga runs
        if saga.get("saga_name") == CHOREOGRAPHY_RECORD_NAME:
            choreography.append(saga)  # not a saga of steps
            continue
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
    return saga_records, step_records, choreography


#: Activity statuses outside the step vocabulary, mapped as the classic layout
#: recorded them (a step whose compensation failed ended ``failed``).
_ACTIVITY_OUTCOME = {"compensation_failed": "failed"}


def _activity_record(transaction: Transaction, activity: Activity) -> dict[str, Any]:
    return {
        "saga_id": transaction.transaction_id,
        "saga_name": transaction.flow,
        "step_name": activity.name,
        "action": activity.name,
        "outcome": _ACTIVITY_OUTCOME.get(activity.status, activity.status),
        "duration_ms": activity.duration_ms,
        "attempt": activity.attempt,
        "executed_at": _timestamp(activity.ended_at or activity.started_at),
    }


async def _choreography_record(
    log: SagaLogStore, transaction: Transaction
) -> dict[str, Any] | None:
    """A choreographed transaction in the tracker-record shape the Silver layer reads."""
    from sagaz.choreography.tracker import RECORD_NAME, status_from_log

    status = await status_from_log(log, transaction.transaction_id)
    if status is None:
        return None
    if transaction.status in _CHOREOGRAPHY_STATUSES:
        status.status = transaction.status
    return {
        "saga_id": transaction.transaction_id,
        "saga_name": RECORD_NAME,
        "tenant_id": transaction.tenant_id,
        "context": status.to_dict(),
    }


#: The transaction row's status (kept by the tracker) wins over the projection,
#: which cannot tell completion without the completion event types.
_CHOREOGRAPHY_STATUSES = frozenset(
    {"executing", "completed", "compensating", "compensated", "failed"}
)


async def read_saga_log(
    log: SagaLogStore,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """One pass over a unified saga log (ADR-041): the same three record lists as
    :func:`read_storage`, for orchestrated and choreographed transactions alike."""
    from sagaz.core.tenant import system_scope, tenant_scope

    saga_records: list[dict[str, Any]] = []
    step_records: list[dict[str, Any]] = []
    choreography: list[dict[str, Any]] = []
    with system_scope():
        transactions = await log.list_transactions(limit=2**31 - 1)
    for transaction in transactions:
        with tenant_scope(transaction.tenant_id):
            if transaction.coordination == "choreographed":
                record = await _choreography_record(log, transaction)
                if record is not None:
                    choreography.append(record)
                continue
            saga_records.append(
                {
                    "saga_id": transaction.transaction_id,
                    "saga_name": transaction.flow,
                    "status": transaction.status,
                    "created_at": _timestamp(transaction.started_at),
                    "updated_at": _timestamp(transaction.ended_at or transaction.updated_at),
                }
            )
            step_records.extend(
                _activity_record(transaction, a)
                for a in await log.activities(transaction.transaction_id)
            )
    return saga_records, step_records, choreography
