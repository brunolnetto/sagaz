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

from typing import TYPE_CHECKING

from sagaz.core.tenant import system_scope

if TYPE_CHECKING:
    from sagaz.core.storage.saga_log._base import SagaLogStore
    from sagaz.core.storage.saga_log._model import ExportBatch


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
