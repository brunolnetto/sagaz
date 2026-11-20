"""StateChart phase 2 on the imperative Saga (ADR-040, #190).

With ``use_step_statechart`` on, the saga runs on a chart with one region per
step (``sagaz.core.execution.step_statechart``): the configuration it reports
and persists says where every step is. The executor's existing points (a step
starts, succeeds, fails, is compensated) send the step events; with the flag
off nothing is sent and the flat phase 1 machine is used, as before.

It also gives the phase 2 re-entry guarantee: from a persisted configuration
and the ordered completed steps, a new ``Saga`` with the same step definitions
finishes the compensation in reverse completion order, without running again
the compensations that had succeeded. Steps that were still executing are
reported (:meth:`in_doubt_steps`), never compensated automatically, since
whether their action took effect is unknown. Resuming forward execution is
:class:`~sagaz.core.replay.SagaReplay`'s job.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sagaz.core.execution.step_statechart import (
    build_step_statechart,
    configuration_values,
    is_step_chart,
    lifecycle_state,
    step_states,
    validate_configuration,
)
from sagaz.core.types import SagaResult, SagaStatus

if TYPE_CHECKING:
    from sagaz.core.saga._step import SagaStep

logger = logging.getLogger("sagaz.core.saga")

_STATUS = {
    "pending": SagaStatus.PENDING,
    "executing": SagaStatus.EXECUTING,
    "compensating": SagaStatus.COMPENSATING,
    "completed": SagaStatus.COMPLETED,
    "rolled_back": SagaStatus.ROLLED_BACK,
    "failed": SagaStatus.FAILED,
}


def _default_flag() -> bool:
    """The global ``SagaConfig.use_step_statechart``, without creating a config."""
    from sagaz.core.config import _config

    config = _config._global_config
    return bool(config is not None and getattr(config, "use_step_statechart", False))


class _SagaStepChartMixin:
    """The phase 2 step chart: hooks for the executor, and compensation re-entry."""

    name: str
    status: SagaStatus
    steps: list[SagaStep]
    completed_steps: list[SagaStep]
    compensation_errors: list[Exception]
    context: Any
    _state_machine: Any

    if TYPE_CHECKING:

        async def _compensate_all(self) -> None: ...

    def _init_step_chart(self, enabled: bool | None) -> None:
        self.use_step_statechart = _default_flag() if enabled is None else enabled

    # -- the chart -------------------------------------------------------------------

    @property
    def _step_chart_on(self) -> bool:
        return is_step_chart(self._state_machine)

    def _arm_step_chart(self) -> None:
        """Use the step chart for the saga's steps (called right before ``start``)."""
        if not self.use_step_statechart:
            return
        chart = build_step_statechart(tuple(step.name for step in self.steps))
        if type(self._state_machine) is not chart:
            self._state_machine = chart(self)  # type: ignore[arg-type]  # a Saga

    def _step_states(self) -> dict[str, str]:
        if not self._step_chart_on:
            return {}
        return step_states(
            self._state_machine.step_names, configuration_values(self._state_machine)
        )

    async def _step_event(self, step_name: str, event: str) -> None:
        """Send a step's event to the chart (no-op without the step chart)."""
        if not self._step_chart_on:
            return
        index = self._state_machine.step_names.index(step_name)
        await self._state_machine.send(f"s{index}__{event}")

    async def _step_compensating(self, step_name: str) -> None:
        """A step's compensation starts (a step resumed in ``compensating`` already is)."""
        if self._step_states().get(step_name) == "completed":
            await self._step_event(step_name, "compensate")

    async def _fail_running_steps(self, step_names: Any) -> None:
        """Steps still ``executing`` after a parallel batch ended were cancelled."""
        states = self._step_states()
        for name in step_names:
            if states.get(name) == "executing":
                await self._step_event(name, "fail")

    # -- re-entry ----------------------------------------------------------------------

    async def restore_state(self, configuration: list[str], completed_steps: list[str]) -> None:
        """Restore a persisted run: its configuration and its completed steps, in order.

        Needs the step chart, the same step definitions, and a configuration of
        this saga's chart (``ValueError`` otherwise). No callback runs.
        """
        from statemachine.model import Model
        from statemachine.orderedset import OrderedSet

        if not self.use_step_statechart:
            msg = "restore_state needs use_step_statechart=True"
            raise ValueError(msg)
        names = tuple(step.name for step in self.steps)
        validate_configuration(names, configuration)
        by_name = {step.name: step for step in self.steps}
        unknown = [name for name in completed_steps if name not in by_name]
        if unknown:
            msg = f"completed steps not in this saga: {unknown}"
            raise ValueError(msg)
        model = Model()
        model.state = OrderedSet(configuration)
        chart = build_step_statechart(names)
        self._state_machine = chart(self, model=model)  # type: ignore[arg-type]  # a Saga
        await self._state_machine.activate_initial_state()
        self.completed_steps = [by_name[name] for name in completed_steps]
        self.status = _STATUS[lifecycle_state(configuration)]

    def pending_compensations(self) -> list[str]:
        """Completed steps still to compensate, in the order they will be (reverse)."""
        states = self._step_states()
        return [
            step.name
            for step in reversed(self.completed_steps)
            if step.compensation and states.get(step.name) in ("completed", "compensating")
        ]

    def in_doubt_steps(self) -> list[str]:
        """Steps that were executing: whether their action took effect is unknown."""
        return [name for name, state in self._step_states().items() if state == "executing"]

    async def resume_compensation(self) -> SagaResult:
        """Finish compensating a restored run (see :meth:`restore_state`)."""
        if not self._step_chart_on:
            msg = "resume_compensation needs a run restored with restore_state"
            raise ValueError(msg)
        started = datetime.now()
        lifecycle = lifecycle_state(configuration_values(self._state_machine))
        if lifecycle == "executing":
            if not self.pending_compensations():
                await self._state_machine.nothing_to_compensate()
                return self._resume_result(SagaStatus.ROLLED_BACK, started)
            await self._state_machine.fail()
        elif lifecycle != "compensating":
            msg = f"nothing to resume: the saga already ended ({lifecycle})"
            raise ValueError(msg)
        from sagaz.core.exceptions import SagaCompensationError

        pending = set(self.pending_compensations())
        self.completed_steps = [step for step in self.completed_steps if step.name in pending]
        try:
            await self._compensate_all()
        except SagaCompensationError:
            await self._state_machine.compensation_failed()
            return self._resume_result(SagaStatus.FAILED, started)
        await self._state_machine.finish_compensation()
        return self._resume_result(SagaStatus.ROLLED_BACK, started)

    def _resume_result(self, status: SagaStatus, started: datetime) -> SagaResult:
        return SagaResult(
            success=False,
            saga_name=self.name,
            status=status,
            completed_steps=len(self.completed_steps),
            total_steps=len(self.steps),
            execution_time=(datetime.now() - started).total_seconds(),
            context=self.context,
            compensation_errors=self.compensation_errors,
        )
