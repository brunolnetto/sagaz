"""Saga lifecycle mixin - state-machine entry callbacks for imperative Saga."""

import logging
from datetime import datetime

from sagaz.core.types import SagaStatus

# Keep the original logger name so log records are unchanged by the split.
logger = logging.getLogger("sagaz.core.saga")


class _SagaLifecycleMixin:
    """Mixin providing the ``_on_enter_*`` callbacks invoked by ``SagaStateMachine``."""

    # Attributes provided by the concrete Saga host.
    name: str
    saga_id: str
    status: SagaStatus
    started_at: datetime | None
    completed_at: datetime | None
    completed_steps: list

    async def _on_enter_executing(self) -> None:
        """Callback: entering EXECUTING state"""
        self.status = SagaStatus.EXECUTING
        self.started_at = datetime.now()
        self.completed_steps = []
        logger.info(f"Saga {self.name} [{self.saga_id}] entering EXECUTING state")

    async def _on_enter_compensating(self) -> None:
        """Callback: entering COMPENSATING state"""
        self.status = SagaStatus.COMPENSATING
        logger.warning(
            f"Saga {self.name} [{self.saga_id}] entering COMPENSATING state - "
            f"rolling back {len(self.completed_steps)} steps"
        )

    async def _on_enter_completed(self) -> None:
        """Callback: entering COMPLETED state"""
        self.status = SagaStatus.COMPLETED
        self.completed_at = datetime.now()
        execution_time = (
            (self.completed_at - self.started_at).total_seconds() if self.started_at else 0
        )
        logger.info(
            f"Saga {self.name} [{self.saga_id}] COMPLETED successfully in {execution_time:.2f}s"
        )

    async def _on_enter_rolled_back(self) -> None:
        """Callback: entering ROLLED_BACK state"""
        self.status = SagaStatus.ROLLED_BACK
        self.completed_at = datetime.now()
        execution_time = (
            (self.completed_at - self.started_at).total_seconds() if self.started_at else 0
        )
        logger.info(f"Saga {self.name} [{self.saga_id}] ROLLED_BACK after {execution_time:.2f}s")

    async def _on_enter_failed(self) -> None:
        """Callback: entering FAILED state (unrecoverable)"""
        self.status = SagaStatus.FAILED
        self.completed_at = datetime.now()
        logger.error(
            f"Saga {self.name} [{self.saga_id}] FAILED - unrecoverable error during compensation"
        )
