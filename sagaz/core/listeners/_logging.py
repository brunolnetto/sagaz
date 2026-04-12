"""Logging listener for saga lifecycle event tracking."""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from sagaz.core.listeners._base import SagaListener
from sagaz.core.logger import get_logger

logger = get_logger(__name__)


class LoggingSagaListener(SagaListener):
    """
    Logs all saga lifecycle events.

    Use this for debugging and observability.

    Example:
        >>> class OrderSaga(Saga):
        ...     listeners = [LoggingSagaListener(level=logging.DEBUG)]
    """

    def __init__(self, logger_instance=None, level: int | str = logging.INFO):
        self._logger_instance = logger_instance
        if isinstance(level, str):
            self.level = getattr(logging, level.upper(), logging.INFO)
        else:
            self.level = level

    @property
    def log(self):
        """Get logger - uses dynamic get_logger() if no instance provided."""
        if self._logger_instance is not None:
            return self._logger_instance
        return get_logger(__name__)

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        self.log.log(self.level, f"[SAGA] Starting: {saga_name} (id={saga_id})")

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        self.log.log(self.level, f"[STEP] Entering: {saga_name}.{step_name}")

    async def on_step_success(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], result: Any
    ) -> None:
        self.log.log(self.level, f"[STEP] Success: {saga_name}.{step_name}")

    async def on_step_failure(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self.log.error(f"[STEP] Failed: {saga_name}.{step_name} - {error}")

    async def on_compensation_start(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        self.log.log(self.level, f"[COMPENSATION] Starting: {saga_name}.{step_name}")

    async def on_compensation_complete(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        self.log.log(self.level, f"[COMPENSATION] Complete: {saga_name}.{step_name}")

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        self.log.log(self.level, f"[SAGA] Completed: {saga_name} (id={saga_id})")

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self.log.error(f"[SAGA] Failed: {saga_name} (id={saga_id}) - {error}")

