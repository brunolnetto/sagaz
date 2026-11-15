"""The blocking side of :mod:`pg_logical`: reads the replication stream in a thread.

:class:`ReplicationStream` decodes pgoutput messages, groups the outbox inserts
of each transaction into :class:`CDCChange` objects positioned at the
transaction's end LSN, hands every transaction to ``emit`` and reports to the
server only what :class:`AckState` says has been acknowledged.
"""

from __future__ import annotations

import logging
import select
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sagaz.integrations.cdc._events import event_from_row
from sagaz.integrations.cdc._pgoutput import (
    Begin,
    Commit,
    Insert,
    PgOutputDecoder,
    Relation,
    format_lsn,
)
from sagaz.integrations.cdc._types import CDCChange, CDCError

logger = logging.getLogger("sagaz.integrations.cdc.pg_logical")


@dataclass
class AckState:
    """Which LSNs may be confirmed to the server, shared by both threads.

    ``delivered`` is the position of the last transaction handed to the
    consumer, ``acked`` the highest position it acknowledged. ``idle`` is the
    end of the latest transaction after ``delivered`` that carried no outbox
    change; it may be confirmed once everything delivered is acknowledged, so
    a quiet outbox does not hold WAL back.
    """

    acked: int = 0
    delivered: int = 0
    idle: int = 0
    sent: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def ack(self, lsn: int) -> None:
        with self.lock:
            self.acked = max(self.acked, lsn)

    def deliver(self, lsn: int) -> None:
        with self.lock:
            self.delivered = max(self.delivered, lsn)

    def skip(self, lsn: int) -> None:
        with self.lock:
            self.idle = max(self.idle, lsn)

    def target(self) -> int:
        """The LSN that may be reported as flushed."""
        with self.lock:
            if self.acked >= self.delivered and self.idle > self.acked:
                return self.idle
            return self.acked


def matches_table(relation: Relation, table: str) -> bool:
    """Whether ``relation`` is ``table`` (``name`` or ``schema.name``)."""
    schema, _, name = table.rpartition(".")
    return relation.name == name and (not schema or relation.namespace == schema)


#: ``emit(changes)`` queues one transaction's changes, blocking while the queue
#: is full; it returns False if the stream is stopping.
Emit = Callable[[list[CDCChange]], bool]


class ReplicationStream:
    """Reads a started psycopg2 replication cursor until ``stopping`` is set."""

    def __init__(
        self,
        cursor: Any,
        *,
        table: str,
        emit: Emit,
        acks: AckState,
        stopping: threading.Event,
        poll_interval: float = 0.1,
    ) -> None:
        self.cursor = cursor
        self.table = table
        self.emit = emit
        self.acks = acks
        self.stopping = stopping
        self.poll_interval = poll_interval
        self.decoder = PgOutputDecoder()
        self.skipped_rows = 0
        self._commit_time: datetime | None = None
        self._events: list[Any] = []

    def run(self) -> None:
        """Stream until stopped; send the final feedback on the way out."""
        while not self.stopping.is_set():
            self.send_feedback()
            message = self.cursor.read_message()
            if message is None:
                select.select([self.cursor], [], [], self.poll_interval)
                continue
            if not self.handle(message.payload):
                break
        self.send_feedback()

    def send_feedback(self) -> None:
        """Confirm the acknowledged LSN to the server if it advanced."""
        target = self.acks.target()
        if target > self.acks.sent:
            self.cursor.send_feedback(write_lsn=target, flush_lsn=target, force=True)
            self.acks.sent = target
            logger.debug("Confirmed WAL up to %s", format_lsn(target))

    def handle(self, payload: bytes) -> bool:
        """Process one message; False if ``emit`` reported the stream is stopping."""
        message = self.decoder.decode(payload)
        if isinstance(message, Begin):
            self._commit_time = message.commit_time
            self._events = []
        elif isinstance(message, Insert):
            self._insert(message)
        elif isinstance(message, Commit):
            return self._commit(message)
        return True

    def _insert(self, insert: Insert) -> None:
        relation = self.decoder.relation(insert.relation_id)
        if not matches_table(relation, self.table):
            return
        try:
            event = event_from_row(self.decoder.row(insert))
        except (CDCError, ValueError, TypeError) as exc:
            self.skipped_rows += 1
            logger.warning("Skipping an outbox row CDC cannot map: %s", exc)
            return
        self._events.append(event)

    def _commit(self, commit: Commit) -> bool:
        committed_at = self._commit_time or commit.commit_time
        changes = [CDCChange(event, committed_at, commit.end_lsn) for event in self._events]
        self._events = []
        self._commit_time = None
        if not changes:
            self.acks.skip(commit.end_lsn)
            return True
        # Recorded before the hand-off so a fast ack can never be overtaken.
        self.acks.deliver(commit.end_lsn)
        return self.emit(changes)
