"""Read the unified saga log through PostgreSQL logical replication (#495, ADR-013).

:class:`SagaLogCDCReader` is a :class:`~sagaz.core.storage.saga_log.SagaLogReader`
that streams the inserts into ``saga_log_event`` from the write-ahead log,
instead of polling with a cursor. It hands an exporter the same
:class:`~sagaz.core.storage.saga_log.ExportBatch` objects::

    reader = SagaLogCDCReader(log, "postgresql://...", name="fluss")
    exporter = SagaLogExporter(reader, FlussSink("fluss:9123"))

Changes arrive in commit order, as soon as their transaction commits. The
position is the transaction's end LSN. ``acknowledge`` confirms it to the
server, so the replication slot keeps the WAL of everything not yet
acknowledged, and a restarted reader resumes after the last acknowledgement:
delivery is at least once.

The prerequisites of :class:`~sagaz.integrations.cdc.pg_logical.PgLogicalSource`
apply: ``wal_level = logical``, a role with ``REPLICATION``, and dropping the
slot of a reader retired for good, since an abandoned slot retains WAL forever.
The slot and publication are named after the reader (``sagaz_log_<name>``).

Only changes committed after the slot exists are streamed. The slot is created
on the first :meth:`~SagaLogCDCReader.read`, so start the reader before the
services write. For events already in the log, export them first with the
cursor reader (``SagaLogReader``) under another name.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sagaz.core.storage.saga_log._model import EventKind, ExportBatch, ExportedEvent, LogEvent
from sagaz.core.tenant import system_scope, tenant_scope
from sagaz.integrations.cdc._events import parse_timestamp
from sagaz.integrations.cdc._types import CDCError
from sagaz.integrations.cdc.pg_logical import PgLogicalSource


def log_event_from_row(row: Mapping[str, Any]) -> LogEvent:
    """A ``saga_log_event`` row from pgoutput (``{column: text}``) as a :class:`LogEvent`."""
    import json

    try:
        occurred_at = parse_timestamp(row["occurred_at"])
        if occurred_at is None:
            msg = "cannot map a saga_log_event row: occurred_at is empty"
            raise CDCError(msg)
        return LogEvent(
            transaction_id=row["transaction_id"],
            event_type=row["event_type"],
            kind=EventKind(row["kind"]),
            event_id=row["event_id"],
            source=row.get("source"),
            causation_id=row.get("causation_id"),
            payload=json.loads(row.get("payload") or "{}"),
            occurred_at=occurred_at,
            sequence=int(row["sequence"]),
            event_version=int(row.get("event_version") or 1),
            tenant_id=row.get("tenant_id") or "default",
        )
    except (KeyError, ValueError) as exc:
        msg = f"cannot map a saga_log_event row: {exc}"
        raise CDCError(msg) from exc


class SagaLogCDCReader:
    """Streams committed saga log events in commit order (a ``SagaLogReader``).

    Args:
        log: The PostgreSQL saga log, to read each transaction's coordination and flow.
        dsn: A connection string for logical replication (``REPLICATION`` role).
        name: The exporter's name; the slot and publication are ``sagaz_log_<name>``.
        batch_size: The most events per batch.
        idle_timeout: Seconds :meth:`read` waits for a change before returning an
            empty batch (the exporter then sleeps its poll interval).
        source: A ready :class:`PgLogicalSource` (tests or custom setup).
    """

    def __init__(
        self,
        log: Any,
        dsn: str,
        *,
        name: str = "cdc",
        batch_size: int = 500,
        idle_timeout: float = 0.5,
        source: Any = None,
    ) -> None:
        self.log = log
        self.name = name
        self.batch_size = batch_size
        self.idle_timeout = idle_timeout
        slot = f"sagaz_log_{name}".replace("-", "_").lower()
        self.source = source or PgLogicalSource(
            dsn,
            slot=slot,
            publication=f"{slot}_pub",
            table="saga_log_event",
            batch_size=batch_size,
            row_mapper=log_event_from_row,
        )
        self._position: str | None = None
        self._pending: ExportBatch | None = None  # read, not yet acknowledged
        self._started = False
        self._flows: dict[tuple[str, str], tuple[str | None, str | None]] = {}

    @property
    def position(self) -> str | None:
        """The end LSN of the last acknowledged batch, as text."""
        return self._position

    async def read(self, limit: int | None = None) -> ExportBatch:
        """The next committed events, or an empty batch after ``idle_timeout`` seconds.

        A batch is returned again until it is acknowledged: a stream, unlike a
        cursor, does not rewind, so a batch the sink failed to take would
        otherwise be skipped (and confirmed by a later acknowledgement).
        """
        if self._pending is not None:
            return self._pending
        if not self._started:
            # The publication needs saga_log_event: touching the log creates its
            # schema if no service has written to it yet.
            with system_scope():
                await self.log.read_committed(None, 1)
            await self.source.start()
            self._started = True
        changes = await self.source.poll(self.idle_timeout)
        if not changes:
            return ExportBatch([], self._position)
        events = [await self._exported(change.event) for change in changes]
        self._pending = ExportBatch(events, str(changes[-1].position))
        return self._pending

    async def acknowledge(self, batch: ExportBatch) -> None:
        """Confirm *batch* to the server: its WAL may go, and it is not read again."""
        if not batch.events or batch.position is None:
            return
        await self.source.ack(int(batch.position))
        self._position = batch.position
        if batch is self._pending:
            self._pending = None

    async def close(self) -> None:
        """Stop streaming (the slot keeps the unacknowledged changes)."""
        if self._started:
            await self.source.stop()
            self._started = False

    async def _exported(self, event: LogEvent) -> ExportedEvent:
        key = (event.tenant_id, event.transaction_id)
        if key not in self._flows:
            with tenant_scope(event.tenant_id):
                transaction = await self.log.get_transaction(event.transaction_id)
            if transaction is None:  # not cached: it may be written later
                return ExportedEvent(event)
            self._flows[key] = (str(transaction.coordination), transaction.flow)
            if len(self._flows) > 10_000:  # a bounded cache of recent transactions
                self._flows.pop(next(iter(self._flows)))
        coordination, flow = self._flows[key]
        return ExportedEvent(event, coordination, flow)
