"""StateChart phase 2: a saga chart with one region per step (ADR-040, #190).

With ``Saga(use_step_statechart=True)`` the saga lifecycle and its steps are
orthogonal regions of one chart, so the persisted configuration says where each
step is, not only the saga:

```
pending                                  (initial)
active (parallel)
├── lifecycle: executing ─fail→ compensating
└── steps (parallel)
    └── step/<name>: pending → executing → completed → compensating → compensated
                                   ↘ failed     ↓ taint    ↘ compensation_failed
                                              tainted (locked: an ancestor of a pivot)
                     pending → completed ("adopt": restored or idempotent steps)
completed | rolled_back | failed         (final; the configuration is flat again)
```

Pivot/taint (phase 3, ADR-023): a pivot step's region has no ``compensate``
transition, and a completed step becomes ``tainted`` once a pivot that depends on
it completes. The chart itself refuses to compensate either.

The saga-level events and guards are phase 1's (``start``, ``succeed``, ``fail``,
``fail_unrecoverable``, ``finish_compensation``, ``compensation_failed``,
``nothing_to_compensate``), with the same runtime contract. Step events are
``s<i>__<event>`` for the step at position ``i``. State values are what gets
persisted: ``step/<percent-encoded name>[/<sub-state>]``, so any step name is safe
and stable.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from statemachine import State
from statemachine.factory import StateMachineMetaclass
from statemachine.state import NestedStateFactory

from sagaz.core.execution.state_machine import _SagaChartBase

STEP_STATES = (
    "pending",
    "executing",
    "completed",
    "failed",
    "compensating",
    "compensated",
    "compensation_failed",
    "tainted",
)
_COMPENSATION_STATES = frozenset({"compensating", "compensated", "compensation_failed"})
_FINAL_STEP_STATES = frozenset({"failed", "compensated", "compensation_failed"})
_STEP_EVENTS = {
    "start": ("pending", "executing"),
    "succeed": ("executing", "completed"),
    "fail": ("executing", "failed"),
    "adopt": ("pending", "completed"),
    "compensate": ("completed", "compensating"),
    "compensated": ("compensating", "compensated"),
    "compensation_failed": ("compensating", "compensation_failed"),
    "taint": ("completed", "tainted"),
}
LIFECYCLE_STATES = ("executing", "compensating")
FINAL_STATES = ("completed", "rolled_back", "failed")


def step_state_value(step_name: str, sub_state: str | None = None) -> str:
    """The persisted value of a step's region (or of one of its sub-states)."""
    value = f"step/{quote(step_name, safe='')}"
    return value if sub_state is None else f"{value}/{sub_state}"


def _step_region(index: int, name: str, pivot: bool = False) -> Any:
    # A completed pivot is a point of no return: its region has no compensation.
    subs = [sub for sub in STEP_STATES if not (pivot and sub in _COMPENSATION_STATES)]
    states = {
        sub: State(
            value=step_state_value(name, sub),
            initial=sub == "pending",
            final=sub in _FINAL_STEP_STATES,
        )
        for sub in subs
    }
    attrs: dict[str, Any] = {f"s{index}_{sub}": state for sub, state in states.items()}
    for event, (source, target) in _STEP_EVENTS.items():
        if source not in states or target not in states:
            continue
        attrs[f"s{index}__{event}"] = states[source].to(states[target])
    return NestedStateFactory(
        f"s{index}", (State.Compound,), attrs, name=name, value=step_state_value(name)
    )


