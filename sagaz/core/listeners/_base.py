"""Base class for saga event listeners."""

from abc import ABC
from typing import Any


class SagaListener(ABC):
    """
    Base class for saga event listeners.

    Subclass this to create custom listeners that respond to saga lifecycle
    events. All methods are optional - implement only what you need.

    Listeners are called in the order they appear in the `listeners` list.
    Errors in listeners are logged but do not break saga execution.
    """

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        """Called when saga execution begins."""

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        """Called before each step executes."""

    async def on_step_success(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], result: Any
    ) -> None:
        """Called after successful step completion."""

    async def on_step_failure(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        """Called when a step fails."""

    async def on_compensation_start(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        """Called before compensation runs for a step."""

    async def on_compensation_complete(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        """Called after compensation completes for a step."""

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        """Called when saga completes successfully."""

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        """Called when saga fails (after compensation attempts)."""
