"""Per-step idempotency keys for ``sagaz.Saga`` (#569).

A saga id runs once (#535), but two different sagas can still call the same API that
is not idempotent: two checkouts charging the same order. A step declares what makes
its effect unique::

    @action("charge", idempotency_key="charge-{order_id}")
    async def charge(self, ctx): ...

The key is built from the saga context (a format string, or a function of the context)
and is unique per tenant, across sagas of any class:

- **First run:** the step claims the key, runs, and stores its result with the key.
- **Key already completed:** the step is not run. The stored result goes into the
  context and the saga goes on as if the step had run, so the step is compensated if
  this saga fails later.
- **Key claimed but not completed:** the step fails with ``StepInDoubtError``, without
  running. The first run crashed in the step, was cancelled, or is running now, and its
  effect may or may not have happened. ``release_step_key()`` frees the key once checked.
- **The step raises:** the key is released. A step that raised did not take effect, as
  for compensation, which does not undo a step that failed.
- **The step is compensated:** the key is released, so a later run executes it again.

Keys are stored in the saga storage as reserved records, created atomically
(``create_saga_state``), so every backend has them with no new table. They last as long
as that storage: a ``SagaConfig`` without one keeps them in its own memory, so configure
a durable saga storage for keys that must survive a restart.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from sagaz.core.decorators._steps import StepKey
from sagaz.core.events import json_safe
from sagaz.core.exceptions import SagaDefinitionError, StepInDoubtError
from sagaz.core.storage._reserved import RESERVED_SAGA_PREFIX
from sagaz.core.types import SagaStatus

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces import SagaStorage

logger = logging.getLogger(__name__)

#: Saga name of the records that hold step idempotency keys.
STEP_KEY_RECORD_NAME = f"{RESERVED_SAGA_PREFIX}step_keys__"

_memory: SagaStorage | None = None


def _fallback() -> SagaStorage:
    """Keys of sagas run without a saga storage: this process's memory."""
    global _memory
    if _memory is None:
        from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage

        _memory = InMemorySagaStorage()
    return _memory


def record_id(key: str) -> str:
    """The id of *key*'s record (a digest: keys may be long or hold any character)."""
    return f"{STEP_KEY_RECORD_NAME}:{hashlib.sha256(key.encode()).hexdigest()[:40]}"


def render_key(step_name: str, key: StepKey, context: dict[str, Any]) -> str:
    """*key* for this run: the format string filled from, or the function called with, *context*."""
    try:
        rendered = key(context) if callable(key) else key.format_map(context)
    except KeyError as missing:
        msg = f"step {step_name!r}: idempotency_key needs {missing} in the saga context"
        raise SagaDefinitionError(msg) from None
    if not isinstance(rendered, str) or not rendered:
        msg = f"step {step_name!r}: idempotency_key must give a non-empty string"
        raise SagaDefinitionError(msg)
    return rendered


async def release_step_key(key: str, storage: SagaStorage | None = None) -> bool:
    """Free *key* in the current tenant scope, so that a step with it runs again.

    For a key left in doubt (``StepInDoubtError``), once its effect was checked. Returns
    whether the key existed. *storage* is the saga storage (default: this process's).
    """
    deleted: bool = await (storage or _fallback()).delete_saga_state(record_id(key))
    return deleted


class StepKeys:
    """The idempotency keys of one saga run."""

    def __init__(self, storage: SagaStorage | None, saga_id: str) -> None:
        self._storage = storage or _fallback()
        self._saga_id = saga_id
        self._held: dict[str, str] = {}  # step -> the key it ran or reused in this run

    async def run(
        self,
        step_name: str,
        key: StepKey | None,
        context: dict[str, Any],
        attempt: Callable[[], Awaitable[object]],
    ) -> object:
        """*attempt*'s result, or the stored one if *key* already completed."""
        if key is None:
            return await attempt()
        rendered = render_key(step_name, key, context)
        claimed, stored = await self._claim(step_name, rendered)
        self._held[step_name] = rendered
        if not claimed:
            logger.info("step %r reuses the result of key %r", step_name, rendered)
            return stored
        try:
            result = await attempt()
        except Exception:  # the step raised: it did not take effect, so the key is free
            del self._held[step_name]
            await self._storage.delete_saga_state(record_id(rendered))
            raise
        # A cancellation is not caught: the effect is unknown, so the key stays claimed.
        await self._save(step_name, rendered, SagaStatus.COMPLETED, json_safe(result))
        return result

    async def compensated(self, step_name: str) -> None:
        """The step was undone: free its key, so that a later run executes it."""
        key = self._held.pop(step_name, None)
        if key is not None:
            await self._storage.delete_saga_state(record_id(key))

    async def _claim(self, step_name: str, key: str) -> tuple[bool, object]:
        """Claim *key*: ``(True, None)``, or ``(False, result)`` if it already completed."""
        fields = self._fields(step_name, key, None)
        created = await self._storage.create_saga_state(
            record_id(key), STEP_KEY_RECORD_NAME, SagaStatus.EXECUTING, [], fields
        )
        if created:
            return True, None
        record = await self._storage.load_saga_state(record_id(key)) or {}
        held = record.get("context") or {}
        if _status(record) == SagaStatus.COMPLETED.value:
            return False, held.get("result")
        raise StepInDoubtError(key, step_name, held.get("saga_id"))

    async def _save(self, step_name: str, key: str, status: SagaStatus, result: object) -> None:
        await self._storage.save_saga_state(
            record_id(key), STEP_KEY_RECORD_NAME, status, [], self._fields(step_name, key, result)
        )

    def _fields(self, step_name: str, key: str, result: object) -> dict[str, Any]:
        return {"key": key, "saga_id": self._saga_id, "step": step_name, "result": result}


def _status(record: dict[str, Any]) -> str:
    status = record.get("status")
    return str(getattr(status, "value", status))
