"""
IcebergTieringJob — periodically flushes historical saga events from the
in-memory / short-term store to an Apache Iceberg table in object storage
(S3 / MinIO).

Iceberg provides time-travel queries, schema evolution, and cost-efficient
storage of immutable historical data.

Usage::

    job = IcebergTieringJob(
        catalog_url="http://rest-catalog:8181",
        warehouse="s3://sagaz-warehouse",
        table="sagaz.saga_history",
    )
    await job.start()
    # … collect events via tier_event() …
    await job.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IcebergRecord:
    """A single record to be written to the Iceberg table."""

    saga_id: str
    saga_name: str
    status: str
    started_at: str
    completed_at: str | None
    duration_ms: float
    step_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "saga_id": self.saga_id,
            "saga_name": self.saga_name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "step_count": self.step_count,
            "metadata": self.metadata,
        }


class IcebergTieringJob:
    """
    Buffers saga completion records and periodically writes them to Iceberg.

    Parameters
    ----------
    catalog_url:
        URL of the Iceberg REST catalog.
    warehouse:
        Object-storage URI for the warehouse (e.g. ``s3://my-bucket``).
    table:
        Iceberg table identifier (``database.table``).
    flush_interval:
        Seconds between background flush cycles.
    batch_size:
        Maximum records per Iceberg write batch.
    """

    def __init__(
        self,
        catalog_url: str = "http://localhost:8181",
        warehouse: str = "s3://sagaz-warehouse",
        table: str = "sagaz.saga_history",
        flush_interval: float = 60.0,
        batch_size: int = 500,
    ) -> None:
        self._catalog_url = catalog_url.rstrip("/")
        self._warehouse = warehouse
        self._table = table
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._buffer: list[IcebergRecord] = []
        self._running = False
        self._tier_task: asyncio.Task | None = None
        self._records_written: int = 0
        self._errors: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tier_task = asyncio.create_task(self._tiering_loop())
        logger.info("IcebergTieringJob started — table=%s", self._table)

    async def stop(self) -> None:
        self._running = False
        if self._tier_task:
            self._tier_task.cancel()
            try:
                await self._tier_task
            except asyncio.CancelledError:
                pass
            self._tier_task = None
        # Final flush
        await self._do_tier()
        logger.info("IcebergTieringJob stopped — %d records written", self._records_written)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def tier_event(self, record: IcebergRecord) -> None:
        """Buffer *record* for the next tiering cycle."""
        self._buffer.append(record)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _tiering_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._flush_interval)
            await self._do_tier()

    async def _do_tier(self) -> None:
        if not self._buffer:
            return
        batch = self._buffer[: self._batch_size]
        self._buffer = self._buffer[self._batch_size :]
        try:
            await self._write_batch(batch)
            self._records_written += len(batch)
        except Exception as exc:
            logger.warning("Iceberg write failed: %s", exc)
            self._errors += 1

    async def _write_batch(self, records: list[IcebergRecord]) -> None:
        """
        Write *records* to the Iceberg REST catalog.
        Override this method in tests to avoid real HTTP calls.
        """
        import urllib.request

        payload = json.dumps({"table": self._table, "records": [r.to_dict() for r in records]})
        req = urllib.request.Request(
            f"{self._catalog_url}/v1/namespaces/default/tables/{self._table}/rows",
            data=payload.encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        return {
            "records_written": self._records_written,
            "errors": self._errors,
            "buffer_size": len(self._buffer),
        }

    @property
    def is_running(self) -> bool:
        return self._running
