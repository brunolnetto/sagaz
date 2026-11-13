"""Deterministic, JSON-safe canonical form for storage records.

Shared by the transfer service (per-record import validation) and the
migration facade (order-independent storage checksums), so both compare
records across backends with exactly the same normalization rules:

- aware datetimes are converted to UTC, naive ones are kept as-is;
- timestamp fields stored as ISO strings are parsed and normalized the same way;
- enums and other ``.value`` holders collapse to their value;
- objects exposing ``to_dict()`` are recursively normalized;
- tuples become lists, sets become deterministically sorted lists.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

_TIMESTAMP_FIELDS = frozenset({"created_at", "claimed_at", "sent_at", "dead_letter_at"})


def _canonical_datetime(value: datetime) -> str:
    """Normalize aware datetimes to UTC; preserve naive datetimes."""
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value
    return normalized.isoformat()


def _canonical_timestamp_string(value: str) -> str:
    """Normalize parseable timestamp strings while preserving invalid values."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value

    return _canonical_datetime(parsed)


def _canonical_sort_key(value: Any) -> str:
    """Produce the deterministic ordering key used for normalized sets."""
    return json.dumps(value, sort_keys=True, default=str)


def _canonicalize_mapping(value: dict[Any, Any]) -> dict[str, Any]:
    """Normalize mapping keys and recursively normalize their values."""
    return {str(key): canonical_value(item, str(key)) for key, item in value.items()}


def _canonicalize_sequence(value: list[Any] | tuple[Any, ...]) -> list[Any]:
    """Normalize lists and tuples into recursively normalized lists."""
    return [canonical_value(item) for item in value]


def _canonicalize_set(value: set[Any]) -> list[Any]:
    """Normalize and deterministically order set elements."""
    normalized = [canonical_value(item) for item in value]
    return sorted(normalized, key=_canonical_sort_key)


def _canonicalize_scalar(value: Any, field_name: str | None = None) -> Any:
    """Normalize datetime, timestamp, and scalar-like objects."""
    if isinstance(value, datetime):
        return _canonical_datetime(value)

    if field_name in _TIMESTAMP_FIELDS and isinstance(value, str):
        return _canonical_timestamp_string(value)

    if hasattr(value, "isoformat"):
        return value.isoformat()

    if hasattr(value, "value"):
        return value.value

    return value


def canonical_value(value: Any, field_name: str | None = None) -> Any:
    """Convert storage values to a JSON-safe, deterministic representation."""
    if hasattr(value, "to_dict"):
        return canonical_value(value.to_dict())

    if isinstance(value, dict):
        return _canonicalize_mapping(value)

    if isinstance(value, (list, tuple)):
        return _canonicalize_sequence(value)

    if isinstance(value, set):
        return _canonicalize_set(value)

    return _canonicalize_scalar(value, field_name)
