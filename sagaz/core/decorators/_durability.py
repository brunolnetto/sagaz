"""Saving a declarative saga's state, and what happens when it fails (#534, #535).

- **Start:** the saga is created in storage with an atomic insert. A ``saga_id``
  that already exists raises :class:`SagaAlreadyExistsError` before any step runs,
  so a retried request cannot charge twice.
- **Progress:** the state is saved after each level of steps (after each step,
  in a sequential saga), so a crash leaves a record of what already ran.
- **Failures to save** raise :class:`SagaPersistenceError`: a saga that cannot
  record its progress stops (and compensates what ran). With
  ``SagaConfig(tolerate_persistence_errors=True)`` they are logged instead, as
  before 2.4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sagaz.core.exceptions import SagaAlreadyExistsError, SagaPersistenceError
from sagaz.core.logger import get_logger
from sagaz.core.types import SagaStatus

if TYPE_CHECKING:
    from sagaz.core.decorators import Saga
    from sagaz.core.decorators._step_ledger import StepLedger

logger = get_logger("sagaz.core.decorators")


class _DurabilityMixin:
    """Saves the saga state for the execution engine."""

    saga: Saga
    _ledger: StepLedger
    allow_rerun: bool = False
    """Run an existing ``saga_id`` again (``Saga.run(..., allow_rerun=True)``)."""

    if TYPE_CHECKING:

        def _get_saga_name(self) -> str: ...

        def _configuration_to_store(self) -> list[str] | None: ...

    def _storage(self) -> Any:
        return self.saga._config.storage if self.saga._config else None

    def _tolerates_storage_errors(self) -> bool:
        return getattr(self.saga._config, "tolerate_persistence_errors", False) is True

    def _state(self, status: SagaStatus) -> tuple[tuple[Any, ...], dict[str, Any]]:
        args = (
            self.saga._saga_id,
            self._get_saga_name(),
            status,
            self._ledger.snapshot(),
            self.saga._context,
        )
        configuration = self._configuration_to_store()
        return args, ({"configuration": configuration} if configuration else {})

    def _storage_failed(self, phase: str, error: Exception) -> None:
        if self._tolerates_storage_errors():
            logger.warning(f"Failed to persist saga state ({phase}): {error}")
            return
        raise SagaPersistenceError(self.saga._saga_id, phase, error) from error

    async def _persist_new(self) -> None:
        """Create the saga in storage; refuse a ``saga_id`` that already exists."""
        storage = self._storage()
        if not storage:
            return
        args, extra = self._state(SagaStatus.EXECUTING)
        create = getattr(storage, "create_saga_state", None)
        try:
            if create is None:  # a duck-typed storage without the 2.4 method
                await storage.save_saga_state(*args, **extra)
                return
            created = await create(*args, **extra)
        except Exception as e:
            self._storage_failed("start", e)
            return
        if created is False and self.allow_rerun:
            await self._persist(SagaStatus.EXECUTING, "start")  # an explicit rerun
            return
        if created is False:
            existing = await storage.load_saga_state(self.saga._saga_id)
            status = existing.get("status") if isinstance(existing, dict) else None
            raise SagaAlreadyExistsError(self.saga._saga_id, status)

    async def _persist(self, status: SagaStatus, phase: str | None = None) -> None:
        """Save the saga state (and the chart configuration, under the step chart)."""
        storage = self._storage()
        if not storage:
            return
        args, extra = self._state(status)
        try:
            await storage.save_saga_state(*args, **extra)
        except Exception as e:
            self._storage_failed(phase or status.value, e)

    async def _persist_outcome(self, status: SagaStatus, error: BaseException) -> None:
        """Save a failed run's outcome without replacing the exception being raised."""
        try:
            await self._persist(status)
        except SagaPersistenceError as persistence_error:
            logger.error(str(persistence_error))
            error.add_note(f"sagaz: {persistence_error}")
