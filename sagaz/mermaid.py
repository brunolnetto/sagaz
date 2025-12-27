"""
Mermaid diagram generation utilities for saga visualization.

This module provides a reusable MermaidGenerator class that can generate
Mermaid flowchart diagrams from saga step definitions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class StepInfo:
    """Normalized step information for Mermaid generation."""

    name: str
    has_compensation: bool
    depends_on: set[str] = field(default_factory=set)


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


class MermaidGenerator:
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
    ):
        self.steps = steps
        self.direction = direction
        self.show_compensation = show_compensation
        self.show_state_markers = show_state_markers
        self.trail = highlight_trail or HighlightTrail()

        self._step_map = {s.name: s for s in steps}
        self._compute_step_metadata()
        self._init_link_tracking()

    def _compute_step_metadata(self) -> None:
        """Compute derived properties from steps."""
        self._compensable_steps = [s for s in self.steps if s.has_compensation]
        self._has_deps = any(s.depends_on for s in self.steps)

        all_deps: set[str] = set()
        for step in self.steps:
            all_deps.update(step.depends_on)
        self._root_steps = [s for s in self.steps if not s.depends_on]
        self._leaf_steps = [s for s in self.steps if s.name not in all_deps]

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

    # -------------------------------------------------------------------------
    # Node Generation
    # -------------------------------------------------------------------------

    def _add_nodes(self) -> None:
        """Add all step nodes to the diagram."""
        has_trail = bool(self.trail.completed or self.trail.failed_step or self.trail.compensated)
        show_comp_subgraph = not has_trail or bool(self.trail.compensated)

        self._add_start_marker()
        self._add_step_nodes(has_trail)
        self._add_final_markers(show_comp_subgraph, has_trail)
        self._add_compensation_nodes(show_comp_subgraph)

    def _add_start_marker(self) -> None:
        """Add START marker."""
        if self.show_state_markers:
            self._lines.append("    START((●))")

    def _add_step_nodes(self, has_trail: bool) -> None:
        """Add step nodes. When trail exists, only show executed nodes."""
        for step in self.steps:
            # When we have a trail, only show nodes that were touched
            if has_trail:
                was_executed = (
                    step.name in self.trail.completed or step.name == self.trail.failed_step
                )
                if not was_executed:
                    continue

            shape = self._get_node_shape(step)
            self._lines.append(f"    {step.name}{shape}")

    def _add_final_markers(self, show_comp_subgraph: bool, has_trail: bool) -> None:
        """Add SUCCESS and ROLLED_BACK markers. Show only relevant one when trail exists."""
        if not self.show_state_markers:
            return

        # When we have a trail, only show the relevant end marker
        if has_trail:
            if self.trail.failed_step:
                # Saga failed - show ROLLED_BACK only
                if self.trail.total_duration:
                    self._lines.append(f'    ROLLED_BACK(("✗ {self.trail.total_duration}"))')
                else:
                    self._lines.append("    ROLLED_BACK((◎))")
            else:
                # Saga succeeded - show SUCCESS only
                if self.trail.total_duration:
                    self._lines.append(f'    SUCCESS(("✓ {self.trail.total_duration}"))')
                else:
                    self._lines.append("    SUCCESS((◎))")
        else:
            # Static diagram: show both markers
            self._lines.append("    SUCCESS((◎))")
            if self.show_compensation and self._compensable_steps and show_comp_subgraph:
                self._lines.append("    ROLLED_BACK((◎))")

    def _add_compensation_nodes(self, show_comp_subgraph: bool) -> None:
        """Add compensation nodes. Only for steps that were actually compensated when trail exists."""
        if not (self.show_compensation and show_comp_subgraph):
            return

        has_trail = bool(self.trail.completed or self.trail.failed_step or self.trail.compensated)

        for step in self._compensable_steps:
            # When we have a trail, only show compensation nodes for actually compensated steps
            if has_trail and step.name not in self.trail.compensated:
                continue

            comp_duration = self.trail.comp_durations.get(step.name)
            if comp_duration:
                self._lines.append(
                    f'    comp_{step.name}{{{{"undo {step.name}<br/>{comp_duration}"}}}}'
                )
            else:
                self._lines.append(f"    comp_{step.name}{{{{undo {step.name}}}}}")

    def _get_node_shape(self, step: StepInfo) -> str:
        """Determine the Mermaid node shape for a step."""
        is_root = not step.depends_on

        # Get duration suffix if available
        duration = self.trail.step_durations.get(step.name)

        # When label has special chars (like parentheses from duration), we need quoted format
        if duration:
            # Use Mermaid's node_id["label"] format for complex labels
            if is_root:
                return f'(["{step.name}<br/>{duration}"])'
            if step.has_compensation:
                return f'["{step.name}<br/>{duration}"]'
            return f'[/"{step.name}<br/>{duration}"/]'
        # Simple labels without special chars
        if is_root:
            return f"([{step.name}])"
        if step.has_compensation:
            return f"[{step.name}]"
        return f"[/{step.name}/]"

    # -------------------------------------------------------------------------
    # Edge Generation
    # -------------------------------------------------------------------------

    def _add_link(
        self, src: str, arrow: str, dst: str, highlight: bool = False, link_type: str = "success"
    ) -> None:
        """Add a link to the diagram, optionally highlighting it.

        Args:
            src: Source node
            arrow: Arrow style
            dst: Destination node
            highlight: Whether to highlight this link
            link_type: 'success' or 'compensation' for coloring
        """
        self._lines.append(f"    {src} {arrow} {dst}")
        if highlight:
            if link_type == "compensation":
                self._compensation_links.append(str(self._link_count))
            else:
                self._success_links.append(str(self._link_count))
        self._link_count += 1

    def _add_success_edges(self) -> None:
        """Add success path edges (green arrows)."""
        has_trail = bool(self.trail.completed or self.trail.failed_step or self.trail.compensated)
        self._add_start_to_roots(has_trail)
        self._add_dependency_or_sequential_edges(has_trail)
        self._add_leaves_to_success(has_trail)

    def _add_start_to_roots(self, has_trail: bool) -> None:
        """Connect START to root steps that were executed."""
        if not self.show_state_markers:
            return
        for step in self._root_steps:
            was_started = step.name in self.trail.completed or step.name == self.trail.failed_step
            # Only add edge if node exists (was executed or no trail)
            if has_trail and not was_started:
                continue
            self._add_link("START", "-->", step.name, highlight=was_started)

    def _is_step_executed(self, step_name: str) -> bool:
        """Check if a step was executed (completed or failed)."""
        return step_name in self.trail.completed or step_name == self.trail.failed_step

    def _add_dependency_or_sequential_edges(self, has_trail: bool) -> None:
        """Add edges between steps that were executed."""
        if self._has_deps:
            self._add_dependency_edges(has_trail)
        else:
            self._add_sequential_edges(has_trail)

    def _add_dependency_edges(self, has_trail: bool) -> None:
        """Add edges based on step dependencies."""
        for step in self.steps:
            step_executed = self._is_step_executed(step.name)
            for dep in sorted(step.depends_on):
                dep_executed = self._is_step_executed(dep)
                if has_trail and not (dep_executed and step_executed):
                    continue
                self._add_link(dep, "-->", step.name, highlight=(dep_executed and step_executed))

    def _add_sequential_edges(self, has_trail: bool) -> None:
        """Add edges for sequential (non-DAG) execution."""
        for i in range(len(self.steps) - 1):
            s1, s2 = self.steps[i].name, self.steps[i + 1].name
            s1_executed = self._is_step_executed(s1)
            s2_executed = self._is_step_executed(s2)
            if has_trail and not (s1_executed and s2_executed):
                continue
            self._add_link(s1, "-->", s2, highlight=(s1_executed and s2_executed))

    def _add_leaves_to_success(self, has_trail: bool) -> None:
        """Connect leaf steps to SUCCESS (only on success, not failure)."""
        if not self.show_state_markers:
            return
        # Only show leaf->SUCCESS edge if saga succeeded (no failure)
        if has_trail and self.trail.failed_step:
            return  # Don't connect to SUCCESS when saga failed
        for step in self._leaf_steps:
            step_completed = step.name in self.trail.completed
            if has_trail and not step_completed:
                continue
            self._add_link(step.name, "-->", "SUCCESS", highlight=step_completed)

    def _add_failure_edges(self) -> None:
        """Add failure and compensation edges."""
        if not self.show_compensation or not self._compensable_steps:
            return

        has_trail = bool(self.trail.completed or self.trail.failed_step or self.trail.compensated)
        show_comp_chain = not has_trail or bool(self.trail.compensated)

        self._add_compensate_edges(has_trail)

        if show_comp_chain:
            self._add_compensation_chain()
            self._add_rollback_edges()

    def _add_compensate_edges(self, has_trail: bool) -> None:
        """Add edges from steps to their compensation nodes."""
        for step in self.steps:
            is_compensated = step.name in self.trail.compensated

            if has_trail:
                # Only show edges for actually compensated steps
                if is_compensated and step.has_compensation:
                    self._add_link(
                        step.name,
                        "-. compensate .->",
                        f"comp_{step.name}",
                        highlight=True,
                        link_type="compensation",
                    )
            else:
                # Static diagram: show all potential edges
                if step.has_compensation:
                    self._add_link(
                        step.name,
                        "-. compensate .->",
                        f"comp_{step.name}",
                        highlight=False,
                        link_type="compensation",
                    )
                else:
                    # Non-compensable: point to nearest compensable ancestor
                    ancestors = self._get_compensable_ancestors(step)
                    if ancestors:
                        target = sorted(ancestors)[0]
                        self._add_link(
                            step.name,
                            "-. compensate .->",
                            f"comp_{target}",
                            highlight=False,
                            link_type="compensation",
                        )

    def _add_compensation_chain(self) -> None:
        """Add edges between compensation nodes (reverse dependency order)."""
        has_trail = bool(self.trail.completed or self.trail.failed_step or self.trail.compensated)

        if self._has_deps:
            self._add_dag_compensation_chain(has_trail)
        else:
            self._add_sequential_compensation_chain(has_trail)

    def _add_dag_compensation_chain(self, has_trail: bool) -> None:
        """Add compensation chain edges for DAG sagas."""
        for step in self._compensable_steps:
            s_comp = step.name in self.trail.compensated
            if has_trail and not s_comp:
                continue

            ancestors = self._get_compensable_ancestors(step)
            for dep in sorted(ancestors):
                d_comp = dep in self.trail.compensated
                if has_trail and not d_comp:
                    continue
                self._add_link(
                    f"comp_{step.name}",
                    "-.->",
                    f"comp_{dep}",
                    highlight=True,
                    link_type="compensation",
                )

    def _add_sequential_compensation_chain(self, has_trail: bool) -> None:
        """Add compensation chain edges for sequential sagas."""
        comp_order = [s.name for s in self.steps if s.has_compensation]
        for i in range(len(comp_order) - 1, 0, -1):
            s1, s2 = comp_order[i], comp_order[i - 1]
            s1_comp = s1 in self.trail.compensated
            s2_comp = s2 in self.trail.compensated
            if has_trail and not (s1_comp and s2_comp):
                continue
            self._add_link(
                f"comp_{s1}", "-.->", f"comp_{s2}", highlight=True, link_type="compensation"
            )

    def _add_rollback_edges(self) -> None:
        """Connect root compensation nodes to ROLLED_BACK."""
        if not self.show_state_markers:
            return

        has_trail = bool(self.trail.completed or self.trail.failed_step or self.trail.compensated)
        root_comps = self._get_root_compensation_steps()

        for step in root_comps:
            is_comp = step.name in self.trail.compensated
            # Skip if trail exists and step wasn't compensated
            if has_trail and not is_comp:
                continue
            self._add_link(
                f"comp_{step.name}", "-.->", "ROLLED_BACK", highlight=True, link_type="compensation"
            )

    def _get_compensable_ancestors(self, step: StepInfo) -> set[str]:
        """Find nearest upstream steps that have compensation."""
        found: set[str] = set()
        queue = sorted(step.depends_on)
        seen: set[str] = set()

        while queue:
            dep_name = queue.pop(0)
            if dep_name in seen:
                continue
            seen.add(dep_name)

            dep_step = self._step_map.get(dep_name)
            if not dep_step:
                continue

            if dep_step.has_compensation:
                found.add(dep_name)
            else:
                # Keep searching upstream
                queue.extend(sorted(dep_step.depends_on))

        return found

    def _get_root_compensation_steps(self) -> list[StepInfo]:
        """Find compensable steps that have no compensable ancestors."""
        if self._has_deps:
            return [s for s in self._compensable_steps if not self._get_compensable_ancestors(s)]
        # Sequential: first compensable step is root
        first = next((s for s in self.steps if s.has_compensation), None)
        return [first] if first else []

    # -------------------------------------------------------------------------
    # Styling
    # -------------------------------------------------------------------------

    def _add_styling(self) -> None:
        """Add CSS class definitions and apply classes to nodes."""
        self._add_class_definitions()
        self._apply_node_classes()
        self._style_state_markers()
        self._style_links()

    def _add_class_definitions(self) -> None:
        """Add CSS class definitions."""
        self._lines.append("")
        self._lines.append("    %% Styling")
        self._lines.append("    classDef success fill:#d4edda,stroke:#28a745,color:#155724")
        self._lines.append("    classDef failure fill:#f8d7da,stroke:#dc3545,color:#721c24")
        self._lines.append("    classDef compensation fill:#fff3cd,stroke:#ffc107,color:#856404")
        self._lines.append("    classDef highlighted stroke-width:3px")
        self._lines.append("    classDef startEnd fill:#333,stroke:#333,color:#fff")
        self._lines.append("    classDef dimmed fill:#e9ecef,stroke:#adb5bd,color:#6c757d")

    def _apply_node_classes(self) -> None:
        """Apply classes to step and compensation nodes."""
        step_names = [s.name for s in self.steps]
        comp_names = (
            [f"comp_{s.name}" for s in self._compensable_steps] if self.show_compensation else []
        )

        if self.trail.completed or self.trail.failed_step or self.trail.compensated:
            self._apply_trail_node_classes(step_names, comp_names)
        else:
            self._apply_default_node_classes(step_names, comp_names)

    def _apply_trail_node_classes(self, step_names: list[str], comp_names: list[str]) -> None:
        """Apply classes when we have a trail. No dimming needed since only executed nodes are shown."""
        # Completed steps get success style
        if self.trail.completed:
            completed_list = sorted(self.trail.completed)
            self._lines.append(f"    class {','.join(completed_list)} success")

        # Failed step gets failure style
        if self.trail.failed_step:
            self._lines.append(f"    class {self.trail.failed_step} failure")

        # Compensated steps get compensation style
        if self.trail.compensated:
            comp_highlighted = [f"comp_{s}" for s in sorted(self.trail.compensated)]
            self._lines.append(f"    class {','.join(comp_highlighted)} compensation")

    def _apply_default_node_classes(self, step_names: list[str], comp_names: list[str]) -> None:
        """Apply default classes when no trail."""
        if step_names:
            self._lines.append(f"    class {','.join(step_names)} success")
        if comp_names:
            self._lines.append(f"    class {','.join(comp_names)} compensation")

    def _style_state_markers(self) -> None:
        """Style START, SUCCESS, ROLLED_BACK markers."""
        if not self.show_state_markers:
            return

        has_trail = bool(self.trail.completed or self.trail.failed_step or self.trail.compensated)

        if has_trail:
            # Only style the markers we actually show
            if self.trail.failed_step:
                self._lines.append("    class START,ROLLED_BACK startEnd")
            else:
                self._lines.append("    class START,SUCCESS startEnd")
        else:
            # Static diagram: style all markers
            state_markers = ["START", "SUCCESS"]
            if self.show_compensation and self._compensable_steps:
                state_markers.append("ROLLED_BACK")
            self._lines.append(f"    class {','.join(state_markers)} startEnd")

    def _style_links(self) -> None:
        """Style link colors (gray default, green success, yellow compensation)."""
        self._lines.append("")
        self._lines.append("    linkStyle default stroke:#adb5bd")
        if self._success_links:
            self._lines.append(
                f"    linkStyle {','.join(self._success_links)} stroke-width:3px,stroke:#28a745"
            )
        if self._compensation_links:
            self._lines.append(
                f"    linkStyle {','.join(self._compensation_links)} stroke-width:3px,stroke:#ffc107"
            )
