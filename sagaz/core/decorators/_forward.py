"""Forward recovery: what a saga does when a step fails after a pivot (#570, ADR-023).

Before a pivot, a failed step rolls the saga back. After a pivot completed, its effects
cannot be undone, so a step that fails downstream of it may be recovered forward instead.
The step's ``@forward_recovery`` handler decides, as ``handler(ctx, error)`` returning a
``RecoveryAction``:

- ``RETRY`` / ``RETRY_WITH_ALTERNATE``: run the step again (the handler may have changed
  the context), at most the handler's ``max_retries`` times.
- ``SKIP``: leave the step failed, without a result or a compensation, and go on. The
  steps that depend on it run; the handler puts in the context what they need.
- ``MANUAL_INTERVENTION``: stop. Nothing is compensated, and the saga ends in
  ``FORWARD_RECOVERY``, waiting for a person. Retries that run out, a handler that raises
  and a value that is no ``RecoveryAction`` end the same way.
- ``COMPENSATE_PIVOT``: roll everything back, the pivot and its ancestors included.

Without a handler, the saga compensates what is still reversible and ends in
``PARTIALLY_COMMITTED``: the pivot and its ancestors stay done.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from sagaz.core.decorators._steps import ForwardRecoveryMetadata
from sagaz.core.execution._pivot_types import RecoveryAction
from sagaz.core.logger import get_logger

logger = get_logger("sagaz.core.decorators")

_RETRY = (RecoveryAction.RETRY, RecoveryAction.RETRY_WITH_ALTERNATE)


class _Step(Protocol):
    """What forward recovery reads of a step's definition (no import of it: no cycle)."""

    step_id: str
    depends_on: list[str]


class _Handler(Protocol):
    """A method decorated with ``@forward_recovery``."""

    _saga_forward_recovery_meta: ForwardRecoveryMetadata

    def __call__(self, ctx: dict[str, Any], error: Exception) -> object: ...


class StepSkippedError(Exception):
    """A step's forward recovery handler chose ``SKIP``: the step failed, the saga goes on."""

    def __init__(self, step_id: str, error: BaseException) -> None:
        self.error = error
        super().__init__(f"step '{step_id}' skipped by its forward recovery handler: {error}")


def recovery_handler(step: str, handler: Callable[..., Any]) -> Callable[..., Any]:
    """*handler* as the forward recovery of *step*, for a step added with ``add_step`` (#678).

    A function decorated with ``@forward_recovery`` keeps its ``max_retries`` and
    ``timeout_seconds``; a plain ``handler(ctx, error)`` gets the defaults.
    """
    meta = getattr(handler, "_saga_forward_recovery_meta", None) or ForwardRecoveryMetadata(
        for_step=step
    )

    @functools.wraps(handler)
    def asked(ctx: dict[str, Any], error: Exception) -> object:
        return handler(ctx, error)

    setattr(asked, "_saga_forward_recovery_meta", meta)  # noqa: B010 - the engine reads it
    return asked


class _ForwardRecoveryMixin:
    """Forward recovery for the execution engine."""

    #: The step whose failure needs a person; set when recovery stops forward.
    _needs_forward_recovery: str | None = None
    #: The handler chose COMPENSATE_PIVOT: pivots and tainted steps are undone too.
    _compensate_pivots: bool = False

    if TYPE_CHECKING:
        saga: Any
        _failed_step: str | None

        async def _attempt_step(self, step: _Step) -> object: ...
        async def _compensate(self) -> None: ...

    def _after_completed_pivot(self, step: _Step) -> bool:
        """Whether *step* is downstream of a pivot that completed."""
        pivots, registry = self.saga._completed_pivots, self.saga._step_registry
        pending, seen = list(step.depends_on), set()
        while pending:
            name = pending.pop()
            if name in pivots:
                return True
            if name not in seen and name in registry:
                seen.add(name)
                pending.extend(registry[name].depends_on)
        return False

    async def _recover_forward(self, step: _Step) -> object:
        """Run *step*'s attempts; if they fail after a pivot, let its handler decide."""
        handler = self.saga._forward_recovery_handlers.get(step.step_id)
        retries = 0
        while True:
            try:
                return await self._attempt_step(step)
            except Exception as error:
                if handler is None or not self._after_completed_pivot(step):
                    raise
                action = await self._ask(handler, step.step_id, error)
                limit = handler._saga_forward_recovery_meta.max_retries
                if action in _RETRY and retries < limit:
                    retries += 1
                    logger.info(f"Forward recovery retries '{step.step_id}' ({retries}/{limit})")
                    continue
                if action is RecoveryAction.SKIP:
                    raise StepSkippedError(step.step_id, error) from error
                if action is RecoveryAction.COMPENSATE_PIVOT:
                    self._compensate_pivots = True
                else:  # MANUAL_INTERVENTION, retries that ran out, or no usable answer
                    self._needs_forward_recovery = step.step_id
                raise

    async def _ask(
        self, handler: _Handler, step_id: str, error: Exception
    ) -> RecoveryAction | None:
        """The handler's ``RecoveryAction``, or None if it raised or answered something else."""
        timeout = handler._saga_forward_recovery_meta.timeout_seconds
        try:
            answer = handler(self.saga._context, error)
            if inspect.isawaitable(answer):
                answer = await asyncio.wait_for(answer, timeout)
        except Exception as handler_error:
            logger.error(f"Forward recovery handler of '{step_id}' failed: {handler_error}")
            return None
        if not isinstance(answer, RecoveryAction):
            logger.error(f"Forward recovery handler of '{step_id}' returned {answer!r}")
            return None
        return answer

    async def _roll_back(self) -> None:
        """Compensate, unless the saga stopped to be recovered forward."""
        if self._needs_forward_recovery is None:
            await self._compensate()
