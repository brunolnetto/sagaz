"""StateChart phase 3: step charts for the declarative Saga (ADR-040, #522).

With ``use_step_statechart`` on (a ``Saga`` argument, a class attribute, or
``SagaConfig.use_step_statechart``), a run drives the same chart as the
imperative ``Saga`` (``sagaz.core.execution.step_statechart``): one region per
step, a ``tainted`` state for the ancestors of a completed pivot, and pivot
regions the chart refuses to compensate. The configuration is persisted with
the saga state, and after each compensated step as a checkpoint, so
:meth:`Saga.resume_compensation` can finish an interrupted compensation.
With the flag off nothing is sent or stored, as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sagaz.core.events import SagaFailed, SagaRolledBack
from sagaz.core.execution.step_statechart import (
    build_step_statechart,
    configuration_values,
    lifecycle_state,
    step_states,
    validate_configuration,
)
from sagaz.core.logger import get_logger
from sagaz.core.types import SagaStatus

if TYPE_CHECKING:
    from sagaz.core.decorators import Saga, SagaStepDefinition
    from sagaz.core.decorators._step_ledger import StepLedger

logger = get_logger("sagaz.core.decorators")

_UNDOABLE = ("completed", "compensating")  # what a resumed compensation may still undo


def _chart_class(steps: list[SagaStepDefinition]) -> Any:
    return build_step_statechart(
        tuple(step.step_id for step in steps),
        frozenset(step.step_id for step in steps if step.pivot),
    )


class _DecoratorStepChartMixin:
    """The chart a declarative saga's runs drive, and what it tells about them."""

    use_step_statechart: bool | None = None
    """Run on the phase 3 step chart (None: ``SagaConfig.use_step_statechart``)."""

    _config: Any
    _steps: list[SagaStepDefinition]
    _state_chart: Any

    def _init_step_chart(self, enabled: bool | None) -> None:
        if enabled is None:
            enabled = type(self).use_step_statechart
        if enabled is None:
            enabled = bool(getattr(self._config, "use_step_statechart", False))
        self.use_step_statechart = enabled
        self._state_chart = None

    @property
    def state_configuration(self) -> list[str]:
        """The last run's chart configuration (empty without the step chart)."""
        chart = self._state_chart
        return configuration_values(chart) if chart is not None else []

    def get_step_states(self) -> dict[str, str]:
        """Each step's state in the last run, while it runs (empty once it ended)."""
        return step_states([s.step_id for s in self._steps], self.state_configuration)

    def in_doubt_steps(self) -> list[str]:
        """Steps that were executing: whether their action took effect is unknown."""
        return [name for name, state in self.get_step_states().items() if state == "executing"]

    async def resume_compensation(self, saga_id: str) -> SagaStatus:
        """Finish compensating a run from its stored state (``SagaConfig.storage``).

        Compensates, in the compensation graph's order, the steps still
        ``completed`` or ``compensating`` (again: compensations must be
        idempotent). Tainted and pivot steps stay as they are; steps that were
        executing are logged as in doubt, never compensated. Returns the final
        status, ``ROLLED_BACK`` or ``FAILED``.
        """
        from sagaz.core.decorators._execution import ExecutionEngine

        return await ExecutionEngine(self).resume_compensation(saga_id)  # type: ignore[arg-type]


