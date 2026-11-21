"""Retries and timeouts of declarative saga steps (#533).

A step runs ``max_retries + 1`` times at most, each attempt under its timeout,
with exponential backoff between attempts (``Saga.retry_backoff_base * 2**n``
seconds), like the imperative engine. A step that sets neither falls back to
``SagaConfig.default_timeout`` and ``SagaConfig.default_max_retries``; a tenant
quota may lower both (ADR-020). Cancellation is never retried.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sagaz.core.logger import get_logger
from sagaz.core.tenant import capped_retries, capped_timeout

if TYPE_CHECKING:
    from sagaz.core.decorators import Saga, SagaStepDefinition
    from sagaz.core.decorators._step_ledger import StepLedger

logger = get_logger("sagaz.core.decorators")

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 3


def _number(value: Any) -> int | float | None:
    """``value`` when it is a number (a config may be any object, even a mock)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


class _StepAttemptsMixin:
    """Runs a step's attempts for the execution engine."""

    saga: Saga
    _ledger: StepLedger

    if TYPE_CHECKING:

        async def _run_step(self, step: SagaStepDefinition, kind: str = ...) -> Any: ...

        async def _run_compensation(self, step_id: str, fallback: Any) -> Any: ...

    def _step_timeout(self, step: SagaStepDefinition) -> float:
        """The step's timeout, else the config's default, capped by the tenant's quota."""
        if step.timeout_seconds is not None:
            return capped_timeout(step.timeout_seconds)
        default = _number(getattr(self.saga._config, "default_timeout", None))
        return capped_timeout(DEFAULT_TIMEOUT if default is None else float(default))

    def _step_retries(self, step: SagaStepDefinition) -> int:
        """The step's retries, else the config's default, capped by the tenant's quota."""
        if step.max_retries is not None:
            return capped_retries(step.max_retries)
        default = _number(getattr(self.saga._config, "default_max_retries", None))
        return capped_retries(DEFAULT_MAX_RETRIES if default is None else int(default))

    async def _attempt_step(self, step: SagaStepDefinition) -> Any:
        """Run the step until an attempt succeeds; re-raise the last attempt's error."""
        timeout = self._step_timeout(step)
        attempts = self._step_retries(step) + 1
        for attempt in range(attempts):
            self._ledger.attempted(step.step_id, attempt)
            try:
                return await asyncio.wait_for(self._run_step(step), timeout=timeout)
            except Exception as error:  # asyncio.CancelledError is not an Exception
                if attempt == attempts - 1:
                    raise
                delay = self.saga.retry_backoff_base * (2**attempt)
                logger.warning(
                    f"Step '{step.step_id}' failed (attempt {attempt + 1}/{attempts}): "
                    f"{type(error).__name__}: {error}; retrying in {delay:g}s"
                )
                await asyncio.sleep(delay)
        msg = "unreachable: the last attempt returns or raises"
        raise AssertionError(msg)

    async def _attempt_compensation(self, step_id: str, node: Any) -> None:
        """Run a compensation until an attempt succeeds (#550): ``max_retries + 1`` at most.

        Each attempt runs under the compensation's timeout, with the same backoff as
        steps; the last attempt's error is raised. Cancellation is never retried.
        """
        attempts = int(node.max_retries) + 1
        for attempt in range(attempts):
            try:
                await asyncio.wait_for(
                    self._run_compensation(step_id, node.compensation_fn),
                    timeout=node.timeout_seconds,
                )
                return
            except Exception as error:
                if attempt == attempts - 1:
                    raise
                delay = self.saga.retry_backoff_base * (2**attempt)
                logger.warning(
                    f"Compensation of '{step_id}' failed (attempt {attempt + 1}/{attempts}): "
                    f"{type(error).__name__}: {error}; retrying in {delay:g}s"
                )
                await asyncio.sleep(delay)
