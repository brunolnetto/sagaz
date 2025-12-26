import asyncio
import logging
from typing import Any

from sagaz.core import Saga, SagaResult
from sagaz.types import SagaStatus

# ============================================
# SAGA ORCHESTRATOR
# ============================================


class SagaOrchestrator:
    """
    Production-ready orchestrator for managing and tracking multiple sagas
    Thread-safe with proper async support
    """

    def __init__(self, logger: logging.Logger | None = None, verbose: bool = False):
        self.sagas: dict[str, Saga] = {}
        self._lock = asyncio.Lock()
        self.logger = logger or logging.getLogger(__name__)
        self.verbose = verbose

    async def execute_saga(self, saga: Saga) -> SagaResult:
        """Execute a saga and track it"""
        async with self._lock:
            self.sagas[saga.saga_id] = saga

        result = await saga.execute()

        if self.verbose:
            self.logger.info(
                f"Saga {saga.name} [{saga.saga_id}] finished with status: {result.status.value}"
            )

        return result

    async def get_saga(self, saga_id: str) -> Saga | None:
        """Get saga by ID"""
        async with self._lock:
            return self.sagas.get(saga_id)

    async def get_saga_status(self, saga_id: str) -> dict[str, Any] | None:
        """Get status of a saga by ID"""
        saga = await self.get_saga(saga_id)
        return saga.get_status() if saga else None

    async def get_all_sagas_status(self) -> list[dict[str, Any]]:
        """Get status of all sagas"""
        async with self._lock:
            return [saga.get_status() for saga in self.sagas.values()]

    async def count_by_status(self, status: SagaStatus) -> int:
        """Count sagas by status"""
        async with self._lock:
            return sum(1 for saga in self.sagas.values() if saga.status == status)

    async def count_completed(self) -> int:
        """Count completed sagas"""
        return await self.count_by_status(SagaStatus.COMPLETED)

    async def count_failed(self) -> int:
        """Count failed sagas (unrecoverable)"""
        return await self.count_by_status(SagaStatus.FAILED)

    async def count_rolled_back(self) -> int:
        """Count rolled back sagas (recovered)"""
        return await self.count_by_status(SagaStatus.ROLLED_BACK)

    async def get_statistics(self) -> dict[str, Any]:
        """Get orchestrator statistics"""
        async with self._lock:
            status_counts = self._count_saga_statuses()
            return {
                "total_sagas": len(self.sagas),
                **status_counts,
            }

    def _count_saga_statuses(self) -> dict[str, int]:
        """Count sagas by status."""
        from collections import Counter

        counts = Counter(saga.status for saga in self.sagas.values())
        return {
            "completed": counts.get(SagaStatus.COMPLETED, 0),
            "rolled_back": counts.get(SagaStatus.ROLLED_BACK, 0),
            "failed": counts.get(SagaStatus.FAILED, 0),
            "executing": counts.get(SagaStatus.EXECUTING, 0),
            "pending": counts.get(SagaStatus.PENDING, 0),
        }
