"""Checks of a declarative saga's definition (#536).

They run when a saga is created (decorated steps) and before it runs (steps
added with ``add_step``), so a mistake surfaces with a message that names the
step, not as a wrong error at run time.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from sagaz.core.exceptions import ParallelPivotsWarning, SagaDefinitionError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sagaz.core.decorators import SagaStepDefinition


def check_dependencies(steps: Sequence[SagaStepDefinition]) -> None:
    """Raise ``SagaDefinitionError`` for a dependency on no step, or a cycle (with its path)."""
    names = {step.step_id for step in steps}
    for step in steps:
        missing = [dep for dep in step.depends_on if dep not in names]
        if missing:
            msg = f"step {step.step_id!r} depends on unknown step(s) {missing}; steps: {sorted(names)}"
            raise SagaDefinitionError(msg)
    cycle = find_cycle({step.step_id: list(step.depends_on) for step in steps})
    if cycle:
        msg = f"dependency cycle: {' -> '.join(cycle)}"
        raise SagaDefinitionError(msg)


def find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """A cycle in ``graph`` (node -> its dependencies) as a path ``[a, b, ..., a]``, or None."""
    visiting: list[str] = []
    done: set[str] = set()

    def visit(node: str) -> list[str] | None:
        if node in done:
            return None
        if node in visiting:
            return [*visiting[visiting.index(node) :], node]
        visiting.append(node)
        for dep in graph.get(node, []):
            cycle = visit(dep)
            if cycle:
                return cycle
        visiting.pop()
        done.add(node)
        return None

    for node in sorted(graph):
        cycle = visit(node)
        if cycle:
            return list(reversed(cycle))  # in execution order: a runs before b ...
    return None


def parallel_pivots(steps: Sequence[SagaStepDefinition]) -> list[tuple[str, str]]:
    """Pairs of pivot steps where neither depends on the other, directly or not (#679)."""
    by_name = {step.step_id: step for step in steps}

    def ancestors(name: str) -> set[str]:
        seen: set[str] = set()
        todo = list(by_name[name].depends_on)
        while todo:
            current = todo.pop()
            if current not in seen and current in by_name:
                seen.add(current)
                todo.extend(by_name[current].depends_on)
        return seen

    pivots = sorted(step.step_id for step in steps if step.pivot)
    before = {name: ancestors(name) for name in pivots}
    return [
        (first, second)
        for index, first in enumerate(pivots)
        for second in pivots[index + 1 :]
        if first not in before[second] and second not in before[first]
    ]


def warn_parallel_pivots(saga_name: str, steps: Sequence[SagaStepDefinition]) -> None:
    """Warn that pivots in parallel branches commit in the order they happen to complete.

    The rule is well defined (a step stays if it is a completed pivot or an ancestor of
    one), but its outcome depends on timing: if one branch fails just before the other's
    pivot completes, everything is rolled back; just after, one irreversible action
    stands without the other.
    """
    for first, second in parallel_pivots(steps):
        warnings.warn(
            f"saga {saga_name!r}: the pivots {first!r} and {second!r} are in parallel "
            "branches. If one branch fails, which of them stays done depends on the order "
            "they complete in. Chain them with depends_on if they must commit together.",
            ParallelPivotsWarning,
            stacklevel=4,
        )
