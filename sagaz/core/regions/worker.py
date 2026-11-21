"""Regional workers: run the steps assigned to their region (ADR-034, #59)."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from sagaz.choreography.events import AbstractEventBus, Event
from sagaz.core.events import json_safe
from sagaz.core.regions._protocol import ACTION, COMPENSATION, HEARTBEAT, REPLY_PREFIX, REQUEST
from sagaz.core.tenant import tenant_scope

logger = logging.getLogger(__name__)

StepFn = Callable[[dict[str, Any]], Awaitable[Any]]


class RegionalWorker:
    """Runs, in *region*, the saga steps that coordinators route there.

    Register the steps it may run, either from saga classes (:meth:`serve`) or
    one by one (:meth:`register`), then :meth:`start` it. Replicas of a worker
    share the region bus's consumer group, so each request runs once. While
    running, the worker publishes a heartbeat every *heartbeat_interval*
    seconds; coordinators treat the region as down when heartbeats stop.

    Steps receive a copy of the saga context. Return what the saga needs; to
    keep personal data in the region, return references (ids), not the data.
    """

    def __init__(
        self,
        region: str,
        bus: AbstractEventBus,
        *,
        heartbeat_interval: float = 1.0,
        worker_id: str | None = None,
    ) -> None:
        self.region = region
        self.bus = bus
        self.heartbeat_interval = heartbeat_interval
        self.worker_id = worker_id or f"{region}-{uuid4().hex[:8]}"
        self._steps: dict[tuple[str, str, str], StepFn] = {}
        self._heartbeats: asyncio.Task[None] | None = None

    # -- registration ----------------------------------------------------------

    def register(
        self, saga_name: str, step: str, action: StepFn, compensation: StepFn | None = None
    ) -> None:
        """Let this worker run *step* of *saga_name* (and its compensation)."""
        self._steps[(saga_name, step, ACTION)] = action
        if compensation is not None:
            self._steps[(saga_name, step, COMPENSATION)] = compensation

    def serve(self, saga: object) -> None:
        """Register every region-assigned step of *saga* (a ``Saga`` class or instance)."""
        instance: Any = saga() if inspect.isclass(saga) else saga
        name = instance.saga_name or type(instance).__name__
        for step in instance.get_steps():
            if step.region is not None:
                self.register(name, step.step_id, step.forward_fn, step.compensation_fn)

    @property
    def steps(self) -> list[tuple[str, str, str]]:
        return sorted(self._steps)

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        self.bus.subscribe(REQUEST, self._on_request)
        await self._beat()
        self._heartbeats = asyncio.get_running_loop().create_task(self._beat_forever())

    async def stop(self) -> None:
        self.bus.unsubscribe(REQUEST, self._on_request)
        if self._heartbeats is not None:
            self._heartbeats.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeats
            self._heartbeats = None

    async def _beat(self) -> None:
        await self.bus.publish(
            Event(
                HEARTBEAT, {"region": self.region, "worker": self.worker_id}, source=self.worker_id
            )
        )

    async def _beat_forever(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._beat()
            except Exception:
                logger.exception("Region %s: heartbeat failed", self.region)

    # -- requests --------------------------------------------------------------

    async def _on_request(self, event: Event) -> None:
        request = event.data
        if request.get("target") != self.region:
            return  # for another region sharing the bus
        key = (request["saga_name"], request["step"], request["kind"])
        reply: dict[str, Any] = {"request_id": event.event_id}
        fn = self._steps.get(key)
        if fn is None:
            reply |= {
                "ok": False,
                "error_type": "LookupError",
                "error_message": f"worker {self.worker_id} does not serve {key}",
            }
        else:
            try:
                with tenant_scope(event.tenant_id):
                    result = await fn(dict(request.get("context") or {}))
                reply |= {"ok": True, "result": json_safe(result)}
            except Exception as error:
                logger.warning("Region %s: %s %s failed: %s", self.region, key[2], key[1], error)
                reply |= {
                    "ok": False,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                }
        await self.bus.publish(
            Event(
                REPLY_PREFIX + request["coordinator"],
                reply,
                saga_id=event.saga_id,
                tenant_id=event.tenant_id,
                source=self.worker_id,
            )
        )
