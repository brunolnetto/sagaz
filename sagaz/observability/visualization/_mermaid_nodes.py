"""Node rendering for the Mermaid diagram generator."""

from __future__ import annotations

from sagaz.observability.visualization._mermaid_models import StepInfo, _MermaidState


class _NodeRenderingMixin(_MermaidState):
    """Renders START/SUCCESS/ROLLED_BACK markers, step nodes and compensation nodes."""

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
