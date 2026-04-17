"""
FlussAnalyticsListener — emits saga lifecycle events to an Apache Fluss table
for real-time streaming analytics.

Apache Fluss is a streaming storage engine designed for sub-second analytics.
This listener bridges the sagaz event bus to a Fluss table via its REST / gRPC
interface.  In environments where Fluss is not available, events are buffered
in memory and metrics are still tracked.

Usage::

    listener = FlussAnalyticsListener(
        fluss_url="http://fluss:9000",
        table="sagaz.saga_events",
    )
    await listener.start()
    # … attach to orchestrator …
    await listener.on_saga_completed(saga_id="s1", duration_ms=123)
    await listener.stop()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FlussEvent:
    saga_id: str
    event_type: str
    duration_ms: float = 0.0
    status: str = ""
    step_name: str = ""
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_row(self) -> dict[str, Any]:
        return {
            "saga_id": self.saga_id,
            "event_type": self.event_type,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "step_name": self.step_name,
            "ts": self.ts.isoformat(),
        }


class FlussAnalyticsListener:
    """
    Listens to saga lifecycle events and forwards them to a Fluss table.

    Parameters
    ----------
    fluss_url:
        HTTP endpoint of the Fluss REST gateway.
    table:
        Fully-qualified Fluss table name (database.table).
    buffer_size:
        Maximum number of events to buffer before flushing.
    flush_interval:
        Seconds between background flushes.
    """

    def __init__(
        self,
        fluss_url: str = "http://localhost:9000",
        table: str = "sagaz.saga_events",
        buffer_size: int = 100,
        flush_interval: float = 1.0,
    ) -> None:
        self._url = fluss_url.rstrip("/")
        self._table = table
        self._buffer_size = buffer_size
        self._flush_interval = flush_interval
        self._buffer: list[FlussEvent] = []
        self._running = False
        self._flush_task: asyncio.Task | None = None
        self._one_off_flush: asyncio.Task | None = None
        self._events_written: int = 0
        self._errors: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("FlussAnalyticsListener started — table=%s", self._table)

    async def stop(self) -> None:
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final flush
        await self._do_flush()
        logger.info("FlussAnalyticsListener stopped — wrote %d events", self._events_written)

    # ------------------------------------------------------------------
    # Event callbacks
    # ------------------------------------------------------------------

    async def on_saga_started(self, saga_id: str) -> None:
        self._emit(FlussEvent(saga_id=saga_id, event_type="saga_started"))

    async def on_saga_completed(self, saga_id: str, duration_ms: float = 0.0) -> None:
        self._emit(
            FlussEvent(
                saga_id=saga_id,
                event_type="saga_completed",
                duration_ms=duration_ms,
                status="completed",
            )
        )

    async def on_saga_failed(self, saga_id: str, error: str = "") -> None:
        self._emit(FlussEvent(saga_id=saga_id, event_type="saga_failed", status="failed"))

    async def on_saga_rolled_back(self, saga_id: str) -> None:
        self._emit(FlussEvent(saga_id=saga_id, event_type="saga_rolled_back", status="rolled_back"))

    async def on_step_executed(
        self, saga_id: str, step_name: str, duration_ms: float = 0.0
    ) -> None:
        self._emit(
            FlussEvent(
                saga_id=saga_id,
                event_type="step_executed",
                step_name=step_name,
                duration_ms=duration_ms,
            )
        )

    async def on_step_failed(self, saga_id: str, step_name: str) -> None:
        self._emit(
            FlussEvent(
                saga_id=saga_id, event_type="step_failed", step_name=step_name, status="failed"
            )
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit(self, event: FlussEvent) -> None:
        self._buffer.append(event)
        if len(self._buffer) >= self._buffer_size:
            self._one_off_flush = asyncio.ensure_future(self._do_flush())

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._flush_interval)
            await self._do_flush()

    async def _do_flush(self) -> None:
        if not self._buffer:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        try:
            await self._write_rows(batch)
            self._events_written += len(batch)
        except Exception as exc:
            logger.warning("Fluss flush failed: %s", exc)
            self._errors += 1
            # Re-queue on failure (best-effort)
            self._buffer[:0] = batch[: self._buffer_size // 2]

    async def _write_rows(self, rows: list[FlussEvent]) -> None:
        """Send *rows* to the Fluss REST endpoint.  Override in tests."""
        import json
        import urllib.request

        payload = json.dumps({"table": self._table, "rows": [r.to_row() for r in rows]})
        req = urllib.request.Request(
            f"{self._url}/api/v1/rows",
            data=payload.encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        return {
            "events_written": self._events_written,
            "errors": self._errors,
            "buffer_size": len(self._buffer),
        }
