"""Styling (classDef / class / linkStyle) for the Mermaid diagram generator."""

from __future__ import annotations

from sagaz.observability.visualization._mermaid_models import StepInfo, _MermaidState


class _StylingMixin(_MermaidState):
    """Renders class definitions, node classes, marker and link styles."""

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

        # v1.3.0: Pivot zone styles
        if self.show_pivot_zones and self._has_pivots:
            self._lines.append("    %% Pivot Zone Styles")
            self._lines.append("    classDef reversible fill:#98FB98,stroke:#28a745,color:#155724")
            self._lines.append(
                "    classDef pivot fill:#FFD700,stroke:#FFA500,color:#8B4513,stroke-width:3px"
            )
            self._lines.append("    classDef committed fill:#87CEEB,stroke:#4169E1,color:#00008B")
            self._lines.append("    classDef tainted fill:#DDA0DD,stroke:#8B008B,color:#4B0082")

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
        # v1.3.0: Apply pivot zone styles if enabled and pivots exist
        if self.show_pivot_zones and self._has_pivots:
            self._apply_zone_classes()
        else:
            # Original behavior: all steps get success style
            if step_names:
                self._lines.append(f"    class {','.join(step_names)} success")

        if comp_names:
            self._lines.append(f"    class {','.join(comp_names)} compensation")

    def _apply_zone_classes(self) -> None:
        """
        Apply zone-based styling to nodes (v1.3.0).

        Zones:
        - reversible: Steps before pivot (light green)
        - pivot: The pivot step itself (gold, thick border)
        - committed: Steps after pivot (light blue)
        - tainted: Ancestors of completed pivot (plum/purple)
        """
        # Collect steps by zone
        reversible_steps = []
        pivot_steps = []
        committed_steps = []
        tainted_steps = []

        for step in self.steps:
            if step.tainted:
                tainted_steps.append(step.name)
            elif step.pivot:
                pivot_steps.append(step.name)
            elif self._is_after_any_pivot(step):
                committed_steps.append(step.name)
            else:
                reversible_steps.append(step.name)

        # Apply classes
        if reversible_steps:
            self._lines.append(f"    class {','.join(reversible_steps)} reversible")
        if pivot_steps:
            self._lines.append(f"    class {','.join(pivot_steps)} pivot")
        if committed_steps:
            self._lines.append(f"    class {','.join(committed_steps)} committed")
        if tainted_steps:
            self._lines.append(f"    class {','.join(tainted_steps)} tainted")

    def _is_after_any_pivot(self, step: StepInfo) -> bool:
        """Check if step is a descendant of any pivot."""
        if not self._pivot_steps:
            return False

        # BFS from pivot steps to find descendants
        pivots = {s.name for s in self._pivot_steps}

        # Check if any ancestor is a pivot
        visited = set()
        to_check = list(step.depends_on)

        while to_check:
            dep = to_check.pop(0)
            if dep in visited:
                continue
            visited.add(dep)

            if dep in pivots:
                return True

            # Check ancestors of this dependency
            dep_step = self._step_map.get(dep)
            if dep_step:
                to_check.extend(dep_step.depends_on)

        return False

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
