"""
Mermaid diagram generation utilities for saga visualization.

This module provides a reusable MermaidGenerator class that can generate
Mermaid flowchart diagrams from saga step definitions.
"""

from __future__ import annotations

from collections.abc import Callable

from sagaz.observability.visualization._mermaid_edges import _EdgeRenderingMixin
from sagaz.observability.visualization._mermaid_models import HighlightTrail, StepInfo
from sagaz.observability.visualization._mermaid_nodes import _NodeRenderingMixin
from sagaz.observability.visualization._mermaid_styles import _StylingMixin

__all__ = ["HighlightTrail", "MermaidGenerator", "StepInfo"]


class MermaidGenerator(_NodeRenderingMixin, _EdgeRenderingMixin, _StylingMixin):
    """
    Generates Mermaid flowchart diagrams from saga step definitions.

    This class encapsulates all Mermaid generation logic to reduce complexity
    in the main Saga classes.
    """

    def __init__(
        self,
        steps: list[StepInfo],
        direction: str = "TB",
        show_compensation: bool = True,
        show_state_markers: bool = True,
        highlight_trail: HighlightTrail | None = None,
        show_pivot_zones: bool = True,
    ):
        """
        Initialise the generator with saga step metadata.

        Args:
            steps: Normalised step descriptors (name, deps, compensation flag).
            direction: Mermaid graph direction — ``TB`` (top-to-bottom),
                ``LR`` (left-to-right), etc.
            show_compensation: Include compensation subgraph in the diagram.
            show_state_markers: Render START / SUCCESS / ROLLED_BACK markers.
            highlight_trail: Optional execution trail for colouring visited nodes.
            show_pivot_zones: Highlight pivot (point-of-no-return) zones.
        """
        self.steps = steps
        self.direction = direction
        self.show_compensation = show_compensation
        self.show_state_markers = show_state_markers
        self.trail = highlight_trail or HighlightTrail()
        self.show_pivot_zones = show_pivot_zones

        self._step_map = {s.name: s for s in steps}
        self._compute_step_metadata()
        self._init_link_tracking()

    def _compute_step_metadata(self) -> None:
        """Compute derived properties from steps."""
        self._compensable_steps = self._filter_steps(lambda s: s.has_compensation)
        self._has_deps = any(s.depends_on for s in self.steps)

        all_deps = self._collect_all_dependencies()
        self._root_steps = self._filter_steps(lambda s: not s.depends_on)
        self._leaf_steps = self._filter_steps(lambda s: s.name not in all_deps)

        # v1.3.0: Pivot zone information
        self._pivot_steps = self._filter_steps(lambda s: s.pivot)
        self._tainted_steps = self._filter_steps(lambda s: s.tainted)
        self._has_pivots = bool(self._pivot_steps)

    def _filter_steps(self, predicate: Callable[[StepInfo], bool]) -> list[StepInfo]:
        """Filter steps by a predicate."""
        return [s for s in self.steps if predicate(s)]

    def _collect_all_dependencies(self) -> set[str]:
        """Collect all step names that are dependencies."""
        all_deps: set[str] = set()
        for step in self.steps:
            all_deps.update(step.depends_on)
        return all_deps

    def _init_link_tracking(self) -> None:
        """Initialize link tracking state."""
        self._lines: list[str] = []
        self._link_count = 0
        self._success_links: list[str] = []
        self._compensation_links: list[str] = []

    def generate(self) -> str:
        """Generate the complete Mermaid diagram."""
        self._lines = [f"flowchart {self.direction}"]

        # Add total duration as a comment if available
        if self.trail.total_duration:
            self._lines.append(f"    %% Total Duration: {self.trail.total_duration}")

        self._add_nodes()
        self._add_success_edges()
        self._add_failure_edges()
        self._add_styling()

        return "\n".join(self._lines)
