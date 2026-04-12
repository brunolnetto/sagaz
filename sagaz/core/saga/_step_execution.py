"""
Step-level execution logic for Saga pattern

Handles:
- Step execution with timeout protection
- Retry logic with exponential backoff
- Step state transitions
- Error handling and step-specific failures
"""

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sagaz.core.exceptions import SagaStepError, SagaTimeoutError
from sagaz.core.types import SagaStepStatus

if TYPE_CHECKING:
    from sagaz.core.saga import Saga
    from sagaz.core.saga._step import SagaStep

logger = logging.getLogger(__name__)


class StepExecutor:
    """Handles individual step execution with retry and timeout logic"""

    def __init__(self, saga: "Saga"):
        self.saga = saga

    async def execute_step_with_retry(self, step: "SagaStep") -> None:
        """
        Execute a step with retry logic and exponential backoff

        Attempts step execution with configurable retry attempts and exponential backoff
        between retries. Raises the last error if all retries are exhausted.

        Args:
            step: The SagaStep to execute

        Raises:
            SagaTimeoutError: If step times out
            SagaStepError: If step fails
        """
        last_error: SagaTimeoutError | SagaStepError | None = None
        total_attempts = step.max_retries + 1  # Initial attempt + retries

        for attempt in range(total_attempts):
            try:
                step.retry_count = attempt
                await self.execute_step(step)
                return  # Success!

            except SagaTimeoutError as e:
                last_error = e
                logger.warning(
                    f"Step '{step.name}' timed out (attempt {attempt + 1}/{total_attempts})"
                )

            except SagaStepError as e:
                last_error = e
                logger.warning(
                    f"Step '{step.name}' failed (attempt {attempt + 1}/{total_attempts}): {e}"
                )

            # Exponential backoff before retry (configurable base timeout)
            if attempt < total_attempts - 1:
                backoff_time = self.saga.retry_backoff_base * (2**attempt)
                logger.info(f"Retrying step '{step.name}' in {backoff_time}s...")
                await asyncio.sleep(backoff_time)

        # All retries exhausted
        step.error = last_error
        assert last_error is not None, "last_error should be set after exhausting retries"
        raise last_error

    async def execute_step(self, step: "SagaStep") -> None:
        """
        Execute a single step with timeout

        Executes the step action with timeout protection. On success, stores the result
        in the saga context for subsequent steps to access.

        Args:
            step: The SagaStep to execute

        Raises:
            SagaTimeoutError: If step execution exceeds timeout
            SagaStepError: If step action raises an exception
        """
        try:
            step.status = SagaStepStatus.EXECUTING
            logger.info(f"Executing step: {step.name}")

            # Execute with timeout
            step.result = await asyncio.wait_for(
                self.saga._invoke(step.action, self.saga.context), timeout=step.timeout
            )

            # Store result in context for next steps
            self.saga.context.set(step.name, step.result)

            step.status = SagaStepStatus.COMPLETED
            step.executed_at = datetime.now()
            logger.info(f"Step '{step.name}' completed successfully")

        except TimeoutError:
            step.status = SagaStepStatus.FAILED
            error = SagaTimeoutError(f"Step '{step.name}' timed out after {step.timeout}s")
            step.error = error
            raise error

        except Exception as e:
            step.status = SagaStepStatus.FAILED
            step.error = e
            msg = f"Step '{step.name}' failed: {e!s}"
            raise SagaStepError(msg)
