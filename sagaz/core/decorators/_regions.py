"""Running region-assigned steps through the multi-region coordinator (ADR-034, #59)."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from sagaz.core.regions._protocol import ACTION, COMPENSATION

if TYPE_CHECKING:
    from sagaz.core.decorators import Saga, SagaStepDefinition
    from sagaz.core.regions import MultiRegionCoordinator


class _RegionRoutingMixin:
    """Runs a step locally, or in its region's workers when it declares one."""

    saga: Saga

    def _coordinator(self) -> MultiRegionCoordinator | None:
        from sagaz.core.regions import MultiRegionCoordinator

        coordinator = getattr(self.saga._config, "regions", None)
        return coordinator if isinstance(coordinator, MultiRegionCoordinator) else None

    def _check_regions(self) -> None:
        """Fail before the saga starts if a step's region cannot be served."""
        regional = [s for s in self.saga._steps if s.region is not None]
        if not regional:
            return
        coordinator = self._coordinator()
        if coordinator is None:
            names = ", ".join(f"{s.step_id} ({s.region})" for s in regional)
            msg = f"Steps declare a region but SagaConfig.regions has no coordinator: {names}"
            raise ValueError(msg)
        for step in regional:
            coordinator.registry.get(step.region or "")  # unknown region: ValueError

    async def _run_step(self, step: SagaStepDefinition, kind: str = ACTION) -> Any:
        fn = step.forward_fn if kind == ACTION else step.compensation_fn
        assert fn is not None
        coordinator = self._coordinator() if step.region is not None else None
        if coordinator is None or step.region is None:
            return await _call(fn, self.saga._context)
        target = coordinator.target(step.region)
        if target == coordinator.home:
            return await _call(fn, self.saga._context)
        return await coordinator.run(
            target,
            saga_name=self.saga.saga_name or type(self.saga).__name__,
            saga_id=self.saga._saga_id,
            step=step.step_id,
            kind=kind,
            context=self.saga._context,
            declared=step.region,
        )

    async def _run_compensation(self, step_id: str, fallback: Any) -> Any:
        step = self.saga._step_registry.get(step_id)
        if step is None or step.region is None or step.compensation_fn is None:
            return await _call(fallback, self.saga._context)
        return await self._run_step(step, COMPENSATION)


async def _call(fn: Any, context: object) -> Any:
    """Call a step or compensation; a plain (sync) function works too (#536)."""
    result = fn(context)
    if inspect.isawaitable(result):
        result = await result
    return result
