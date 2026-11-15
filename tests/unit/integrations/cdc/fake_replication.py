"""An in-memory stand-in for a PostgreSQL server speaking pgoutput to psycopg2.

:class:`FakeServer` keeps committed transactions as pgoutput messages and one
confirmed LSN per slot. A replication cursor streams the transactions that end
after its slot's confirmed LSN, and ``send_feedback`` advances it, like a real
logical replication slot.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from tests.unit.integrations.cdc import pgoutput_encoder as enc

COMMITTED = datetime(2026, 11, 14, 20, 0, 0, tzinfo=UTC)
OUTBOX_RELID = 16384
OTHER_RELID = 16400


@dataclass
class Txn:
    end_lsn: int
    messages: list[bytes]


@dataclass
class Message:
    payload: bytes
    data_start: int = 0


@dataclass
class FakeServer:
    publications: set[str] = field(default_factory=set)
    slots: dict[str, int] = field(default_factory=dict)
    txns: list[Txn] = field(default_factory=list)
    feedback: list[int] = field(default_factory=list)
    statements: list[str] = field(default_factory=list)
    connect_error: Exception | None = None
    start_error: Exception | None = None
    read_error: Exception | None = None
    create_error: Exception | None = None
    connections: list[Any] = field(default_factory=list)
    lsn: int = 0x1000

    def connect(self, dsn: str, replication: bool) -> FakeConnection:
        if self.connect_error is not None:
            raise self.connect_error
        conn = FakeConnection(self, replication)
        self.connections.append(conn)
        return conn

    def commit(
        self,
        *rows: list[Any],
        relation_id: int = OUTBOX_RELID,
        committed: datetime = COMMITTED,
        extra: list[bytes] | None = None,
    ) -> int:
        """Commit a transaction inserting ``rows`` (value lists); its end LSN."""
        start = self.lsn
        self.lsn += 0x100
        messages = [enc.begin(start, committed, xid=len(self.txns) + 1)]
        messages.append(enc.outbox_relation(OUTBOX_RELID))
        messages.append(enc.relation(OTHER_RELID, "public", "other", [("id", enc.INT4_OID)]))
        messages += [enc.insert(relation_id, row) for row in rows]
        messages += extra or []
        messages.append(enc.commit(start, self.lsn, committed))
        self.txns.append(Txn(self.lsn, messages))
        return self.lsn

    def insert_outbox(self, *saga_ids: str, **row: Any) -> int:
        return self.commit(*[enc.outbox_values(saga_id=s, **row) for s in saga_ids])

    @property
    def open_connections(self) -> int:
        return sum(1 for conn in self.connections if not conn.closed)


class FakeConnection:
    def __init__(self, server: FakeServer, replication: bool) -> None:
        self.server = server
        self.replication = replication
        self.closed = False
        self.autocommit = True

    def cursor(self) -> Any:
        if self.replication:
            return FakeReplicationCursor(self.server)
        return FakeCursor(self.server)

    def close(self) -> None:
        self.closed = True


class FakeCursor:
    """Answers the catalog queries and DDL issued by ``_pg_setup``."""

    def __init__(self, server: FakeServer) -> None:
        self.server = server
        self._row: tuple[int] | None = None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        server = self.server
        server.statements.append(sql)
        self._row = None
        if "FROM pg_publication" in sql:
            self._row = (1,) if params[0] in server.publications else None
        elif "FROM pg_replication_slots" in sql:
            self._row = (1,) if params[0] in server.slots else None
        elif sql.startswith(("CREATE PUBLICATION", "SELECT pg_create_logical")):
            self._create(sql)
        elif "pg_drop_replication_slot" in sql:
            del server.slots[params[0]]
        elif sql.startswith("DROP PUBLICATION"):
            server.publications.discard(sql.split()[-1])

    def _create(self, sql: str) -> None:
        if self.server.create_error is not None:
            raise self.server.create_error
        if sql.startswith("CREATE PUBLICATION"):
            self.server.publications.add(sql.split()[2])
        else:
            self.server.slots[sql.split("'")[1]] = 0

    def fetchone(self) -> tuple[int] | None:
        return self._row

    def close(self) -> None:
        pass


class FakeReplicationCursor:
    def __init__(self, server: FakeServer) -> None:
        self.server = server
        self.started: dict[str, Any] = {}
        self._read_fd, self._write_fd = os.pipe()
        self._queue: list[bytes] = []
        self._next_txn = 0
        self.closed = False
        self.lock = threading.Lock()

    def start_replication(self, **kwargs: Any) -> None:
        if self.server.start_error is not None:
            raise self.server.start_error
        slot = kwargs["slot_name"]
        if slot not in self.server.slots:
            msg = f'replication slot "{slot}" does not exist'
            raise RuntimeError(msg)
        self.started = kwargs
        confirmed = self.server.slots[slot]
        self._next_txn = next(
            (i for i, txn in enumerate(self.server.txns) if txn.end_lsn > confirmed),
            len(self.server.txns),
        )

    def fileno(self) -> int:
        return self._read_fd

    def read_message(self) -> Message | None:
        if self.server.read_error is not None:
            raise self.server.read_error
        if not self._queue and self._next_txn < len(self.server.txns):
            self._queue = list(self.server.txns[self._next_txn].messages)
            self._next_txn += 1
        if not self._queue:
            return None
        return Message(self._queue.pop(0))

    def send_feedback(
        self,
        write_lsn: int = 0,
        flush_lsn: int = 0,
        apply_lsn: int = 0,
        reply: bool = False,
        force: bool = False,
    ) -> None:
        slot = self.started["slot_name"]
        self.server.feedback.append(flush_lsn)
        self.server.slots[slot] = max(self.server.slots[slot], flush_lsn)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            os.close(self._read_fd)
            os.close(self._write_fd)
