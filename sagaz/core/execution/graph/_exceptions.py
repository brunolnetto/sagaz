"""Exceptions for the saga execution graph."""


class CompensationGraphError(Exception):
    """Base exception for compensation graph errors."""


class CircularDependencyError(CompensationGraphError):
    """Raised when circular dependencies are detected in the graph."""

    def __init__(self, cycle: list[str]):
        """Record the full cycle path for diagnostic messages."""
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle)}")


class MissingDependencyError(CompensationGraphError):
    """Raised when a step depends on a non-existent step."""

    def __init__(self, step_id: str, missing_dep: str):
        """Record the dependant step and the absent dependency name."""
        self.step_id = step_id
        self.missing_dep = missing_dep
        super().__init__(f"Step '{step_id}' depends on non-existent step '{missing_dep}'")
