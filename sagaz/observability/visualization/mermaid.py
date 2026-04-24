"""
Mermaid diagram generation utilities for saga visualization.

This module provides a reusable MermaidGenerator class that can generate
Mermaid flowchart diagrams from saga step definitions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StepInfo:
    """Normalized step information for Mermaid generation."""

    name: str
    has_compensation: bool
    depends_on: set[str] = field(default_factory=set)
    # v1.3.0: Pivot support
    pivot: bool = False
    """True if this step is a pivot (point of no return)."""
    tainted: bool = False
    """True if this step is tainted (ancestor of completed pivot)."""


@dataclass
class HighlightTrail:
    """Execution trail information for highlighting."""

    completed: set[str] = field(default_factory=set)
    failed_step: str | None = None
    compensated: set[str] = field(default_factory=set)
    step_durations: dict[str, str] = field(default_factory=dict)  # step_name -> "120ms"
    comp_durations: dict[str, str] = field(
        default_factory=dict
    )  # step_name -> "50ms" (for compensation)
    total_duration: str | None = None  # Overall saga duration

    @classmethod
    def from_dict(cls, data: dict | None) -> HighlightTrail:
        """Create from dictionary or return empty trail."""
        if not data:
            return cls()
        return cls(
            completed=set(data.get("completed_steps", [])),
            failed_step=data.get("failed_step"),
            compensated=set(data.get("compensated_steps", [])),
            step_durations=data.get("step_durations", {}),
            comp_durations=data.get("comp_durations", {}),
            total_duration=data.get("total_duration"),
        )


class DiagramState:
    """Helper to manage the state of the diagram being built."""

    def __init__(self, direction: str):
        self.lines: list[str] = [f"flowchart {direction}"]
        self.link_count = 0
        self.success_links: list[str] = []
        self.compensation_links: list[str] = []

    def add_line(self, line: str) -> None:
        """Add a raw line to the diagram."""
        self.lines.append(f"    {line}")

    def add_comment(self, comment: str) -> None:
        """Add a Mermaid comment."""
        self.add_line(f"%% {comment}")

    def add_link(
        self, src: str, arrow: str, dst: str, highlight: bool = False, link_type: str = "success"
    ) -> None:
        """Add a link and track its ID for styling."""
        self.add_line(f"{src} {arrow} {dst}")
        if highlight:
            if link_type == "compensation":
                self.compensation_links.append(str(self.link_count))
            else:
                self.success_links.append(str(self.link_count))
        self.link_count += 1

    def render(self) -> str:
        """Return the complete diagram string."""
        return "\n".join(self.lines)


class NodeRenderer:
    """Handles generation of node definitions and shapes."""

    def __init__(self, trail: HighlightTrail):
        self.trail = trail

    def get_step_shape(self, step: StepInfo) -> str:
        """Determine the Mermaid node shape for a step."""
        is_root = not step.depends_on
        duration = self.trail.step_durations.get(step.name)

        label = f"{step.name}<br/>{duration}" if duration else step.name
        # Use quoted labels for safety with special chars
        label_fmt = f'"{label}"' if duration else label

        if is_root:
            return f"([{label_fmt}])"
        if step.has_compensation:
            return f"[{label_fmt}]"
        return f"[/{label_fmt}/]"

    def get_comp_shape(self, step: StepInfo) -> str:
        """Determine the shape for a compensation node."""
        duration = self.trail.comp_durations.get(step.name)
        label = f"undo {step.name}<br/>{duration}" if duration else f"undo {step.name}"
        return f"{{{{{label}}}}}"


class MermaidGenerator:
    """
    Generates Mermaid flowchart diagrams from saga step definitions.
    Refactored for better maintainability (v1.6.1).
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
        self.steps = steps
        self.direction = direction
        self.show_compensation = show_compensation
        self.show_state_markers = show_state_markers
        self.trail = highlight_trail or HighlightTrail()
        self.show_pivot_zones = show_pivot_zones

        self._step_map = {s.name: s for s in steps}
        self._node_renderer = NodeRenderer(self.trail)
        self._compute_metadata()

    def _compute_metadata(self) -> None:
        """Pre-calculate properties to simplify generation logic."""
        self._compensable_steps = [s for s in self.steps if s.has_compensation]
        self._has_deps = any(s.depends_on for s in self.steps)
        self._root_steps = [s for s in self.steps if not s.depends_on]
        self._identify_leaf_steps()
        self._identify_pivots()

    def _identify_leaf_steps(self) -> None:
        """Identify steps that are not dependencies of any other step."""
        all_deps: set[str] = set()
        for s in self.steps:
            all_deps.update(s.depends_on)
        self._leaf_steps = [s for s in self.steps if s.name not in all_deps]

    def _identify_pivots(self) -> None:
        """Identify pivot steps and check trail existence."""
        self._pivot_steps = [s for s in self.steps if s.pivot]
        self._has_pivots = bool(self._pivot_steps)
        self._has_trail = bool(self.trail.completed or self.trail.failed_step or self.trail.compensated)

    def generate(self) -> str:
        """Generate the complete Mermaid diagram."""
        state = DiagramState(self.direction)

        if self.trail.total_duration:
            state.add_comment(f"Total Duration: {self.trail.total_duration}")

        self._add_nodes(state)
        self._add_edges(state)
        self._add_styling(state)

        return state.render()

    def _add_nodes(self, state: DiagramState) -> None:
        """Add all nodes: START, steps, compensation, and end markers."""
        if self.show_state_markers:
            state.add_line("START((●))")

        for step in self.steps:
            if self._has_trail and not self._is_step_touched(step):
                continue
            state.add_line(f"{step.name}{self._node_renderer.get_step_shape(step)}")

        self._add_end_markers(state)
        self._add_compensation_nodes(state)

    def _is_step_touched(self, step: StepInfo) -> bool:
        """Check if step was part of the execution trail."""
        return step.name in self.trail.completed or step.name == self.trail.failed_step

    def _add_end_markers(self, state: DiagramState) -> None:
        """Add SUCCESS and/or ROLLED_BACK markers."""
        if not self.show_state_markers:
            return

        duration_label = f'"{self.trail.total_duration}"' if self.trail.total_duration else "◎"

        if self._has_trail:
            if self.trail.failed_step:
                label = f'("✗ {self.trail.total_duration}")' if self.trail.total_duration else "((◎))"
                state.add_line(f"ROLLED_BACK{label}")
            else:
                label = f'("✓ {self.trail.total_duration}")' if self.trail.total_duration else "((◎))"
                state.add_line(f"SUCCESS{label}")
        else:
            state.add_line("SUCCESS((◎))")
            if self.show_compensation and self._compensable_steps:
                state.add_line("ROLLED_BACK((◎))")

    def _add_compensation_nodes(self, state: DiagramState) -> None:
        """Add compensation nodes if applicable."""
        if not self.show_compensation:
            return

        for step in self._compensable_steps:
            if self._has_trail and step.name not in self.trail.compensated:
                continue
            state.add_line(f"comp_{step.name}{self._node_renderer.get_comp_shape(step)}")

    def _add_edges(self, state: DiagramState) -> None:
        """Add all diagram edges."""
        self._add_success_edges(state)
        self._add_failure_edges(state)

    def _add_success_edges(self, state: DiagramState) -> None:
        """Add forward execution edges."""
        self._add_start_edges(state)
        self._add_step_to_step_edges(state)
        self._add_success_marker_edges(state)

    def _add_start_edges(self, state: DiagramState) -> None:
        """Add edges from START to root steps."""
        if not self.show_state_markers:
            return
        for root in self._root_steps:
            executed = self._is_step_touched(root)
            if self._has_trail and not executed:
                continue
            state.add_link("START", "-->", root.name, highlight=executed)

    def _add_step_to_step_edges(self, state: DiagramState) -> None:
        """Add edges between steps based on dependencies or sequence."""
        for step in self.steps:
            for dep in sorted(step.depends_on) if self._has_deps else []:
                self._add_step_link(state, dep, step.name)

        if not self._has_deps:
            for i in range(len(self.steps) - 1):
                self._add_step_link(state, self.steps[i].name, self.steps[i + 1].name)

    def _add_success_marker_edges(self, state: DiagramState) -> None:
        """Add edges from leaf steps to SUCCESS marker."""
        if not self.show_state_markers or (self._has_trail and self.trail.failed_step):
            return
        for leaf in self._leaf_steps:
            completed = leaf.name in self.trail.completed
            if self._has_trail and not completed:
                continue
            state.add_link(leaf.name, "-->", "SUCCESS", highlight=completed)

    def _add_step_link(self, state: DiagramState, src: str, dst: str) -> None:
        """Add a link between two steps with trail highlighting."""
        src_step = self._step_map.get(src)
        dst_step = self._step_map.get(dst)
        
        # If either step is missing from the map (should only happen in invalid/test graphs),
        # we treat it as not touched.
        src_touched = self._is_step_touched(src_step) if src_step else False
        dst_touched = self._is_step_touched(dst_step) if dst_step else False
        
        highlight = src_touched and dst_touched
        if self._has_trail and not highlight:
            return
        state.add_link(src, "-->", dst, highlight=highlight)

    def _add_failure_edges(self, state: DiagramState) -> None:
        """Add compensation and rollback edges."""
        if not self.show_compensation or not self._compensable_steps:
            return

        # Step -> Compensation
        for step in self.steps:
            is_comp = step.name in self.trail.compensated
            if self._has_trail:
                if is_comp and step.has_compensation:
                    state.add_link(
                        step.name, "-. compensate .->", f"comp_{step.name}", True, "compensation"
                    )
            elif step.has_compensation:
                state.add_link(step.name, "-. compensate .->", f"comp_{step.name}", False, "compensation")
            else:
                ancestors = self._get_compensable_ancestors(step)
                if ancestors:
                    target = sorted(ancestors)[0]
                    state.add_link(step.name, "-. compensate .->", f"comp_{target}", False, "compensation")

        # Compensation Chain
        self._add_compensation_chain(state)

    def _add_compensation_chain(self, state: DiagramState) -> None:
        """Add links between compensation nodes."""
        if self._has_deps:
            self._add_dependency_compensation_links(state)
        else:
            self._add_sequential_compensation_links(state)

        self._add_rollback_marker_links(state)

    def _add_dependency_compensation_links(self, state: DiagramState) -> None:
        """Add compensation links for dependency-based sagas."""
        for step in self._compensable_steps:
            if self._has_trail and step.name not in self.trail.compensated:
                continue
            for dep in sorted(self._get_compensable_ancestors(step)):
                if self._has_trail and dep not in self.trail.compensated:
                    continue
                state.add_link(f"comp_{step.name}", "-.->", f"comp_{dep}", True, "compensation")

    def _add_sequential_compensation_links(self, state: DiagramState) -> None:
        """Add compensation links for sequential sagas."""
        comp_names = [s.name for s in self._compensable_steps]
        for i in range(len(comp_names) - 1, 0, -1):
            s1, s2 = comp_names[i], comp_names[i - 1]
            highlight = s1 in self.trail.compensated and s2 in self.trail.compensated
            if self._has_trail and not highlight:
                continue
            state.add_link(f"comp_{s1}", "-.->", f"comp_{s2}", True, "compensation")

    def _add_rollback_marker_links(self, state: DiagramState) -> None:
        """Add links from root compensations to ROLLED_BACK marker."""
        if not self.show_state_markers:
            return
        for root_comp in self._get_root_compensation_steps():
            highlight = root_comp.name in self.trail.compensated
            if self._has_trail and not highlight:
                continue
            state.add_link(f"comp_{root_comp.name}", "-.->", "ROLLED_BACK", True, "compensation")

    def _get_compensable_ancestors(self, step: StepInfo) -> set[str]:
        """Find nearest upstream steps that have compensation."""
        found: set[str] = set()
        queue = sorted(step.depends_on)
        seen: set[str] = set()

        while queue:
            name = queue.pop(0)
            if name in seen:
                continue
            seen.add(name)
            s = self._step_map.get(name)
            if not s:
                continue
            if s.has_compensation:
                found.add(name)
            else:
                queue.extend(sorted(s.depends_on))
        return found

    def _get_root_compensation_steps(self) -> list[StepInfo]:
        """Find compensable steps that have no compensable ancestors."""
        if self._has_deps:
            return [s for s in self._compensable_steps if not self._get_compensable_ancestors(s)]
        return [self._compensable_steps[0]] if self._compensable_steps else []

    def _add_styling(self, state: DiagramState) -> None:
        """Add class definitions and apply them to nodes."""
        state.add_comment("Styling")
        state.add_line("classDef success fill:#d4edda,stroke:#28a745,color:#155724")
        state.add_line("classDef failure fill:#f8d7da,stroke:#dc3545,color:#721c24")
        state.add_line("classDef compensation fill:#fff3cd,stroke:#ffc107,color:#856404")
        state.add_line("classDef startEnd fill:#333,stroke:#333,color:#fff")

        if self.show_pivot_zones and self._has_pivots:
            state.add_comment("Pivot Zone Styles")
            state.add_line("classDef reversible fill:#98FB98,stroke:#28a745,color:#155724")
            state.add_line("classDef pivot fill:#FFD700,stroke:#FFA500,color:#8B4513,stroke-width:3px")
            state.add_line("classDef committed fill:#87CEEB,stroke:#4169E1,color:#00008B")
            state.add_line("classDef tainted fill:#DDA0DD,stroke:#8B008B,color:#4B0082")

        self._apply_classes(state)
        self._apply_link_styles(state)

    def _apply_classes(self, state: DiagramState) -> None:
        """Apply CSS classes to nodes."""
        if self._has_trail:
            self._apply_trail_classes(state)
        else:
            self._apply_static_classes(state)

    def _apply_trail_classes(self, state: DiagramState) -> None:
        """Apply styling based on execution trail."""
        if self.trail.completed:
            state.add_line(f"class {','.join(sorted(self.trail.completed))} success")
        if self.trail.failed_step:
            state.add_line(f"class {self.trail.failed_step} failure")
        if self.trail.compensated:
            state.add_line(f"class {','.join(f'comp_{s}' for s in sorted(self.trail.compensated))} compensation")
        
        if self.show_state_markers:
            markers = ["START", "ROLLED_BACK" if self.trail.failed_step else "SUCCESS"]
            state.add_line(f"class {','.join(markers)} startEnd")

    def _apply_static_classes(self, state: DiagramState) -> None:
        """Apply styling for static diagrams (no trail)."""
        if self.show_pivot_zones and self._has_pivots:
            self._apply_zone_classes(state)
        else:
            state.add_line(f"class {','.join(s.name for s in self.steps)} success")
        
        if self.show_compensation and self._compensable_steps:
            state.add_line(f"class {','.join(f'comp_{s.name}' for s in self._compensable_steps)} compensation")
        
        if self.show_state_markers:
            markers = ["START", "SUCCESS"]
            if self.show_compensation and self._compensable_steps:
                markers.append("ROLLED_BACK")
            state.add_line(f"class {','.join(markers)} startEnd")

    def _apply_zone_classes(self, state: DiagramState) -> None:
        """Apply zone-based styling (v1.3.0)."""
        zones: dict[str, list[str]] = {"reversible": [], "pivot": [], "committed": [], "tainted": []}
        for s in self.steps:
            if s.tainted:
                zones["tainted"].append(s.name)
            elif s.pivot:
                zones["pivot"].append(s.name)
            elif self._is_after_any_pivot(s):
                zones["committed"].append(s.name)
            else:
                zones["reversible"].append(s.name)
        
        for zone, names in zones.items():
            if names:
                state.add_line(f"class {','.join(names)} {zone}")

    def _is_after_any_pivot(self, step: StepInfo) -> bool:
        """BFS to check if step is descendant of any pivot."""
        pivots = {s.name for s in self._pivot_steps}
        visited, queue = set(), list(step.depends_on)
        while queue:
            name = queue.pop(0)
            if name in pivots: return True
            if name not in visited:
                visited.add(name)
                s = self._step_map.get(name)
                if s: queue.extend(s.depends_on)
        return False

    def _apply_link_styles(self, state: DiagramState) -> None:
        """Apply colors to links."""
        state.add_line("")
        state.add_line("linkStyle default stroke:#adb5bd")
        if state.success_links:
            state.add_line(f"linkStyle {','.join(state.success_links)} stroke-width:3px,stroke:#28a745")
        if state.compensation_links:
            state.add_line(f"linkStyle {','.join(state.compensation_links)} stroke-width:3px,stroke:#ffc107")
