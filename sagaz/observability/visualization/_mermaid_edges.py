"""Edge rendering for the Mermaid diagram generator."""

from __future__ import annotations

from sagaz.observability.visualization._mermaid_models import StepInfo, _MermaidState


class _EdgeRenderingMixin(_MermaidState):
    """Renders success, compensation and rollback edges."""

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
