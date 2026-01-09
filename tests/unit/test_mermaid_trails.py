import pytest

from sagaz.visualization.mermaid import HighlightTrail, MermaidGenerator, StepInfo


@pytest.fixture
def basic_steps():
    return [
        StepInfo(name="step1", has_compensation=True),
        StepInfo(name="step2", has_compensation=True, depends_on={"step1"}),
        StepInfo(name="step3", has_compensation=False, depends_on={"step2"}),
    ]


class TestMermaidTrails:
    def test_success_trail_rendering(self, basic_steps):
        """Test a fully successful execution trail."""
        trail = HighlightTrail(
            completed={"step1", "step2", "step3"},
            total_duration="150ms",
            step_durations={"step1": "50ms", "step2": "50ms", "step3": "50ms"},
        )

        generator = MermaidGenerator(basic_steps, highlight_trail=trail)
        diagram = generator.generate()

        # Check nodes are present with durations
        assert "step1" in diagram
        assert "50ms" in diagram

        # Check success edge styling
        assert "linkStyle" in diagram
        assert "stroke:#28a745" in diagram  # Green for success

        # Check start -> step1
        assert "START" in diagram
        assert "SUCCESS" in diagram
        assert "150ms" in diagram  # Total duration in success node

        # Should NOT have failure markers
        # Note: The color definition is always present in classDef, so we can't check for color code absence.
        # We check that no node is assigned the 'failure' class.
        assert "class " not in diagram or " failure" not in diagram.split("class ")[-1]
        assert "ROLLED_BACK" not in diagram

    def test_failure_trail_rendering(self, basic_steps):
        """Test an execution trail that failed and rolled back."""
        trail = HighlightTrail(
            completed={"step1"},  # step1 succeeded
            failed_step="step2",  # step2 failed
            compensated={"step1"},  # step1 was compensated
            total_duration="120ms",
            step_durations={"step1": "50ms", "step2": "30ms"},
            comp_durations={"step1": "40ms"},
        )

        generator = MermaidGenerator(basic_steps, highlight_trail=trail)
        diagram = generator.generate()

        # Check failed step is marked red
        assert "class step2 failure" in diagram

        # Check rolled back markers
        assert "ROLLED_BACK" in diagram
        assert "120ms" in diagram

        # Check compensation nodes
        assert "comp_step1" in diagram
        assert "undo step1<br/>40ms" in diagram

        # Check compensation edges (yellow/orange)
        assert "stroke:#ffc107" in diagram

        # step3 should NOT be in the diagram
        # Logic: _add_step_nodes skips non-executed steps if trail exists
        assert "step3" not in diagram

    def test_partial_success_no_rollback(self, basic_steps):
        """Test a failure where compensation didn't run or wasn't needed."""
        # Scenario: step2 failed, but step1 has no compensation (modified for test)
        steps = [
            StepInfo(name="step1", has_compensation=False),
            StepInfo(name="step2", has_compensation=True, depends_on={"step1"}),
        ]

        trail = HighlightTrail(
            completed={"step1"},
            failed_step="step2",
            compensated=set(),  # No compensations
        )

        generator = MermaidGenerator(steps, highlight_trail=trail)
        diagram = generator.generate()

        # step2 failed
        assert "class step2 failure" in diagram

        # ROLLED_BACK usually appears if markers are on
        assert "ROLLED_BACK" in diagram

        # NO compensation nodes should be visible
        assert "comp_step1" not in diagram

        # Link from step2 to ROLLED_BACK (unlinked directly usually, checks markers)
        # Note: step2 doesn't link to ROLLED_BACK automatically unless it's a compensation root.
        # But failure style is applied.

    def test_trail_from_dict(self):
        """Test parsing HighlightTrail from dictionary."""
        data = {
            "completed_steps": ["a", "b"],
            "failed_step": "c",
            "compensated_steps": ["b", "a"],
            "step_durations": {"a": "10ms"},
            "comp_durations": {"b": "5ms"},
            "total_duration": "100ms",
        }

        trail = HighlightTrail.from_dict(data)

        assert trail.completed == {"a", "b"}
        assert trail.failed_step == "c"
        assert trail.compensated == {"a", "b"}
        assert trail.step_durations["a"] == "10ms"
        assert trail.comp_durations["b"] == "5ms"
        assert trail.total_duration == "100ms"

    def test_trail_from_none(self):
        """Test parsing HighlightTrail from None."""
        trail = HighlightTrail.from_dict(None)
        assert isinstance(trail, HighlightTrail)
        assert len(trail.completed) == 0
        assert trail.failed_step is None

    def test_rendering_independent_steps(self):
        """Test rendering with no dependencies (parallel starts)."""
        steps = [
            StepInfo(name="A", has_compensation=False),
            StepInfo(name="B", has_compensation=False),
        ]

        trail = HighlightTrail(completed={"A", "B"})
        generator = MermaidGenerator(steps, highlight_trail=trail)
        diagram = generator.generate()

        # Both start from START
        assert "START --> A" in diagram
        assert "START --> B" in diagram

        # Both end at SUCCESS
        assert "A --> SUCCESS" in diagram
        assert "B --> SUCCESS" in diagram

    def test_only_executed_nodes_shown(self):
        """Verify that when a trail is present, unexecuted nodes are hidden."""
        steps = [
            StepInfo(name="A", has_compensation=False),
            StepInfo(name="B", has_compensation=False, depends_on={"A"}),
            StepInfo(name="C", has_compensation=False, depends_on={"B"}),
        ]

        # Trail only shows A completed, likely halted or just incomplete snapshot
        # If failed_step is set to A, then B and C are skipped.
        trail = HighlightTrail(completed=set(), failed_step="A")

        generator = MermaidGenerator(steps, highlight_trail=trail)
        diagram = generator.generate()

        assert "A" in diagram
        # "B" might be in "TB" (flowchart TB), so check for node B definition or usage
        assert "    B" not in diagram
        assert "    C" not in diagram
