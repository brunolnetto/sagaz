"""Ordered, durable reading of the saga log for exporters (ADR-013, #480).

A :class:`SagaLogReader` returns committed events of every tenant in an order
that a later commit can never be inserted before, starting after the position
its exporter acknowledged last. The position is stored in the log's database
(``saga_export_cursor``), so an exporter that crashes resumes where it was and
delivers at least once::

    reader = SagaLogReader(log, "fluss")
    while batch := await reader.read():
        await sink.write(batch.events)
        await reader.acknowledge(batch)

The order is per backend: the rowid in SQLite (one writer at a time), and in
PostgreSQL the writing transaction's id, read only below the oldest
transaction still running, so a long transaction that commits late is not
skipped.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from sagaz.core._poller import Poller
from sagaz.core.tenant import system_scope

if TYPE_CHECKING:
    from sagaz.core.storage.saga_log._base import SagaLogStore
    from sagaz.core.storage.saga_log._model import ExportBatch, ExportedEvent

logger = logging.getLogger(__name__)


class SagaLogReader:
    """Reads a saga log for the exporter *name*, from its last acknowledged position."""

    def __init__(self, log: SagaLogStore, name: str, *, batch_size: int = 500) -> None:
        self.log = log
        self.name = name
        self.batch_size = batch_size
        self._position: str | None = None
        self._loaded = False

    @property
    def position(self) -> str | None:
        return self._position

    async def read(self, limit: int | None = None) -> ExportBatch:
        """The next committed events (empty when the exporter is caught up)."""
        with system_scope():
            if not self._loaded:
                self._position = await self.log.load_cursor(self.name)
                self._loaded = True
            return await self.log.read_committed(self._position, limit or self.batch_size)

    async def acknowledge(self, batch: ExportBatch) -> None:
        """Persist *batch*'s position: its events are never read again."""
        if not batch.events or batch.position is None:
            return
        with system_scope():
            await self.log.save_cursor(self.name, batch.position)
        self._position = batch.position


@runtime_checkable
class ExportSink(Protocol):
    """Where an exporter writes committed log events.

    ``write`` returns only once the destination has accepted every event, and
    must be idempotent: after a crash, events are written again. Key the
    destination on ``(tenant_id, transaction_id, sequence)``.
    """

    async def write(self, events: list[ExportedEvent]) -> None: ...

    async def close(self) -> None: ...


class SagaLogExporter:
    """Moves a saga log to a sink, at least once.

    The reader's position is acknowledged only after the sink accepted the
    batch, so a crash or an unreachable sink delays events and never drops
    them. In the background (:meth:`start`) it polls every ``poll_interval``
    seconds and, while the sink fails, backs off up to ``max_backoff``.

    Args:
        reader: The log reader; its name identifies this exporter's cursor.
        sink: The destination.
        poll_interval: Seconds between polls once caught up.
        max_backoff: Longest wait between attempts while the sink fails.
    """

    def __init__(
        self,
        reader: SagaLogReader,
        sink: ExportSink,
        *,
        poll_interval: float = 0.5,
        max_backoff: float = 30.0,
    ) -> None:
        self.reader = reader
        self.sink = sink
        self.poll_interval = poll_interval
        self.max_backoff = max_backoff
        self.exported = 0
        self.errors = 0
        self.last_error: str | None = None
        self.last_occurred_at: datetime | None = None
        self._delay = poll_interval
        self._poller = Poller(
            self._tick, lambda: self._delay, name=f"saga-log-exporter-{reader.name}"
        )

    async def export(self) -> int:
        """Export everything committed so far; return how many events.

        A sink failure propagates, after the batches before it were
        acknowledged: calling again resumes with the failed batch.
        """
        total = 0
        while batch := await self.reader.read():
            await self.sink.write(batch.events)
            await self.reader.acknowledge(batch)
            total += len(batch.events)
            self.exported += len(batch.events)
            self.last_occurred_at = batch.events[-1].event.occurred_at
        return total

    def metrics(self) -> dict[str, Any]:
        """Exported events, errors and lag (seconds since the last exported event occurred)."""
        lag = (
            None
            if self.last_occurred_at is None
            else (datetime.now(UTC) - self.last_occurred_at).total_seconds()
        )
        return {
            "exporter": self.reader.name,
            "exported": self.exported,
            "errors": self.errors,
            "last_error": self.last_error,
            "lag_seconds": lag,
        }

    @property
    def running(self) -> bool:
        return self._poller.running

    async def start(self) -> None:
        self._poller.start()

    async def stop(self) -> None:
        """Stop after the batch in progress (an overrunning one is cancelled and
        exported again later: its position was not acknowledged)."""
        await self._poller.stop()

    async def close(self) -> None:
        """Stop, and close the sink (and the reader, if it holds a stream)."""
        await self.stop()
        await self.sink.close()
        close_reader = getattr(self.reader, "close", None)
        if callable(close_reader):
            await close_reader()

    async def _tick(self) -> None:
        """One background round; a failure backs off up to ``max_backoff``."""
        try:
            await self.export()
            self._delay = self.poll_interval
        except Exception as exc:  # the sink or the log is down: retry later
            self.errors += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._delay = min(max(self._delay * 2, self.poll_interval), self.max_backoff)
            logger.warning(
                "Exporter %s failed (%s); retrying in %.1fs",
                self.reader.name,
                self.last_error,
                self._delay,
            )
