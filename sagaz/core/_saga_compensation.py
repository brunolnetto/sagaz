"""Saga compensation mixin - step rollback and retry logic for imperative Saga."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sagaz.core.exceptions import SagaCompensationError
from sagaz.core.types import SagaStepStatus

logger = logging.getLogger(__name__)


class _SagaCompensationMixin:
    """Mixin adding compensation (rollback) capabilities to the Saga class."""

    async def _compensate_all(self) -> None:
        """
        Compensate all completed steps in reverse order
        Continues even if some compensations fail, collecting all errors
        """
        compensation_errors = await self._run_compensations()
        if compensation_errors:
            self._raise_compensation_error(compensation_errors)

    async def _run_compensations(self) -> list[SagaCompensationError]:
        """Execute all compensations, collecting errors."""
        errors = []
        for step in reversed(self.completed_steps):
            if step.compensation:
                error = await self._try_compensate_step(step)
                if error:
                    errors.append(error)
        return errors

    async def _try_compensate_step(self, step) -> SagaCompensationError | None:
        """Try to compensate a step, returning error if failed."""
        try:
            await self._compensate_step_with_retry(step)
            return None
        except SagaCompensationError as e:
            self.compensation_errors.append(e)
            logger.error(f"Compensation failed for step '{step.name}': {e}")
            return e

    def _raise_compensation_error(self, errors: list[SagaCompensationError]) -> None:
        """Raise aggregate compensation error."""
        error_summary = "; ".join(str(e) for e in errors)
        msg = f"Failed to compensate {len(errors)} steps: {error_summary}"
        raise SagaCompensationError(msg)

    async def _compensate_step_with_retry(self, step) -> None:
        """Compensate a step with retry logic"""
        last_error: SagaCompensationError | None = None
        max_comp_retries = 3

        for attempt in range(max_comp_retries):
            try:
                await self._compensate_step(step)
                return  # Success!

            except SagaCompensationError as e:
                last_error = e
                logger.warning(
                    f"Compensation for '{step.name}' failed "
                    f"(attempt {attempt + 1}/{max_comp_retries})"
                )

            # Exponential backoff (uses configurable base timeout)
            if attempt < max_comp_retries - 1:
                backoff_time = self.retry_backoff_base * (2**attempt)
                await asyncio.sleep(backoff_time)

        # All retries exhausted
        assert last_error is not None, "last_error should be set after exhausting retries"
        raise last_error

    async def _compensate_step(self, step) -> None:
        """Compensate a single step with timeout"""
        try:
            step.status = SagaStepStatus.COMPENSATING
            logger.info(f"Compensating step: {step.name}")

            # Type assertion - compensation must exist if _compensate_step is called
            assert step.compensation is not None, f"No compensation defined for step '{step.name}'"

            # Pass the step result to compensation for context
            await asyncio.wait_for(
                self._invoke(step.compensation, step.result, self.context),
                timeout=step.compensation_timeout,
            )

            step.status = SagaStepStatus.COMPENSATED
            step.compensated_at = datetime.now()
            logger.info(f"Step '{step.name}' compensated successfully")

        except TimeoutError:
            step.status = SagaStepStatus.FAILED
            msg = f"Compensation for '{step.name}' timed out after {step.compensation_timeout}s"
            raise SagaCompensationError(msg)

        except Exception as e:
            step.status = SagaStepStatus.FAILED
            step.error = e
            msg = f"Compensation for step '{step.name}' failed: {e!s}"
            raise SagaCompensationError(msg)

    @staticmethod
    async def _invoke(func: Callable[..., Any], *args, **kwargs) -> Any:
        """Invoke function (handle both sync and async)"""
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)
