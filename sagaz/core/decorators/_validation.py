"""Checks of a declarative saga's definition (#536).

They run when a saga is created (decorated steps) and before it runs (steps
added with ``add_step``), so a mistake surfaces with a message that names the
step, not as a wrong error at run time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sagaz.core.exceptions import SagaDefinitionError

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
