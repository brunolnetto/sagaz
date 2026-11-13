"""Saga configuration validation for the dry-run engine (ADR-019)."""

from typing import Any

from sagaz._dry_run_types import ValidationResult, _StepIntrospection


class _DryRunValidationMixin(_StepIntrospection):
    """Validation phase of :class:`sagaz.dry_run.DryRunEngine`."""

    async def _validate(
        self,
        saga: object,
        context: dict[str, Any],  # type: ignore
    ) -> ValidationResult:
        """Validate saga configuration."""
        errors = []
        warnings: list[str] = []
        checks: dict[str, Any] = {}

        steps = self._extract_steps(saga)
        if not steps:
            errors.append("Saga has no steps defined")
            checks["has_steps"] = False
            return ValidationResult(errors=errors, warnings=warnings, checks=checks)

        checks["has_steps"] = True
        checks["step_count"] = len(steps)
        step_names = self._get_step_names(steps)
        checks["step_names"] = sorted(step_names)

        has_dependencies, has_compensation = self._validate_steps(
            steps, step_names, errors, warnings
        )
        checks["has_dependencies"] = has_dependencies
        checks["has_compensation"] = has_compensation

        self._validate_context_fields(saga, context, checks, errors)
        self._validate_cycles(steps, checks, errors)

        return ValidationResult(errors=errors, warnings=warnings, checks=checks)

    def _get_step_names(self, steps: list) -> set[str]:
        """Get step names from steps."""
        return {str(getattr(step, "step_id", None) or getattr(step, "name", "")) for step in steps}

    def _validate_steps(
        self, steps: list, step_names: set[str], errors: list, warnings: list
    ) -> tuple[bool, bool]:
        """Validate individual steps and return (has_dependencies, has_compensation)."""
        has_dependencies = False
        has_compensation = False

        for step in steps:
            step_name: str = str(getattr(step, "step_id", None) or getattr(step, "name", "unknown"))
            depends_on: Any = getattr(step, "depends_on", set()) or getattr(
                step, "dependencies", set()
            )

            if depends_on:
                has_dependencies = True
                for dep in depends_on:
                    if dep not in step_names:
                        errors.append(f"Step '{step_name}' depends on unknown step '{dep}'")

            compensation_fn = getattr(step, "compensation_fn", None) or getattr(
                step, "compensation", None
            )
            if compensation_fn is not None:
                has_compensation = True
            elif getattr(step, "requires_compensation", False):
                warnings.append(f"Step '{step_name}' requires compensation but none defined")

        return has_dependencies, has_compensation

    def _validate_context_fields(
        self,
        saga: object,
        context: dict[str, Any],
        checks: dict,
        errors: list,  # type: ignore
    ):
        """Validate required context fields."""
        checks["required_context_fields"] = []
        if hasattr(saga, "required_context_fields"):
            checks["required_context_fields"] = list(saga.required_context_fields)
            missing = set(saga.required_context_fields) - set(context.keys())
            if missing:
                errors.append(f"Missing required context fields: {sorted(missing)}")

    def _validate_cycles(self, steps: list, checks: dict, errors: list):
        """Build DAG and check for cycles."""
        dag: dict[str, list[str]] = {}
        for step in steps:
            step_name: str = str(getattr(step, "step_id", None) or getattr(step, "name", "unknown"))
            depends_on: Any = getattr(step, "depends_on", set()) or getattr(
                step, "dependencies", set()
            )
            dag[step_name] = list(depends_on) if depends_on else []

        checks["has_cycles"] = False
        if dag and any(deps for deps in dag.values()):
            cycles = self._detect_cycles(dag)
            if cycles:
                checks["has_cycles"] = True
                errors.append(f"Circular dependencies detected: {cycles}")

    def _detect_cycles(self, dag: dict[str, list[str]]) -> list[list[str]]:
        """Detect cycles in DAG using DFS.

        Args:
            dag: Adjacency list representation {step: [dependencies]}

        Returns:
            List of cycles found (empty if no cycles)
        """
        cycles = []
        visited = set()
        rec_stack = set()

        def dfs(node: str, path: list[str]):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in dag.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path[:])
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycles.append([*path[cycle_start:], neighbor])

            rec_stack.remove(node)

        for node in dag:
            if node not in visited:
                dfs(node, [])

        return cycles
