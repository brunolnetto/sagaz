"""Outbox CDC through PostgreSQL's native logical replication (ADR-011, option 4).

:class:`PgLogicalSource` streams the rows inserted into ``saga_outbox`` from the
write-ahead log with the built-in ``pgoutput`` plugin. No Debezium or Kafka is
needed, only psycopg2 (``pip install 'sagaz[cdc]'``); psycopg 3 does not
implement the replication protocol.

Prerequisites
-------------
* ``wal_level = logical`` in ``postgresql.conf`` (requires a restart), and
  ``max_replication_slots`` / ``max_wal_senders`` of at least 1 each beyond
  what other replicas use.
* A role with the ``REPLICATION`` attribute (or a superuser), allowed to
  connect by ``pg_hba.conf`` (a logical replication connection is matched
  against the database name, like an ordinary one). Creating the publication
  needs ``CREATE`` on the database and ownership of the outbox table; with
  ``create=False`` an administrator creates them beforehand::

      CREATE PUBLICATION sagaz_outbox_pub FOR TABLE saga_outbox WITH (publish = 'insert');
      SELECT pg_create_logical_replication_slot('sagaz_outbox', 'pgoutput');

* **An abandoned slot retains WAL forever.** The server keeps every WAL
  segment the slot has not confirmed, so a slot whose consumer is gone fills
  the disk. Remove a slot that is no longer used with :meth:`drop_slot` (or
  ``pg_drop_replication_slot``), monitor ``pg_replication_slots``, and
  consider ``max_slot_wal_keep_size``.

Delivery
--------
Changes are grouped per transaction: every change of a transaction carries its
commit time (``committed_at``) and its end LSN (``position``), and a
transaction is never split across batches. The source confirms an LSN to the
server (``send_feedback(flush_lsn=...)``) only once it is passed to
:meth:`ack`; on restart the server resumes from the last confirmed LSN, so
unacknowledged changes are delivered again (at least once). Transactions
without outbox inserts are confirmed as soon as everything before them is.

A row that cannot be mapped to an :class:`OutboxEvent` is logged, counted in
:attr:`PgLogicalSource.skipped_rows` and skipped; acknowledging a later
position moves past it.

Multi-tenancy
-------------
Logical decoding reads the WAL, not the table, so row-level security does not
filter it: the stream carries the inserts of every tenant whatever role
replicates, and each event's ``tenant_id`` comes from its row. Treat the
replication role as privileged.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any

from sagaz.integrations.cdc._pg_setup import (
    ConnectionFactory,
    check_identifier,
    check_slot_name,
    default_connection_factory,
    drop,
    setup,
)
from sagaz.integrations.cdc._pg_stream import AckState, ReplicationStream
from sagaz.integrations.cdc._types import CDCChange, CDCError

logger = logging.getLogger("sagaz.integrations.cdc.pg_logical")

_END = object()  # posted by the reader thread when it stops without error


class PgLogicalSource:
    """A :class:`CDCSource` reading ``saga_outbox`` inserts from a replication slot.

    Args:
        dsn: libpq connection string of the database holding the outbox.
        slot: logical replication slot (``pgoutput``) to stream from.
        publication: publication that includes the outbox table.
        table: outbox table, optionally schema-qualified.
        create: create the publication and the slot at :meth:`start` if missing.
        batch_size: rows per batch; a batch closes once it reaches this size
            (it may exceed it to keep a transaction whole).
        max_batch_delay: seconds to wait for more rows after the first one. It is
            the floor of the CDC lag: 5 ms gave a p50 lag of ~8 ms at 1,000 events/s
            locally, against ~54 ms with 50 ms, without lowering throughput.
        feedback_interval: seconds between status updates to the server, which
            also keep the connection alive.
        queue_size: transactions buffered between the reader thread and the
            event loop; the thread waits when it is full.
        poll_interval: seconds the reader thread waits for data per iteration,
            which bounds how long :meth:`ack` and :meth:`stop` take to apply.
        connection_factory: ``factory(dsn, replication)`` returning a psycopg2
            connection (for tests or custom connection setup).
        row_mapper: Maps an inserted row (``{column: text}``) to the change's
            event; ``event_from_row`` (an outbox event) by default.
    """

    name = "pg_logical"

    def __init__(
        self,
        dsn: str,
        *,
        slot: str = "sagaz_outbox",
        publication: str = "sagaz_outbox_pub",
        table: str = "saga_outbox",
        create: bool = True,
        batch_size: int = 500,
        max_batch_delay: float = 0.005,
        feedback_interval: float = 10.0,
        queue_size: int = 64,
        poll_interval: float = 0.1,
        connection_factory: ConnectionFactory | None = None,
        row_mapper: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        if batch_size < 1 or queue_size < 1:
            msg = "batch_size and queue_size must be positive"
            raise ValueError(msg)
        self.dsn = dsn
        self.slot = check_slot_name(slot)
        self.publication = check_identifier(publication, "publication name")
        self.table = check_identifier(table, "table name", qualified=True)
        self.create = create
        self.batch_size = batch_size
        self.max_batch_delay = max_batch_delay
        self.feedback_interval = feedback_interval
        self.queue_size = queue_size
        self.poll_interval = poll_interval
        self._factory = connection_factory or default_connection_factory
        self._row_mapper = row_mapper
        self._acks = AckState()
        self._thread: threading.Thread | None = None
        self._stream: ReplicationStream | None = None
        self._queue: asyncio.Queue[Any] | None = None
        self._terminal: Any = None
        self._stopping = threading.Event()
        self._slots = threading.Semaphore(queue_size)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def skipped_rows(self) -> int:
        """Outbox rows skipped because they could not be mapped to an event."""
        return self._stream.skipped_rows if self._stream else 0

    async def start(self) -> None:
        """Create the publication and slot if asked, then start streaming."""
        if self._thread is not None:
            msg = "PgLogicalSource is already started"
            raise CDCError(msg)
        conn, cursor = await asyncio.to_thread(self._open)
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self.queue_size + 1)  # + the end marker
        self._terminal = None
        self._acks = AckState()
        stopping = self._stopping = threading.Event()
        self._slots = threading.Semaphore(self.queue_size)
        self._stream = ReplicationStream(
            cursor,
            table=self.table,
            emit=lambda changes: self._emit(loop, changes),
            acks=self._acks,
            stopping=stopping,
            poll_interval=self.poll_interval,
            **({"mapper": self._row_mapper} if self._row_mapper else {}),
        )
        self._thread = threading.Thread(
            target=self._run,
            args=(loop, conn, self._stream),
            name=f"sagaz-cdc-{self.slot}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Streaming %s from replication slot %s", self.table, self.slot)

    async def stop(self) -> None:
        """Stop the reader thread, confirm what was acknowledged and disconnect."""
        thread = self._thread
        if thread is None:
            return
        self._stopping.set()
        await asyncio.to_thread(thread.join)
        self._thread = None

    async def ack(self, position: Any) -> None:
        """Allow the server to discard WAL up to ``position`` (an end LSN)."""
        if position is not None:
            self._acks.ack(int(position))

    async def changes(self) -> AsyncIterator[list[CDCChange]]:
        """Batches of changes until :meth:`stop`; reader errors raise :class:`CDCError`."""
        if self._queue is None:
            msg = "PgLogicalSource.changes() called before start()"
            raise CDCError(msg)
        while True:
            item = await self._take(None)
            if not isinstance(item, list):
                self._finish(item)
                return
            yield await self._fill(item)

    async def poll(self, timeout: float) -> list[CDCChange]:
        """The next batch of changes, or ``[]`` if none arrives within *timeout* seconds.

        Unlike :meth:`changes`, waiting can time out without ending the stream.
        Raises :class:`CDCError` if the reader failed, and returns ``[]`` once stopped.
        """
        if self._queue is None:
            msg = "PgLogicalSource.poll() called before start()"
            raise CDCError(msg)
        try:
            item = await self._take(timeout)
        except TimeoutError:
            return []
        if not isinstance(item, list):
            self._finish(item)
            return []
        return await self._fill(item)

    async def drop_slot(self, *, drop_publication: bool = False) -> bool:
        """Drop the replication slot (and the publication); True if the slot existed.

        Run it when this source is retired for good: an unused slot retains WAL.
        """
        if self.running:
            msg = "stop the source before dropping its replication slot"
            raise CDCError(msg)
        publication = self.publication if drop_publication else None
        return await asyncio.to_thread(drop, self._factory, self.dsn, self.slot, publication)

    # -- reader thread ---------------------------------------------------------

    def _open(self) -> tuple[Any, Any]:
        try:
            if self.create:
                setup(self._factory, self.dsn, self.slot, self.publication, self.table)
            conn = self._factory(self.dsn, True)
        except CDCError:
            raise
        except Exception as exc:
            msg = f"cannot connect for logical replication: {exc}"
            raise CDCError(msg) from exc
        try:
            cursor = conn.cursor()
            cursor.start_replication(
                slot_name=self.slot,
                decode=False,
                options={"proto_version": "1", "publication_names": self.publication},
                status_interval=self.feedback_interval,
            )
        except Exception as exc:
            conn.close()
            msg = f"cannot start replication from slot {self.slot!r}: {exc}"
            raise CDCError(msg) from exc
        return conn, cursor

    def _run(self, loop: asyncio.AbstractEventLoop, conn: Any, stream: ReplicationStream) -> None:
        outcome: Any = _END
        try:
            stream.run()
        except Exception as exc:
            logger.exception("Logical replication stream from slot %s failed", self.slot)
            outcome = exc
        finally:
            with suppress(Exception):
                stream.cursor.close()
            with suppress(Exception):
                conn.close()
            self._post(loop, outcome)

    def _emit(self, loop: asyncio.AbstractEventLoop, changes: list[CDCChange]) -> bool:
        while not self._stopping.is_set():
            if self._slots.acquire(timeout=self.poll_interval):
                self._post(loop, changes)
                return True
        return False

    def _post(self, loop: asyncio.AbstractEventLoop, item: Any) -> None:
        queue = self._queue
        if queue is None:  # pragma: no cover - start() sets it before the thread runs
            return
        with suppress(RuntimeError):  # the loop is already closed
            loop.call_soon_threadsafe(queue.put_nowait, item)

    # -- event loop side -----------------------------------------------------

    async def _take(self, timeout: float | None) -> Any:
        if self._terminal is not None:
            return self._terminal
        assert self._queue is not None
        if timeout is None:
            item = await self._queue.get()
        else:
            item = await asyncio.wait_for(self._queue.get(), timeout)
        if isinstance(item, list):
            self._slots.release()
        else:
            self._terminal = item
        return item

    async def _fill(self, batch: list[CDCChange]) -> list[CDCChange]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.max_batch_delay
        while len(batch) < self.batch_size and self._terminal is None:
            try:
                item = await self._take(max(0.0, deadline - loop.time()))
            except TimeoutError:
                break
            if isinstance(item, list):
                batch.extend(item)
        return batch

    def _finish(self, item: Any) -> None:
        if isinstance(item, BaseException):
            msg = f"logical replication from slot {self.slot!r} failed: {item}"
            raise CDCError(msg) from item