class _EngineStepChartMixin:
    """Step chart events for the execution engine (no-ops without a chart)."""

    saga: Saga
    _ledger: StepLedger
    _compensation_failed: bool

    if TYPE_CHECKING:

        def _get_saga_name(self) -> str: ...
        def _initialize_run(self, initial_context: dict[str, Any], saga_id: str | None) -> None: ...
        def _register_compensations(self) -> None: ...
        async def _open_recorder(self, saga_name: str) -> None: ...
        async def _record(self, event_type: Any, **fields: Any) -> None: ...
        async def _compensate(self) -> None: ...
        def _elapsed_ms(self, since: float | None = None) -> float: ...

    # The chart's guards read these from its host, the engine.
    @property
    def steps(self) -> list[SagaStepDefinition]:
        return self.saga._steps

    @property
    def completed_steps(self) -> list[str]:
        return [n for n, s in self._chart_step_states().items() if s in ("completed", "tainted")]

    @property
    def _chart(self) -> Any:
        return self.saga._state_chart

    def _chart_step_states(self) -> dict[str, str]:
        chart = self._chart
        if chart is None:
            return {}
        return step_states(chart.step_names, configuration_values(chart))

    async def _chart_open(self) -> None:
        """Start a fresh chart for this run, when the saga uses one."""
        self.saga._state_chart = None
        if not self.saga.use_step_statechart or not self.saga._steps:
            return
        chart = _chart_class(self.saga._steps)(self)
        await chart.activate_initial_state()
        await chart.start()
        self.saga._state_chart = chart

    async def _chart_step(self, step_id: str, event: str) -> None:
        chart = self._chart
        if chart is not None:
            await chart.send(f"s{chart.step_names.index(step_id)}__{event}")

    async def _chart_taint(self, step_ids: set[str]) -> None:
        states = self._chart_step_states()
        for step_id in sorted(step_ids):
            if states.get(step_id) == "completed":
                await self._chart_step(step_id, "taint")

    async def _chart_compensating(self, step_id: str) -> None:
        """A compensation starts (the chart refuses it for a pivot or a tainted step)."""
        if self._chart_step_states().get(step_id) in ("completed", "tainted"):
            await self._chart_step(step_id, "compensate")

    async def _chart_compensation_failed(self, step_id: str) -> None:
        if self._chart_step_states().get(step_id) == "compensating":
            await self._chart_step(step_id, "compensation_failed")

    def _lifecycle(self) -> str | None:
        chart = self._chart
        return None if chart is None else lifecycle_state(configuration_values(chart))

    async def _chart_succeeded(self) -> None:
        if self._lifecycle() == "executing":
            await self._chart.succeed()

    async def _chart_failed(self) -> None:
        """The run failed: compensate what completed, or end with nothing to undo."""
        if self._lifecycle() != "executing":
            return
        if self.completed_steps:
            await self._chart.fail()
        else:
            await self._chart.nothing_to_compensate()

    async def _chart_compensation_done(self) -> None:
        if self._lifecycle() != "compensating":
            return
        if self._compensation_failed:
            await self._chart.compensation_failed()
        else:
            await self._chart.finish_compensation()

    def _failure_status(self) -> SagaStatus:
        return SagaStatus.FAILED if self._compensation_failed else SagaStatus.ROLLED_BACK

    async def _persist(self, status: SagaStatus) -> None:
        """Store the saga state (and the configuration, under the step chart)."""
        storage = self.saga._config.storage if self.saga._config else None
        if not storage:
            return
        extra = {}
        if self._chart is not None:
            extra["configuration"] = configuration_values(self._chart)
        try:
            await storage.save_saga_state(
                self.saga._saga_id,
                self._get_saga_name(),
                status,
                self._ledger.snapshot(),
                self.saga._context,
                **extra,
            )
        except Exception as e:
            logger.warning(f"Failed to persist saga state ({status.value}): {e}")

    async def _checkpoint(self) -> None:
        """After a compensated step: the configuration to resume the compensation from."""
        if self._chart is not None:
            await self._persist(SagaStatus.COMPENSATING)

    # -- re-entry ----------------------------------------------------------------------

    async def resume_compensation(self, saga_id: str) -> SagaStatus:
        state = await self._load_resumable(saga_id)
        self._initialize_run(state.get("context") or {}, saga_id)
        self._ledger.restore(state.get("steps") or [])
        self._register_compensations()
        await self._restore_chart(list(state["configuration"]))
        doubt = self.saga.in_doubt_steps()
        if doubt:
            logger.warning(f"Saga {saga_id}: steps in doubt, not compensated: {doubt}")
        await self._open_recorder(self._get_saga_name())
        await self._chart_failed()
        await self._compensate()
        await self._chart_compensation_done()
        status = self._failure_status()
        if status == SagaStatus.FAILED:
            await self._record(
                SagaFailed, error_message="resumed compensation failed", duration_ms=0.0
            )
        else:
            await self._record(SagaRolledBack, duration_ms=self._elapsed_ms())
        await self._persist(status)
        return status

    async def _load_resumable(self, saga_id: str) -> dict[str, Any]:
        if not self.saga.use_step_statechart:
            msg = "resume_compensation needs use_step_statechart=True"
            raise ValueError(msg)
        storage = self.saga._config.storage if self.saga._config else None
        if storage is None:
            msg = "resume_compensation needs SagaConfig.storage"
            raise ValueError(msg)
        state = await storage.load_saga_state(saga_id)
        if state is None:
            msg = f"no stored state for saga {saga_id}"
            raise ValueError(msg)
        configuration = list(state.get("configuration") or [])
        validate_configuration([s.step_id for s in self.saga._steps], configuration)
        lifecycle = lifecycle_state(configuration)
        if lifecycle not in ("executing", "compensating"):
            msg = f"nothing to resume: saga {saga_id} already ended ({lifecycle})"
            raise ValueError(msg)
        return dict(state)

    async def _restore_chart(self, configuration: list[str]) -> None:
        """Bind the stored configuration (no callback runs) and the pivot bookkeeping."""
        from statemachine.model import Model
        from statemachine.orderedset import OrderedSet

        model = Model()
        model.state = OrderedSet(configuration)
        chart = _chart_class(self.saga._steps)(self, model=model)
        await chart.activate_initial_state()
        self.saga._state_chart = chart
        graph = self.saga._compensation_graph
        for step_id, state in self._chart_step_states().items():
            step = self.saga._step_registry[step_id]
            if state in (*_UNDOABLE, "tainted"):
                graph.mark_step_executed(step_id)
            if state == "tainted":
                self.saga._tainted_steps.add(step_id)
            if step.pivot and state in ("completed", "tainted"):
                self.saga._completed_pivots.add(step_id)
                self.saga._pivot_reached = True
