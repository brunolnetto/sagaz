"""
CDCWorker — polls a Debezium Kafka Connect HTTP endpoint and turns
raw CDC payloads into ``CDCEvent`` objects that the outbox processor can
consume.

The worker is designed to be run as an asyncio background task:

    worker = CDCWorker("http://debezium:8083", connector_name="sagaz-pg")
    await worker.start()
    # … application runs …
    await worker.stop()

In tests, use ``CDCWorker`` with a mocked ``_http_get`` to avoid network calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sagaz.integrations.cdc.metrics import CDCMetrics

logger = logging.getLogger(__name__)


class CDCEventType(Enum):
    INSERT = "c"  # create
    UPDATE = "u"
    DELETE = "d"
    READ = "r"  # snapshot read


@dataclass
class CDCEvent:
    """
    A single change captured from the database.

    Attributes
    ----------
    table:
        Source table name (e.g. ``"saga_state"``).
    op:
        Operation type: INSERT / UPDATE / DELETE / READ.
    before:
        Row state before the change (None for INSERTs).
    after:
        Row state after the change (None for DELETEs).
    ts_ms:
        Source database commit timestamp in milliseconds since epoch.
    offset:
        Connector offset token for resumable consumption.
    """

    table: str
    op: CDCEventType
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ts_ms: int = 0
    offset: str = ""

    @property
    def saga_id(self) -> str | None:
        row = self.after or self.before or {}
        return row.get("saga_id")

    @classmethod
    def from_debezium_payload(cls, payload: dict[str, Any]) -> CDCEvent:
        """Parse a Debezium « source » payload dict into a CDCEvent."""
        op_str = payload.get("op", "r")
        try:
            op = CDCEventType(op_str)
        except ValueError:
            op = CDCEventType.READ
        return cls(
            table=payload.get("source", {}).get("table", "unknown"),
            op=op,
            before=payload.get("before"),
            after=payload.get("after"),
            ts_ms=payload.get("ts_ms", 0),
            offset=str(payload.get("source", {}).get("lsn", "")),
        )


# ---------------------------------------------------------------------------
# CDCWorker
# ---------------------------------------------------------------------------

_DEFAULT_POLL_INTERVAL = 1.0  # seconds


class CDCWorker:
    """
    Polls the Debezium Kafka Connect REST API and processes CDC events.

    Parameters
    ----------
    connect_url:
        Base URL for the Kafka Connect REST API (e.g. ``http://localhost:8083``).
    connector_name:
        Name of the registered Debezium connector.
    poll_interval:
        Seconds between polling cycles.
    on_event:
        Async callback invoked for each ``CDCEvent``.  Defaults to a no-op.
    metrics:
        Optional ``CDCMetrics`` instance for Prometheus-style counting.
    """

    def __init__(
        self,
        connect_url: str,
        connector_name: str = "sagaz-pg",
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        on_event: Callable[[CDCEvent], Coroutine] | None = None,
        metrics: CDCMetrics | None = None,
    ) -> None:
        self._url = connect_url.rstrip("/")
        self._connector = connector_name
        self._poll_interval = poll_interval
        self._on_event = on_event
        self._metrics = metrics or CDCMetrics()
        self._running = False
        self._task: asyncio.Task | None = None
        self._offset: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("CDCWorker started — connector=%s", self._connector)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CDCWorker stopped")

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                events = await self._fetch_events()
                for ev in events:
                    await self._process(ev)
            except Exception as exc:
                logger.exception("CDC poll error: %s", exc)
                self._metrics.increment_error()
            await asyncio.sleep(self._poll_interval)

    async def _fetch_events(self) -> list[CDCEvent]:
        """
        Fetch pending CDC events from the Debezium connector endpoint.
        Subclasses can override ``_http_get`` to inject test responses.
        """
        url = f"{self._url}/connectors/{self._connector}/offsets"
        try:
            payload = await self._http_get(url)
        except Exception as exc:
            logger.warning("CDC fetch failed: %s", exc)
            self._metrics.increment_error()
            return []

        events = []
        for record in payload.get("records", []):
            try:
                ev = CDCEvent.from_debezium_payload(record)
                events.append(ev)
            except Exception:
                logger.warning("Could not parse CDC record: %r", record)
        return events

    async def _process(self, event: CDCEvent) -> None:
        time.monotonic()
        lag_ms = (time.time() * 1000 - event.ts_ms) if event.ts_ms else 0.0
        self._metrics.record_event(lag_ms=lag_ms)
        if self._on_event:
            await self._on_event(event)
        logger.debug(
            "CDC event processed: table=%s op=%s saga_id=%s", event.table, event.op, event.saga_id
        )

    # Seam for injection in tests
    async def _http_get(self, url: str) -> dict[str, Any]:
        """Make a GET request to *url* and return parsed JSON."""
        import json
        import urllib.request

        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def get_metrics(self) -> dict[str, Any]:
        return self._metrics.snapshot()
