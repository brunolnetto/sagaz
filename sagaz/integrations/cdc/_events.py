"""Map captured ``saga_outbox`` rows to :class:`OutboxEvent` (ADR-011).

Sources deliver row values in different shapes: PostgreSQL's ``pgoutput``
sends every column as text, Debezium sends JSON with timestamps as ISO strings
or epoch microseconds. :func:`event_from_row` accepts all of them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.tenant import DEFAULT_TENANT
from sagaz.integrations.cdc._types import CDCError

#: Columns an outbox row must carry to become an event.
REQUIRED = ("event_id", "saga_id", "event_type", "payload")

# A time followed by an offset without minutes: "...T20:00:00.123+00".
_HOUR_ONLY_OFFSET = re.compile(r"T\d\d:\d\d(:\d\d(\.\d+)?)?[+-]\d\d$")


def parse_timestamp(value: Any) -> datetime | None:
    """A timezone-aware datetime from text, ISO 8601, epoch micros/millis or a datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        # Debezium MicroTimestamp (µs) or a millisecond epoch.
        seconds = value / 1_000_000 if abs(value) >= 10**14 else value / 1_000
        return datetime.fromtimestamp(seconds, UTC)
    text = str(value).strip().replace(" ", "T", 1)
    if _HOUR_ONLY_OFFSET.search(text):
        text += ":00"  # PostgreSQL prints whole-hour offsets as '+00'
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        msg = f"unrecognised timestamp {value!r}"
        raise CDCError(msg) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _json(value: Any, column: str) -> Any:
    if value is None or isinstance(value, dict | list):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        msg = f"column {column!r} is not JSON: {value!r}"
        raise CDCError(msg) from exc


def _int(value: Any, default: int = 0) -> int:
    return default if value in (None, "") else int(value)


def event_from_row(row: Mapping[str, Any]) -> OutboxEvent:
    """Build the :class:`OutboxEvent` an inserted ``saga_outbox`` row describes."""
    missing = [column for column in REQUIRED if row.get(column) in (None, "")]
    if missing:
        msg = f"outbox row lacks {', '.join(missing)}"
        raise CDCError(msg)
    status = row.get("status") or OutboxStatus.PENDING.value
    return OutboxEvent(
        event_id=str(row["event_id"]),
        saga_id=str(row["saga_id"]),
        event_type=str(row["event_type"]),
        payload=_json(row["payload"], "payload"),
        aggregate_type=row.get("aggregate_type") or "saga",
        aggregate_id=row.get("aggregate_id"),
        headers=_json(row.get("headers"), "headers") or {},
        status=OutboxStatus(status),
        created_at=parse_timestamp(row.get("created_at")) or datetime.now(UTC),
        retry_count=_int(row.get("retry_count")),
        replay_count=_int(row.get("replay_count")),
        routing_key=row.get("routing_key"),
        partition_key=row.get("partition_key"),
        tenant_id=row.get("tenant_id") or DEFAULT_TENANT,
    )
