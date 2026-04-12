"""Logging convenience hooks for step lifecycle events."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_step_lifecycle(logger_instance=None) -> dict[str, Any]:
    """
    Create a set of hooks that log all step lifecycle events.

    Returns:
        Dict with on_enter, on_success, on_failure hooks

    Example:
        >>> hooks = log_step_lifecycle()
        >>> @step("my_step", **hooks)
        ... async def my_step(self, ctx):
        ...     ...
    """
    log = logger_instance or logger

    async def on_enter(ctx: dict[str, Any], step_name: str):
        log.info(f"[STEP] Entering: {step_name}")

    async def on_success(ctx: dict[str, Any], step_name: str, result: Any):
        log.info(f"[STEP] Success: {step_name}")

    async def on_failure(ctx: dict[str, Any], step_name: str, error: Exception):
        log.error(f"[STEP] Failed: {step_name} - {error}")

    return {
        "on_enter": on_enter,
        "on_success": on_success,
        "on_failure": on_failure,
    }
