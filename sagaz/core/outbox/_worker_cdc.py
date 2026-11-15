"""CDC mode of the outbox worker (ADR-011, #50).

In CDC mode the worker does not poll ``saga_outbox`` for new events: a
:class:`~sagaz.integrations.cdc.CDCSource` streams inserted rows from the
database's change log, and the worker publishes each one through the same path
as polled events (tenant scope, broker, ``SENT`` status, failure handling).

**Hybrid recovery.** A failed publish moves the event back to ``PENDING`` with
an ``UPDATE``, which is not a new insert, so the change stream never delivers
it again. A slow sweep therefore claims events that have been pending for
longer than ``cdc_sweep_min_age_seconds`` and processes them as polling would:
retries, events the stream missed, and anything inserted while the worker was
down. Fresh events are left to the stream, so the two paths rarely meet; when
they do (a stream lagging behind the sweep age), the event is published twice,
which the outbox's at-least-once contract already allows.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sagaz.core.outbox._worker_logging import logger
from sagaz.core.tenant import system_scope

if TYPE_CHECKING:
    import prometheus_client

    from sagaz.core.outbox.types import OutboxConfig, OutboxEvent
    from sagaz.integrations.cdc import CDCChange, CDCSource

CDC_LAG: prometheus_client.Histogram | None
CDC_EVENTS: prometheus_client.Counter | None
CDC_ERRORS: prometheus_client.Counter | None

try:
    from prometheus_client import Counter, Histogram

    CDC_LAG = Histogram(
        "sagaz_cdc_lag_seconds",
        "Time from the commit of an outbox insert to the end of its processing",
        ["source"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    )
    CDC_EVENTS = Counter(
        "sagaz_cdc_events_total",
        "Outbox events received from the CDC source and processed",
        ["source"],
    )
    CDC_ERRORS = Counter(
        "sagaz_cdc_errors_total",
        "CDC errors: events whose processing raised, and source stream failures",
        ["source", "kind"],
    )
except ImportError:  # pragma: no cover - prometheus_client is optional
    CDC_LAG = CDC_EVENTS = CDC_ERRORS = None


def _record_change(source: str, change: CDCChange, now: datetime, failed: bool) -> None:
    if CDC_EVENTS is None or CDC_LAG is None or CDC_ERRORS is None:  # pragma: no cover
        return
    CDC_EVENTS.labels(source=source).inc()
    if failed:
        CDC_ERRORS.labels(source=source, kind="event").inc()
    if change.committed_at is not None:
        CDC_LAG.labels(source=source).observe(max(0.0, (now - change.committed_at).total_seconds()))


class OutboxWorkerCDCMixin:
    """``run_cdc`` and ``process_changes`` for :class:`OutboxWorker`."""

    config: OutboxConfig
    worker_id: str
    _running: bool
    _shutdown_event: asyncio.Event

    async def _process_event(self, event: OutboxEvent) -> None:  # pragma: no cover - worker
        raise NotImplementedError

    async def process_batch(self, older_than_seconds: float = 0.0) -> int:  # pragma: no cover
        raise NotImplementedError

    async def process_changes(self, changes: list[CDCChange], source: str = "cdc") -> int:
        """Publish a batch of captured inserts; return how many were processed without error."""
        results = await asyncio.gather(
            *(self._process_event(change.event) for change in changes), return_exceptions=True
        )
        now = datetime.now(UTC)
        processed = 0
        for change, result in zip(changes, results, strict=True):
            failed = isinstance(result, BaseException)
            if failed:
                logger.error(f"CDC event {change.event.event_id} failed: {result}")
            else:
                processed += 1
            _record_change(source, change, now, failed)
        return processed

    async def run_cdc(self, source: CDCSource) -> None:
        """Consume ``source`` until :meth:`stop`; sweep stale pending events meanwhile."""
        await source.start()
        consumer = asyncio.create_task(self._consume(source))
        tasks: set[asyncio.Task[Any]] = {consumer, asyncio.create_task(self._shutdown_event.wait())}
        if self.config.cdc_sweep_interval_seconds:
            tasks.add(asyncio.create_task(self._sweep_loop()))
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if consumer in done and consumer.exception() is not None:
                if CDC_ERRORS is not None:
                    CDC_ERRORS.labels(source=source.name, kind="stream").inc()
                raise consumer.exception()  # type: ignore[misc]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await source.stop()

    async def _consume(self, source: CDCSource) -> None:
        async for batch in source.changes():
            if not batch:
                continue
            await self.process_changes(batch, source.name)
            # Acknowledge only after the whole batch was handled (published, or
            # recorded as failed for the sweep to retry): at least once.
            await source.ack(batch[-1].position)

    async def _sweep_loop(self) -> None:
        interval = float(self.config.cdc_sweep_interval_seconds or 0)
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                with system_scope():
                    swept = await self.process_batch(
                        older_than_seconds=self.config.cdc_sweep_min_age_seconds
                    )
                if swept:
                    logger.info(f"Worker {self.worker_id} swept {swept} stale pending events")
            except Exception as e:  # keep sweeping; the stream is the main path
                logger.error(f"Worker {self.worker_id} sweep failed: {e}")
