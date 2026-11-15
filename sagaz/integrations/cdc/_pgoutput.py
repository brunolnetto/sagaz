"""Decoder for PostgreSQL's ``pgoutput`` logical replication messages (protocol 1).

Pure functions over bytes, no I/O. Each replication message (the payload of
one ``XLogData``) is decoded on its own; :class:`PgOutputDecoder` keeps the
``Relation`` messages it has seen, because ``Insert`` messages refer to their
table by relation id only.

Reference: "Logical Replication Message Formats" in the PostgreSQL manual
(protocol-logicalrep-message-formats). Only what the outbox needs is decoded in
full: Begin, Commit, Relation and Insert. Update, Delete, Truncate, Origin,
Type, logical decoding messages and unknown types decode to :class:`Skipped`.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.integrations.cdc._types import CDCError

#: PostgreSQL timestamps count microseconds from 2000-01-01 UTC.
PG_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


class PgOutputError(CDCError):
    """A replication message is truncated or malformed."""


class _Unchanged:
    """Marker for an unchanged TOASTed value (tuple kind ``'u'``)."""

    def __repr__(self) -> str:
        return "UNCHANGED_TOAST"


#: The value of a column the message does not carry (unchanged TOAST datum).
UNCHANGED_TOAST = _Unchanged()


@dataclass(frozen=True)
class Column:
    name: str
    type_oid: int
    flags: int = 0
    type_modifier: int = -1


@dataclass(frozen=True)
class Relation:
    relation_id: int
    namespace: str
    name: str
    replica_identity: str
    columns: tuple[Column, ...]

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}.{self.name}"


@dataclass(frozen=True)
class Begin:
    final_lsn: int
    commit_time: datetime
    xid: int


@dataclass(frozen=True)
class Commit:
    flags: int
    commit_lsn: int
    end_lsn: int
    commit_time: datetime


@dataclass(frozen=True)
class Insert:
    relation_id: int
    values: tuple[Any, ...]


@dataclass(frozen=True)
class Skipped:
    """A message the outbox does not need (update, delete, truncate, ...)."""

    kind: str


Message = Begin | Commit | Relation | Insert | Skipped


def pg_timestamp(micros: int) -> datetime:
    """The datetime of a PostgreSQL timestamp (µs since 2000-01-01 UTC)."""
    return PG_EPOCH + timedelta(microseconds=micros)


def format_lsn(lsn: int) -> str:
    """An LSN as PostgreSQL prints it, e.g. ``0/16B3748``."""
    return f"{lsn >> 32:X}/{lsn & 0xFFFFFFFF:X}"


@dataclass
class _Reader:
    data: bytes
    pos: int = 0

    def _take(self, size: int) -> bytes:
        end = self.pos + size
        if end > len(self.data):
            msg = f"pgoutput message truncated at byte {self.pos} (needs {size} more)"
            raise PgOutputError(msg)
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def _unpack(self, fmt: str) -> Any:
        return struct.unpack(fmt, self._take(struct.calcsize(fmt)))[0]

    def byte(self) -> str:
        return self._take(1).decode("ascii", errors="replace")

    def int8(self) -> int:
        return int(self._unpack("!b"))

    def int16(self) -> int:
        return int(self._unpack("!h"))

    def int32(self) -> int:
        return int(self._unpack("!i"))

    def uint32(self) -> int:
        return int(self._unpack("!I"))

    def int64(self) -> int:
        return int(self._unpack("!q"))

    def uint64(self) -> int:
        return int(self._unpack("!Q"))

    def string(self) -> str:
        end = self.data.find(b"\x00", self.pos)
        if end < 0:
            msg = f"pgoutput string at byte {self.pos} is not terminated"
            raise PgOutputError(msg)
        text = self.data[self.pos : end].decode("utf-8")
        self.pos = end + 1
        return text


def _begin(reader: _Reader) -> Begin:
    final_lsn = reader.uint64()
    commit_time = pg_timestamp(reader.int64())
    return Begin(final_lsn=final_lsn, commit_time=commit_time, xid=reader.uint32())


def _commit(reader: _Reader) -> Commit:
    flags = reader.int8()
    commit_lsn = reader.uint64()
    end_lsn = reader.uint64()
    commit_time = pg_timestamp(reader.int64())
    return Commit(flags=flags, commit_lsn=commit_lsn, end_lsn=end_lsn, commit_time=commit_time)


def _column(reader: _Reader) -> Column:
    flags = reader.int8()
    name = reader.string()
    type_oid = reader.uint32()
    return Column(name=name, type_oid=type_oid, flags=flags, type_modifier=reader.int32())


def _relation(reader: _Reader) -> Relation:
    relation_id = reader.uint32()
    namespace = reader.string() or "pg_catalog"  # an empty namespace means pg_catalog
    name = reader.string()
    replica_identity = reader.byte()
    columns = tuple(_column(reader) for _ in range(reader.int16()))
    return Relation(relation_id, namespace, name, replica_identity, columns)


def _value(reader: _Reader) -> Any:
    kind = reader.byte()
    if kind == "n":
        return None
    if kind == "u":
        return UNCHANGED_TOAST
    if kind in ("t", "b"):  # text, or binary (protocol 2+ with ``binary``)
        raw = reader._take(reader.int32())
        return raw.decode("utf-8") if kind == "t" else raw
    msg = f"unknown pgoutput tuple column kind {kind!r}"
    raise PgOutputError(msg)


def decode_tuple(reader: _Reader) -> tuple[Any, ...]:
    """Decode a ``TupleData`` block: text, ``None`` or :data:`UNCHANGED_TOAST` per column."""
    return tuple(_value(reader) for _ in range(reader.int16()))


def _insert(reader: _Reader) -> Insert:
    relation_id = reader.uint32()
    marker = reader.byte()
    if marker != "N":
        msg = f"pgoutput insert expects a new tuple ('N'), got {marker!r}"
        raise PgOutputError(msg)
    return Insert(relation_id=relation_id, values=decode_tuple(reader))


_DECODERS: dict[str, Callable[[_Reader], Message]] = {
    "B": _begin,
    "C": _commit,
    "R": _relation,
    "I": _insert,
}

#: Message types that are valid but irrelevant to the outbox.
SKIPPED_KINDS = {
    "U": "update",
    "D": "delete",
    "T": "truncate",
    "O": "origin",
    "Y": "type",
    "M": "message",
}


def decode_message(data: bytes) -> Message:
    """Decode one pgoutput message (the payload of an ``XLogData``)."""
    if not data:
        msg = "empty pgoutput message"
        raise PgOutputError(msg)
    reader = _Reader(bytes(data))
    kind = reader.byte()
    decoder = _DECODERS.get(kind)
    if decoder is None:
        return Skipped(SKIPPED_KINDS.get(kind, f"unknown:{kind}"))
    return decoder(reader)


@dataclass
class PgOutputDecoder:
    """Decodes a pgoutput stream, remembering the relations it has announced."""

    relations: dict[int, Relation] = field(default_factory=dict)

    def decode(self, data: bytes) -> Message:
        message = decode_message(data)
        if isinstance(message, Relation):
            self.relations[message.relation_id] = message
        return message

    def relation(self, relation_id: int) -> Relation:
        try:
            return self.relations[relation_id]
        except KeyError:
            msg = f"pgoutput insert for relation {relation_id} before its Relation message"
            raise PgOutputError(msg) from None

    def row(self, insert: Insert) -> dict[str, Any]:
        """The inserted row as ``{column: text or None}``.

        Unchanged TOAST values (which an insert does not normally carry) are
        left out, so the row mapping treats them as absent.
        """
        relation = self.relation(insert.relation_id)
        if len(relation.columns) != len(insert.values):
            msg = (
                f"insert into {relation.qualified_name} has {len(insert.values)} values "
                f"for {len(relation.columns)} columns"
            )
            raise PgOutputError(msg)
        return {
            column.name: value
            for column, value in zip(relation.columns, insert.values, strict=True)
            if value is not UNCHANGED_TOAST
        }
