from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from sagaz.core.listeners import SagaListener


class EventPublisher(Protocol):
    """Transport interface for visualization events."""

    async def publish(self, event: dict[str, Any]) -> None:
        """Publish one visualization event."""


class HTTPEventPublisher:
    """Best-effort HTTP publisher for a standalone visualization server."""

    def __init__(
        self,
        server_url: str,
        token: str | None = None,
        timeout_seconds: float = 0.5,
    ) -> None:
        parsed = urlsplit(server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            message = "server_url must be an absolute HTTP(S) URL"
            raise ValueError(message)
        if parsed.query or parsed.fragment:
            message = "server_url must not contain a query or fragment"
            raise ValueError(message)
        if timeout_seconds <= 0:
            message = "timeout_seconds must be positive"
            raise ValueError(message)

        self.endpoint = urljoin(server_url.rstrip("/") + "/", "api/v1/events")
        self.token = token
        self.timeout_seconds = timeout_seconds

    async def publish(self, event: dict[str, Any]) -> None:
        """Send an event without blocking the Saga's event loop."""
        await asyncio.to_thread(self._post, event)

    def _post(self, event: dict[str, Any]) -> None:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = Request(
            self.endpoint,
            data=json.dumps(event, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urlopen(request, timeout=self.timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if not 200 <= status < 300:
                message = f"Visualization server returned HTTP {status}"
                raise RuntimeError(message)


class VisualizationSagaListener(SagaListener):
    """Forward allowlisted Saga lifecycle events to a visualization server.

    Event delivery is best-effort. Network failures propagate to the existing
    Saga listener dispatcher, which logs listener failures without aborting
    Saga execution.
    """

    def __init__(
        self,
        server_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 0.5,
        *,
        publisher: EventPublisher | None = None,
    ) -> None:
        if publisher is None:
            if server_url is None:
                message = "server_url or publisher must be provided"
                raise ValueError(message)
            publisher = HTTPEventPublisher(
                server_url,
                token=token,
                timeout_seconds=timeout_seconds,
            )

        self.publisher = publisher

    @classmethod
    def from_env(
        cls,
        *,
        timeout_seconds: float = 0.5,
    ) -> VisualizationSagaListener:
        """Create a listener from SAGAZ_VISUALIZATION_* environment variables."""
        server_url = os.environ.get("SAGAZ_VISUALIZATION_URL")
        if not server_url:
            message = "SAGAZ_VISUALIZATION_URL must be configured"
            raise ValueError(message)
        return cls(
            server_url=server_url,
            token=os.environ.get("SAGAZ_VISUALIZATION_TOKEN"),
            timeout_seconds=timeout_seconds,
        )

    async def _emit(
        self,
        event_type: str,
        saga_name: str,
        saga_id: str,
        *,
        step_name: str | None = None,
        error: Exception | None = None,
    ) -> None:
        event = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "saga_id": str(saga_id),
            "saga_name": str(saga_name),
            "step_name": step_name,
            "error_type": type(error).__name__ if error is not None else None,
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        await self.publisher.publish(event)

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        await self._emit("saga.started", saga_name, saga_id)

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        await self._emit(
            "step.started",
            saga_name,
            ctx.get("saga_id", "unknown"),
            step_name=step_name,
        )

    async def on_step_success(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], result: Any
    ) -> None:
        await self._emit(
            "step.succeeded",
            saga_name,
            ctx.get("saga_id", "unknown"),
            step_name=step_name,
        )

    async def on_step_failure(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        await self._emit(
            "step.failed",
            saga_name,
            ctx.get("saga_id", "unknown"),
            step_name=step_name,
            error=error,
        )

    async def on_compensation_start(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        await self._emit(
            "step.compensation_started",
            saga_name,
            ctx.get("saga_id", "unknown"),
            step_name=step_name,
        )

    async def on_compensation_complete(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        await self._emit(
            "step.compensated",
            saga_name,
            ctx.get("saga_id", "unknown"),
            step_name=step_name,
        )

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        await self._emit("saga.completed", saga_name, saga_id)

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        await self._emit("saga.failed", saga_name, saga_id, error=error)
