"""
Additional tests for Mermaid diagram generation coverage.

These tests cover edge cases in the MermaidGenerator class that are not
covered by the main test_mermaid_and_validation.py tests.
"""

import pytest

from sagaz.mermaid import HighlightTrail, MermaidGenerator, StepInfo


class TestMermaidGeneratorEdgeCases:
    """Test edge cases and additional coverage for MermaidGenerator."""

    def test_mermaid_with_total_duration_comment(self):
        """Test that total_duration is included as a comment."""
        steps = [StepInfo(name="step_a", has_compensation=False)]
        trail = HighlightTrail(completed={"step_a"}, total_duration="1.5s")

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        assert "%% Total Duration: 1.5s" in mermaid

    def test_mermaid_with_step_durations(self):
        """Test that step durations are shown in node labels."""
        steps = [
            StepInfo(name="root_step", has_compensation=False),
            StepInfo(name="child_step", has_compensation=True, depends_on={"root_step"}),
            StepInfo(name="no_comp_step", has_compensation=False, depends_on={"root_step"}),
        ]
        trail = HighlightTrail(
            completed={"root_step", "child_step", "no_comp_step"},
            step_durations={"root_step": "100ms", "child_step": "200ms", "no_comp_step": "50ms"},
        )

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        # Root step with duration (stadium shape with duration)
        assert "root_step" in mermaid
        assert "100ms" in mermaid
        # Child step with compensation and duration
        assert "child_step" in mermaid
        assert "200ms" in mermaid
        # No comp step with duration (trapezoid shape)
        assert "no_comp_step" in mermaid
        assert "50ms" in mermaid

    def test_mermaid_with_compensation_durations(self):
        """Test that compensation durations are shown."""
        steps = [
            StepInfo(name="step_a", has_compensation=True),
        ]
        trail = HighlightTrail(
            completed={"step_a"},
            failed_step=None,
            compensated={"step_a"},
            comp_durations={"step_a": "50ms"},
        )

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        assert "comp_step_a" in mermaid
        assert "50ms" in mermaid

    def test_mermaid_failed_trail_with_total_duration(self):
        """Test failed saga with total_duration shows ROLLED_BACK marker with duration."""
        steps = [
            StepInfo(name="step_a", has_compensation=True),
            StepInfo(name="step_b", has_compensation=True, depends_on={"step_a"}),
        ]
        trail = HighlightTrail(
            completed={"step_a"},
            failed_step="step_b",
            compensated={"step_a"},
            total_duration="2.5s",
        )

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        # Should show ROLLED_BACK with duration
        assert "ROLLED_BACK" in mermaid
        assert "2.5s" in mermaid

    def test_mermaid_success_trail_with_total_duration(self):
        """Test successful saga with total_duration shows SUCCESS marker with duration."""
        steps = [
            StepInfo(name="step_a", has_compensation=True),
        ]
        trail = HighlightTrail(completed={"step_a"}, total_duration="0.5s")

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        # Should show SUCCESS with duration
        assert "SUCCESS" in mermaid
        assert "0.5s" in mermaid

    def test_mermaid_skips_unexecuted_nodes_with_trail(self):
        """Test that nodes not in trail are skipped."""
        steps = [
            StepInfo(name="step_a", has_compensation=True),
            StepInfo(name="step_b", has_compensation=True, depends_on={"step_a"}),
            StepInfo(name="step_c", has_compensation=True, depends_on={"step_b"}),
        ]
        # Only step_a completed, step_b failed - step_c was never executed
        trail = HighlightTrail(completed={"step_a"}, failed_step="step_b", compensated={"step_a"})

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        # step_a and step_b should appear
        assert "step_a" in mermaid
        assert "step_b" in mermaid

    def test_mermaid_sequential_no_deps(self):
        """Test sequential saga without dependencies."""
        steps = [
            StepInfo(name="step_1", has_compensation=True),
            StepInfo(name="step_2", has_compensation=True),
            StepInfo(name="step_3", has_compensation=True),
        ]
        trail = HighlightTrail(
            completed={"step_1", "step_2", "step_3"},
        )

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        # Sequential flow edges
        assert "step_1 --> step_2" in mermaid
        assert "step_2 --> step_3" in mermaid

    def test_mermaid_highlight_trail_from_dict_none(self):
        """Test HighlightTrail.from_dict with None returns empty trail."""
        trail = HighlightTrail.from_dict(None)
        assert trail.completed == set()
        assert trail.failed_step is None
        assert trail.compensated == set()

    def test_mermaid_highlight_trail_from_dict_full(self):
        """Test HighlightTrail.from_dict with all fields."""
        data = {
            "completed_steps": ["a", "b"],
            "failed_step": "c",
            "compensated_steps": ["b", "a"],
            "step_durations": {"a": "10ms", "b": "20ms"},
            "comp_durations": {"a": "5ms"},
            "total_duration": "100ms",
        }

        trail = HighlightTrail.from_dict(data)
        assert trail.completed == {"a", "b"}
        assert trail.failed_step == "c"
        assert trail.compensated == {"a", "b"}
        assert trail.step_durations == {"a": "10ms", "b": "20ms"}
        assert trail.comp_durations == {"a": "5ms"}
        assert trail.total_duration == "100ms"

    def test_mermaid_no_compensable_ancestors(self):
        """Test step with no compensable ancestors."""
        # step_a has no compensation, step_b depends on step_a
        steps = [
            StepInfo(name="step_a", has_compensation=False),
            StepInfo(name="step_b", has_compensation=True, depends_on={"step_a"}),
        ]

        generator = MermaidGenerator(steps=steps)
        mermaid = generator.generate()

        # Should generate valid diagram
        assert "flowchart TB" in mermaid
        assert "step_a" in mermaid
        assert "step_b" in mermaid

    def test_mermaid_root_compensation_steps_sequential(self):
        """Test finding root compensation steps in sequential saga."""
        steps = [
            StepInfo(name="step_1", has_compensation=True),
            StepInfo(name="step_2", has_compensation=True),
        ]

        generator = MermaidGenerator(steps=steps)
        root_comps = generator._get_root_compensation_steps()

        # In sequential mode, first compensable step is root
        assert len(root_comps) == 1
        assert root_comps[0].name == "step_1"

    def test_mermaid_empty_steps_list(self):
        """Test MermaidGenerator with empty steps list."""
        generator = MermaidGenerator(steps=[])
        mermaid = generator.generate()

        # Should still generate valid (minimal) diagram
        assert "flowchart TB" in mermaid

    def test_mermaid_no_state_markers(self):
        """Test MermaidGenerator with state markers disabled."""
        steps = [StepInfo(name="step_a", has_compensation=True)]

        generator = MermaidGenerator(steps=steps, show_state_markers=False)
        mermaid = generator.generate()

        assert "START" not in mermaid
        assert "SUCCESS" not in mermaid

    def test_mermaid_show_compensation_false(self):
        """Test MermaidGenerator with compensation disabled."""
        steps = [StepInfo(name="step_a", has_compensation=True)]

        generator = MermaidGenerator(steps=steps, show_compensation=False)
        mermaid = generator.generate()

        assert "comp_step_a" not in mermaid
        assert "ROLLED_BACK" not in mermaid

    def test_mermaid_dag_with_multiple_roots(self):
        """Test DAG saga with multiple root steps."""
        steps = [
            StepInfo(name="root_a", has_compensation=True),
            StepInfo(name="root_b", has_compensation=True),
            StepInfo(name="child", has_compensation=True, depends_on={"root_a", "root_b"}),
        ]

        generator = MermaidGenerator(steps=steps)
        mermaid = generator.generate()

        # Both roots should connect from START
        assert "START --> root_a" in mermaid
        assert "START --> root_b" in mermaid
        # Child depends on both
        assert "root_a --> child" in mermaid
        assert "root_b --> child" in mermaid

    def test_mermaid_direction_lr(self):
        """Test MermaidGenerator with LR direction."""
        steps = [StepInfo(name="step_a", has_compensation=False)]

        generator = MermaidGenerator(steps=steps, direction="LR")
        mermaid = generator.generate()

        assert "flowchart LR" in mermaid

    def test_mermaid_compensation_chain_sequential(self):
        """Test sequential compensation chain generation."""
        steps = [
            StepInfo(name="step_1", has_compensation=True),
            StepInfo(name="step_2", has_compensation=True),
            StepInfo(name="step_3", has_compensation=True),
        ]

        generator = MermaidGenerator(steps=steps)
        mermaid = generator.generate()

        # Compensation chain should be in reverse order
        assert "comp_step_3 -.-> comp_step_2" in mermaid
        assert "comp_step_2 -.-> comp_step_1" in mermaid

    def test_mermaid_no_compensation_nodes_when_no_compensable_steps(self):
        """Test no compensation nodes when steps have no compensation."""
        steps = [
            StepInfo(name="step_a", has_compensation=False),
            StepInfo(name="step_b", has_compensation=False, depends_on={"step_a"}),
        ]

        generator = MermaidGenerator(steps=steps)
        mermaid = generator.generate()

        assert "comp_" not in mermaid
        assert "ROLLED_BACK" not in mermaid

    def test_mermaid_trail_with_only_failed_step(self):
        """Test trail with only a failed step (first step fails)."""
        steps = [
            StepInfo(name="step_a", has_compensation=True),
            StepInfo(name="step_b", has_compensation=True, depends_on={"step_a"}),
        ]
        trail = HighlightTrail(
            failed_step="step_a",
        )

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        # step_a failed
        assert "step_a" in mermaid
        assert "class step_a failure" in mermaid

    def test_mermaid_root_compensation_steps_dag(self):
        """Test finding root compensation steps in DAG saga."""
        steps = [
            StepInfo(name="root", has_compensation=True),
            StepInfo(name="child_a", has_compensation=True, depends_on={"root"}),
            StepInfo(name="child_b", has_compensation=True, depends_on={"root"}),
        ]

        generator = MermaidGenerator(steps=steps)
        root_comps = generator._get_root_compensation_steps()

        # In DAG mode, root step has no compensable ancestors
        assert len(root_comps) == 1
        assert root_comps[0].name == "root"
