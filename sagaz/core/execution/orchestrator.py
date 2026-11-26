from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter
from typing import TYPE_CHECKING, Any

from sagaz.core.exceptions import SagaFailedError
from sagaz.core.saga import Saga, SagaResult
from sagaz.core.tenant import (
    TenantContext,
    TenantRegistry,
    resolve_tenant,
    tenant_argument,
    tenant_execution,
)
from sagaz.core.types import SagaStatus

if TYPE_CHECKING:
    from sagaz.core.decorators import Saga as DeclarativeSaga
    from sagaz.core.decorators._deadline import Deadline

# ============================================
# SAGA ORCHESTRATOR
# ============================================


class SagaOrchestrator:
    """Runs sagas and tracks their outcome.

    ``run(saga, context)`` runs a ``sagaz.Saga`` (#544); ``execute_saga(saga)`` runs
    the classic imperative ``sagaz.core.saga.Saga``. Both are tracked by saga id, and
    the status and statistics methods cover both.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        verbose: bool = False,
        *,
        tenant: TenantContext | str | None = None,
        tenant_registry: TenantRegistry | None = None,
        tenant_id: TenantContext | str | None = None,
    ) -> None:
        """Create an empty orchestrator.

        Args:
            logger: Optional pre-configured logger; defaults to module logger.
            verbose: Emit INFO log on every saga completion when ``True``.
            tenant: Run every saga as this tenant (ADR-020), a ``TenantContext`` or
                a tenant id: storage is scoped to it and its quotas apply. A tenant
                id is resolved through ``tenant_registry`` when one is given.
            tenant_registry: Registry used to resolve tenant ids.
            tenant_id: Deprecated name of ``tenant`` (until 3.0).
        """
        self.sagas: dict[str, Saga | DeclarativeSaga] = {}
        # sagaz.Saga keeps no status of its own: what each of its runs came to.
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.logger = logger or logging.getLogger(__name__)
        self.verbose = verbose
        given = tenant_argument("SagaOrchestrator", tenant, tenant_id=tenant_id)
        self.tenant = resolve_tenant(given, tenant_registry) if given is not None else None

    async def execute_saga(self, saga: Saga) -> SagaResult:
        """Execute a saga and track it"""
        async with self._lock:
            self.sagas[saga.saga_id] = saga

        if self.tenant is None:
            result = await saga.execute()
        else:
            async with tenant_execution(self.tenant):
                result = await saga.execute()

        if self.verbose:
            self.logger.info(
                f"Saga {saga.name} [{saga.saga_id}] finished with status: {result.status.value}"
            )

        return result

    async def run(
        self,
        saga: DeclarativeSaga,
        initial_context: dict[str, Any],
        saga_id: str | None = None,
        *,
        allow_rerun: bool = False,
        deadline: Deadline = None,
    ) -> dict[str, Any]:
        """Run a ``sagaz.Saga`` and track it (#544).

        As ``saga.run(initial_context, saga_id)``: returns the final context, and
        raises what it raises (``SagaFailedError`` when the saga fails). The
        orchestrator's tenant, if any, is the saga's. A saga id is generated when
        none is given, so that the run can be looked up.
        """
        saga_id = saga_id or str(uuid.uuid4())
        name = saga.saga_name or type(saga).__name__
        await self._track(saga_id, saga, name, SagaStatus.EXECUTING)
        try:
            context = await saga.run(
                initial_context,
                saga_id,
                tenant=self.tenant,
                allow_rerun=allow_rerun,
                deadline=deadline,
            )
        except SagaFailedError as failure:
            await self._track(saga_id, saga, name, failure.status, error=str(failure))
            self._log_finished(name, saga_id, failure.status)
            raise
        except BaseException as error:  # refused before running, or cancelled
            await self._track(saga_id, saga, name, SagaStatus.FAILED, error=str(error))
            raise
        await self._track(saga_id, saga, name, SagaStatus.COMPLETED)
        self._log_finished(name, saga_id, SagaStatus.COMPLETED)
        return context

    async def _track(
        self,
        saga_id: str,
        saga: DeclarativeSaga,
        name: str,
        status: SagaStatus,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            self.sagas[saga_id] = saga
            self._runs[saga_id] = {
                "saga_id": saga_id,
                "name": name,
                "status": status.value,
                "error": error,
            }

    def _log_finished(self, name: str, saga_id: str, status: SagaStatus) -> None:
        if self.verbose:
            self.logger.info(f"Saga {name} [{saga_id}] finished with status: {status.value}")

    async def get_saga(self, saga_id: str) -> Saga | DeclarativeSaga | None:
        """Get saga by ID"""
        async with self._lock:
            return self.sagas.get(saga_id)

    def _status(self, saga_id: str) -> dict[str, Any]:
        """A tracked saga's status: its run record, or the classic saga's own."""
        if saga_id in self._runs:
            return dict(self._runs[saga_id])
        saga = self.sagas[saga_id]
        assert isinstance(saga, Saga)  # only run() tracks a sagaz.Saga
        return saga.get_status()

    def _statuses(self) -> list[SagaStatus]:
        return [SagaStatus(self._status(saga_id)["status"]) for saga_id in self.sagas]

    async def get_saga_status(self, saga_id: str) -> dict[str, Any] | None:
        """Get status of a saga by ID"""
        async with self._lock:
            return self._status(saga_id) if saga_id in self.sagas else None

    async def get_all_sagas_status(self) -> list[dict[str, Any]]:
        """Get status of all sagas"""
        async with self._lock:
            return [self._status(saga_id) for saga_id in self.sagas]

    async def count_by_status(self, status: SagaStatus) -> int:
        """Count sagas by status"""
        async with self._lock:
            return self._statuses().count(status)

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
        counts = Counter(self._statuses())
        return {
            "completed": counts.get(SagaStatus.COMPLETED, 0),
            "rolled_back": counts.get(SagaStatus.ROLLED_BACK, 0),
            "partially_committed": counts.get(SagaStatus.PARTIALLY_COMMITTED, 0),
            "forward_recovery": counts.get(SagaStatus.FORWARD_RECOVERY, 0),
            "failed": counts.get(SagaStatus.FAILED, 0),
            "executing": counts.get(SagaStatus.EXECUTING, 0),
            "pending": counts.get(SagaStatus.PENDING, 0),
        }