@lru_cache(maxsize=128)
def build_step_statechart(
    step_names: tuple[str, ...], pivots: frozenset[str] = frozenset()
) -> type[_SagaChartBase]:
    """The chart class for a saga with these steps and pivot steps (built once, cached)."""
    if len(set(step_names)) != len(step_names):
        msg = f"step names must be unique, got {list(step_names)}"
        raise ValueError(msg)
    if not pivots <= set(step_names):
        msg = f"pivots must be steps of the saga: {sorted(pivots - set(step_names))}"
        raise ValueError(msg)
    lifecycle_states = {
        "executing": State(initial=True, value="executing"),
        "compensating": State(value="compensating"),
    }
    lifecycle = NestedStateFactory(
        "lifecycle", (State.Compound,), dict(lifecycle_states), value="lifecycle"
    )
    steps = NestedStateFactory(
        "steps",
        (State.Parallel,),
        {f"s{i}": _step_region(i, name, name in pivots) for i, name in enumerate(step_names)},
        value="steps",
    )
    active = NestedStateFactory(
        "active", (State.Parallel,), {"lifecycle": lifecycle, "steps": steps}, value="active"
    )
    pending = State(initial=True, value="pending")
    finals = {name: State(final=True, value=name) for name in FINAL_STATES}
    executing, compensating = lifecycle_states["executing"], lifecycle_states["compensating"]
    attrs: dict[str, Any] = {"pending": pending, "active": active, **finals}
    attrs["start"] = pending.to(active, cond="has_steps")
    attrs["succeed"] = executing.to(finals["completed"])
    attrs["fail"] = executing.to(compensating, cond="has_completed_steps")
    attrs["fail_unrecoverable"] = executing.to(finals["failed"])
    attrs["finish_compensation"] = compensating.to(finals["rolled_back"])
    attrs["compensation_failed"] = compensating.to(finals["failed"])
    attrs["nothing_to_compensate"] = executing.to(finals["rolled_back"])
    attrs["step_names"] = step_names
    attrs["pivots"] = pivots
    # The metaclass builds a _SagaChartBase subclass.
    return StateMachineMetaclass(  # type: ignore[return-value]
        f"SagaStepChart{len(step_names)}", (_SagaChartBase,), attrs
    )


def is_step_chart(machine: object) -> bool:
    """Whether *machine* is a phase 2 step chart (its class carries the step names)."""
    return isinstance(getattr(type(machine), "step_names", None), tuple)


def configuration_values(machine: Any) -> list[str]:
    """The active state values, in document order (deterministic for persistence)."""
    active = {str(v) for v in machine.configuration_values}
    return [str(value) for value in machine.states_map if str(value) in active]


def lifecycle_state(values: Iterable[str]) -> str:
    """The saga-level state of a configuration: pending, executing, compensating or final."""
    active = set(values)
    for name in (*FINAL_STATES, "compensating", "executing", "pending"):
        if name in active:
            return name
    msg = f"no lifecycle state in configuration {sorted(active)}"
    raise ValueError(msg)


def step_states(step_names: Sequence[str], values: Iterable[str]) -> dict[str, str]:
    """Each step's sub-state in a running configuration (empty once the saga ended)."""
    active = set(values)
    states: dict[str, str] = {}
    for name in step_names:
        for sub in STEP_STATES:
            if step_state_value(name, sub) in active:
                states[name] = sub
    return states


def validate_configuration(step_names: Sequence[str], values: Sequence[str]) -> None:
    """Raise ``ValueError`` unless *values* is a configuration the chart can be in.

    The library restores any set of states it is given; a corrupted or foreign
    configuration must not be, so this checks it is one of the chart's own.
    """
    active = set(values)
    if len(active) == 1 and active <= {"pending", *FINAL_STATES}:
        return
    lifecycle = active & set(LIFECYCLE_STATES)
    expected = {"active", "lifecycle", "steps", *lifecycle}
    if len(lifecycle) != 1:
        msg = f"a running configuration needs exactly one of {LIFECYCLE_STATES}: {sorted(active)}"
        raise ValueError(msg)
    for name in step_names:
        subs = [sub for sub in STEP_STATES if step_state_value(name, sub) in active]
        if len(subs) != 1:
            msg = f"step {name!r} must be in exactly one state, found {subs}"
            raise ValueError(msg)
        expected |= {step_state_value(name), step_state_value(name, subs[0])}
    if active != expected:
        msg = f"unknown or missing states in configuration: {sorted(active ^ expected)}"
        raise ValueError(msg)
