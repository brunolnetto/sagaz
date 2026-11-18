"""A minimal pgoutput (protocol 1) encoder for building test messages.

It follows "Logical Replication Message Formats" in the PostgreSQL manual; the
decoder tests also check it against bytes captured from a PostgreSQL 16 server.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sagaz.integrations.cdc._pgoutput import PG_EPOCH, UNCHANGED_TOAST

TEXT_OID = 25
UUID_OID = 2950
JSONB_OID = 3802
INT4_OID = 23
TIMESTAMPTZ_OID = 1184

#: The saga_outbox columns (name, type oid) in table order.
OUTBOX_COLUMNS: list[tuple[str, int]] = [
    ("event_id", UUID_OID),
    ("saga_id", TEXT_OID),
    ("aggregate_type", TEXT_OID),
    ("aggregate_id", TEXT_OID),
    ("event_type", TEXT_OID),
    ("payload", JSONB_OID),
    ("headers", JSONB_OID),
    ("status", TEXT_OID),
    ("created_at", TIMESTAMPTZ_OID),
    ("retry_count", INT4_OID),
    ("replay_count", INT4_OID),
    ("routing_key", TEXT_OID),
    ("partition_key", TEXT_OID),
    ("tenant_id", TEXT_OID),
]


def micros(when: datetime) -> int:
    delta = when - PG_EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _cstr(text: str) -> bytes:
    return text.encode() + b"\x00"


def begin(final_lsn: int, committed: datetime, xid: int = 1) -> bytes:
    return b"B" + struct.pack("!QqI", final_lsn, micros(committed), xid)


def commit(commit_lsn: int, end_lsn: int, committed: datetime, flags: int = 0) -> bytes:
    return b"C" + struct.pack("!bQQq", flags, commit_lsn, end_lsn, micros(committed))


def relation(
    relation_id: int,
    namespace: str,
    name: str,
    columns: Sequence[tuple[str, int]],
    identity: str = "d",
) -> bytes:
    body = struct.pack("!I", relation_id) + _cstr(namespace) + _cstr(name) + identity.encode()
    body += struct.pack("!h", len(columns))
    for index, (column, oid) in enumerate(columns):
        body += struct.pack("!b", 1 if index == 0 else 0) + _cstr(column)
        body += struct.pack("!Ii", oid, -1)
    return b"R" + body


def tuple_data(values: Iterable[Any]) -> bytes:
    values = list(values)
    body = struct.pack("!h", len(values))
    for value in values:
        if value is None:
            body += b"n"
        elif value is UNCHANGED_TOAST:
            body += b"u"
        else:
            raw = value if isinstance(value, bytes) else str(value).encode()
            body += b"t" + struct.pack("!i", len(raw)) + raw
    return body


def insert(relation_id: int, values: Iterable[Any]) -> bytes:
    return b"I" + struct.pack("!I", relation_id) + b"N" + tuple_data(values)


def update(relation_id: int, values: Iterable[Any], old: Iterable[Any] | None = None) -> bytes:
    body = b"U" + struct.pack("!I", relation_id)
    if old is not None:
        body += b"O" + tuple_data(old)
    return body + b"N" + tuple_data(values)


def delete(relation_id: int, key: Iterable[Any]) -> bytes:
    return b"D" + struct.pack("!I", relation_id) + b"K" + tuple_data(key)


def truncate(relation_ids: Sequence[int]) -> bytes:
    body = struct.pack("!ib", len(relation_ids), 0)
    return b"T" + body + b"".join(struct.pack("!I", rid) for rid in relation_ids)


def outbox_relation(relation_id: int = 16384, namespace: str = "public") -> bytes:
    return relation(relation_id, namespace, "saga_outbox", OUTBOX_COLUMNS)


def outbox_values(**row: Any) -> list[Any]:
    """Text values of an outbox row in column order (defaults for a valid row)."""
    defaults = {
        "event_id": "4cbae389-8832-4041-a576-fecaf7c477f3",
        "saga_id": "saga-1",
        "aggregate_type": "saga",
        "aggregate_id": "saga-1",
        "event_type": "OrderCreated",
        "payload": '{"order": 1}',
        "headers": "{}",
        "status": "pending",
        "created_at": "2026-11-14 20:00:00.123+00",
        "retry_count": "0",
        "replay_count": "0",
        "routing_key": None,
        "partition_key": None,
        "tenant_id": "default",
    }
    defaults.update(row)
    return [defaults[name] for name, _ in OUTBOX_COLUMNS]
