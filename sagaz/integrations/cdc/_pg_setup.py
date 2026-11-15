"""Connections, publication and replication slot management for :mod:`pg_logical`.

All functions are blocking (psycopg2); the source runs them in a thread.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import closing
from typing import Any

from sagaz.integrations.cdc._types import CDCError

#: ``factory(dsn, replication)`` returns a psycopg2-like connection; with
#: ``replication=True`` it must be a logical replication connection.
ConnectionFactory = Callable[[str, bool], Any]

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_SLOT = re.compile(r"^[a-z0-9_]{1,63}$")


def check_identifier(value: str, what: str, *, qualified: bool = False) -> str:
    """``value`` if it is a plain (optionally schema-qualified) SQL identifier."""
    parts = value.split(".") if qualified else [value]
    if len(parts) > 2 or not all(_IDENTIFIER.match(part) for part in parts):
        msg = f"invalid {what} {value!r}: use letters, digits and underscores"
        raise ValueError(msg)
    return value


def check_slot_name(value: str) -> str:
    if not _SLOT.match(value):
        msg = f"invalid replication slot name {value!r}: use a-z, 0-9 and '_' (max 63)"
        raise ValueError(msg)
    return value


def default_connection_factory(dsn: str, replication: bool) -> Any:
    """A psycopg2 connection: logical replication or ordinary autocommit."""
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:  # pragma: no cover - depends on the environment
        msg = "PostgreSQL logical replication requires psycopg2: pip install 'sagaz[cdc]'"
        raise CDCError(msg) from exc
    if replication:
        return psycopg2.connect(
            dsn, connection_factory=psycopg2.extras.LogicalReplicationConnection
        )
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    return conn


def _exists(cur: Any, query: str, value: str) -> bool:
    cur.execute(query, (value,))
    return cur.fetchone() is not None


_PUBLICATION_EXISTS = "SELECT 1 FROM pg_publication WHERE pubname = %s"
_SLOT_EXISTS = "SELECT 1 FROM pg_replication_slots WHERE slot_name = %s"


def _create_idempotently(cur: Any, exists: Callable[[], bool], create: str, what: str) -> bool:
    """Run ``create`` unless ``exists()``; True if it was created here.

    A concurrent creator (another worker starting at the same time) makes the
    statement fail; that is fine as long as the object exists afterwards.
    """
    if exists():
        return False
    try:
        cur.execute(create)
    except Exception as exc:
        if exists():
            return False
        msg = f"cannot create {what}: {exc}"
        raise CDCError(msg) from exc
    return True


def ensure_publication(cur: Any, publication: str, table: str) -> bool:
    """Create ``publication`` for inserts into ``table`` unless it exists."""
    return _create_idempotently(
        cur,
        lambda: _exists(cur, _PUBLICATION_EXISTS, publication),
        f"CREATE PUBLICATION {publication} FOR TABLE {table} WITH (publish = 'insert')",
        f"publication {publication!r}",
    )


def ensure_slot(cur: Any, slot: str) -> bool:
    """Create the logical replication ``slot`` (``pgoutput``) unless it exists."""
    return _create_idempotently(
        cur,
        lambda: _exists(cur, _SLOT_EXISTS, slot),
        f"SELECT pg_create_logical_replication_slot('{slot}', 'pgoutput')",
        f"replication slot {slot!r}",
    )


def setup(factory: ConnectionFactory, dsn: str, slot: str, publication: str, table: str) -> None:
    """Create the publication, then the slot (pgoutput needs the publication first)."""
    with closing(factory(dsn, False)) as conn, closing(conn.cursor()) as cur:
        ensure_publication(cur, publication, table)
        ensure_slot(cur, slot)


def drop(factory: ConnectionFactory, dsn: str, slot: str, publication: str | None = None) -> bool:
    """Drop ``slot`` (and ``publication`` if given); True if the slot existed."""
    with closing(factory(dsn, False)) as conn, closing(conn.cursor()) as cur:
        existed = _exists(cur, _SLOT_EXISTS, slot)
        if existed:
            cur.execute("SELECT pg_drop_replication_slot(%s)", (slot,))
        if publication is not None:
            cur.execute(f"DROP PUBLICATION IF EXISTS {publication}")
        return existed
