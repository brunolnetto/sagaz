"""Private methods the declarative Saga kept when they moved to ``ExecutionEngine``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.decorators._execution import ExecutionEngine


class _DecoratorCompatMixin:
    """Backward compatible: each one delegates to a fresh execution engine."""

    if TYPE_CHECKING:

        def _engine(self, allow_rerun: bool) -> ExecutionEngine: ...

    def _initialize_run(self, initial_context: dict[str, Any], saga_id: str | None) -> None:
        """Initialize saga run state."""
        self._engine(False)._initialize_run(initial_context, saga_id)

    def _register_compensations(self) -> None:
        """Register all compensations in the graph."""
        self._engine(False)._register_compensations()

    async def _execute_level(self, level_steps: list) -> None:
        """Execute all steps in a level."""
        await self._engine(False)._execute_level(level_steps)

    async def _execute_compensation(self, step_id: str) -> None:
        """Execute compensation for a specific step."""
        await self._engine(False)._execute_compensation(step_id)
