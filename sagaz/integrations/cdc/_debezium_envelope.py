"""Decode Debezium PostgreSQL change events for ``saga_outbox`` (ADR-011).

Debezium's ``JsonConverter`` writes each change as an envelope
(``before``/``after``/``source``/``op``/``ts_ms``), wrapped in
``{"schema": ..., "payload": ...}`` when ``schemas.enable`` is on. Column
values arrive as JSON: ``jsonb`` as a JSON string (``io.debezium.data.Json``),
``timestamptz`` as an ISO-8601 string (``ZonedTimestamp``) and ``uuid`` as a
string, all of which :func:`~sagaz.integrations.cdc._events.event_from_row`
accepts.

Only inserts (``c``) and snapshot reads (``r``) of pending rows describe events
to publish; updates, deletes, truncates, logical messages and tombstones are
skipped. Anything else raises :class:`CDCError`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.integrations.cdc._events import event_from_row, parse_timestamp
from sagaz.integrations.cdc._types import CDCError

#: Operations whose ``after`` image is an outbox event to publish.
CAPTURED_OPS = frozenset({"c", "r"})

#: Operations a source ignores: update, delete, truncate, logical message.
SKIPPED_OPS = frozenset({"u", "d", "t", "m"})


def unwrap(document: Any) -> Any:
    """The change envelope, without the ``{"schema", "payload"}`` wrapper if present."""
    if (
        isinstance(document, Mapping)
        and "schema" in document
        and "payload" in document
        and "op" not in document
    ):
        return document["payload"]
    return document


def load(value: bytes | str | None) -> Any:
    """Parse a Kafka record value as JSON (``None`` stays ``None``: a tombstone)."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except (UnicodeDecodeError, ValueError) as exc:
        msg = f"Debezium message is not JSON: {exc}"
        raise CDCError(msg) from exc


def commit_time(envelope: Mapping[str, Any]) -> datetime | None:
    """When the change was committed: ``source.ts_ms``, else the envelope's ``ts_ms``."""
    source = envelope.get("source")
    timestamp = source.get("ts_ms") if isinstance(source, Mapping) else None
    if timestamp in (None, 0):
        timestamp = envelope.get("ts_ms")
    return parse_timestamp(timestamp) if timestamp else None


def _captured_row(envelope: Any) -> Mapping[str, Any] | None:
    """The ``after`` image to publish, ``None`` for a change to skip."""
    if not isinstance(envelope, Mapping):
        msg = f"Debezium envelope is not an object: {envelope!r:.200}"
        raise CDCError(msg)
    op = envelope.get("op")
    if op in SKIPPED_OPS:
        return None
    if op not in CAPTURED_OPS:
        msg = f"not a Debezium change event (op={op!r})"
        raise CDCError(msg)
    after = envelope.get("after")
    if not isinstance(after, Mapping):
        msg = f"Debezium {op!r} event has no 'after' row"
        raise CDCError(msg)
    # A snapshot reads every row, including those already published.
    if op == "r" and (after.get("status") or OutboxStatus.PENDING.value) != "pending":
        return None
    return after


def decode_value(value: bytes | str | None) -> tuple[OutboxEvent, datetime | None] | None:
    """The outbox event and commit time a Debezium record value describes.

    Returns ``None`` for a record to skip (tombstone, update, delete, a
    snapshot row that is no longer pending) and raises :class:`CDCError` for
    one that cannot be decoded.
    """
    envelope = unwrap(load(value))
    if envelope is None:
        return None
    row = _captured_row(envelope)
    if row is None:
        return None
    try:
        event = event_from_row(row)
    except (ValueError, TypeError) as exc:  # bad status / counter values
        msg = f"cannot map outbox row: {exc}"
        raise CDCError(msg) from exc
    return event, commit_time(envelope)
