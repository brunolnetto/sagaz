"""
Tests for Mermaid diagram generation and connected graph validation.
Combines coverage for MermaidGenerator, declarative Sagas, and graph validation.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from sagaz import Saga, action, compensate
from sagaz.core import Saga as ClassicSaga
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


class TestMermaidGeneration:
    """Test Mermaid diagram generation."""

    def test_declarative_saga_to_mermaid_sequential(self):
        """Test Mermaid generation for sequential saga."""

        class SequentialSaga(Saga):
            saga_name = "sequential"

            @action("step_a")
            async def step_a(self, ctx):
                return {}

            @action("step_b")
            async def step_b(self, ctx):
                return {}

        saga = SequentialSaga()
        mermaid = saga.to_mermaid()

        assert "flowchart TB" in mermaid
        assert "step_a" in mermaid
        assert "step_b" in mermaid
        # Sequential flow should show arrows
        assert "step_a --> step_b" in mermaid

    def test_declarative_saga_to_mermaid_with_deps(self):
        """Test Mermaid generation with dependencies."""

        class DagSaga(Saga):
            saga_name = "dag"

            @action("setup")
            async def setup(self, ctx):
                return {}

            @action("parallel_a", depends_on=["setup"])
            async def parallel_a(self, ctx):
                return {}

            @action("parallel_b", depends_on=["setup"])
            async def parallel_b(self, ctx):
                return {}

            @action("finalize", depends_on=["parallel_a", "parallel_b"])
            async def finalize(self, ctx):
                return {}

        saga = DagSaga()
        mermaid = saga.to_mermaid()

        assert "flowchart TB" in mermaid
        assert "setup" in mermaid
        assert "parallel_a" in mermaid
        assert "parallel_b" in mermaid
        assert "finalize" in mermaid
        assert "setup --> parallel_a" in mermaid
        assert "setup --> parallel_b" in mermaid
        # Finalize should depend on both
        assert "parallel_a --> finalize" in mermaid
        assert "parallel_b --> finalize" in mermaid

    def test_declarative_saga_to_mermaid_markdown(self):
        """Test Mermaid markdown wrapper."""

        class SimpleSaga(Saga):
            saga_name = "simple"

            @action("only_step")
            async def only_step(self, ctx):
                return {}

        saga = SimpleSaga()
        md = saga.to_mermaid_markdown()

        assert md.startswith("```mermaid\n")
        assert md.endswith("\n```")
        assert "flowchart TB" in md

    def test_declarative_saga_to_mermaid_direction(self):
        """Test Mermaid direction parameter."""

        class SimpleSaga(Saga):
            saga_name = "simple"

            @action("step")
            async def step(self, ctx):
                return {}

        saga = SimpleSaga()

        assert "flowchart LR" in saga.to_mermaid("LR")
        assert "flowchart BT" in saga.to_mermaid("BT")
        assert "flowchart RL" in saga.to_mermaid("RL")

    def test_declarative_saga_root_steps_stadium_shape(self):
        """Test that root steps use stadium shape."""

        class RootSaga(Saga):
            saga_name = "root"

            @action("root_step")
            async def root_step(self, ctx):
                return {}

            @action("child_step", depends_on=["root_step"])
            async def child_step(self, ctx):
                return {}

        saga = RootSaga()
        mermaid = saga.to_mermaid()

        # Root step should use stadium shape ([...])
        assert "root_step([root_step])" in mermaid

    def test_declarative_saga_shows_compensation(self):
        """Test that compensation nodes are shown in Mermaid diagram."""

        class CompensableSaga(Saga):
            saga_name = "compensable"

            @action("reserve")
            async def reserve(self, ctx):
                return {}

            @compensate("reserve")
            async def release(self, ctx):
                pass

            @action("charge", depends_on=["reserve"])
            async def charge(self, ctx):
                return {}

            @compensate("charge")
            async def refund(self, ctx):
                pass

        saga = CompensableSaga()
        mermaid = saga.to_mermaid()

        # Should show compensation nodes
        assert "comp_reserve{{undo reserve}}" in mermaid
        assert "comp_charge{{undo charge}}" in mermaid
        # Each step should have a compensate edge to its compensation
        assert "reserve -. compensate .-> comp_reserve" in mermaid
        assert "charge -. compensate .-> comp_charge" in mermaid
        # Compensation chain: charge's comp triggers reserve's comp
        assert "comp_charge -.-> comp_reserve" in mermaid

    def test_declarative_saga_no_compensation_no_arrow(self):
        """Test that steps without compensation don't have compensation nodes."""

        class PartialCompSaga(Saga):
            saga_name = "partial"

            @action("step_with_comp")
            async def step_with_comp(self, ctx):
                return {}

            @compensate("step_with_comp")
            async def undo_step(self, ctx):
                pass

            @action("step_no_comp", depends_on=["step_with_comp"])
            async def step_no_comp(self, ctx):
                return {}

        saga = PartialCompSaga()
        mermaid = saga.to_mermaid()

        # Should show compensation for step_with_comp
        assert "comp_step_with_comp" in mermaid
        # Should NOT show compensation for step_no_comp
        assert "comp_step_no_comp" not in mermaid

    def test_declarative_saga_hide_compensation(self):
        """Test show_compensation=False hides compensation nodes."""

        class CompensableSaga(Saga):
            saga_name = "compensable"

            @action("step")
            async def step(self, ctx):
                return {}

            @compensate("step")
            async def undo(self, ctx):
                pass

        saga = CompensableSaga()
        mermaid = saga.to_mermaid(show_compensation=False)

        # Should NOT show compensation nodes when disabled
        assert "comp_step" not in mermaid
        assert "-. compensate .->" not in mermaid  # No compensate edges

    def test_declarative_saga_parallel_dag_compensation(self):
        """Test that parallel DAG shows correct reverse compensation flow."""

        class ParallelDagSaga(Saga):
            saga_name = "parallel_dag"

            @action("setup")
            async def setup(self, ctx):
                return {}

            @compensate("setup")
            async def teardown(self, ctx):
                pass

            @action("work_a", depends_on=["setup"])
            async def work_a(self, ctx):
                return {}

            @compensate("work_a")
            async def undo_a(self, ctx):
                pass

            @action("work_b", depends_on=["setup"])
            async def work_b(self, ctx):
                return {}

            @compensate("work_b")
            async def undo_b(self, ctx):
                pass

            @action("finalize", depends_on=["work_a", "work_b"])
            async def finalize(self, ctx):
                return {}

            @compensate("finalize")
            async def unfinalize(self, ctx):
                pass

        saga = ParallelDagSaga()
        mermaid = saga.to_mermaid()

        # Happy path
        assert "setup --> work_a" in mermaid
        assert "setup --> work_b" in mermaid
        assert "work_a --> finalize" in mermaid
        assert "work_b --> finalize" in mermaid

        # Each step has compensate edge
        assert "setup -. compensate .-> comp_setup" in mermaid
        assert "work_a -. compensate .-> comp_work_a" in mermaid
        assert "work_b -. compensate .-> comp_work_b" in mermaid
        assert "finalize -. compensate .-> comp_finalize" in mermaid

        # Compensation chain (reverse dependencies)
        assert "comp_finalize -.-> comp_work_a" in mermaid
        assert "comp_finalize -.-> comp_work_b" in mermaid
        assert "comp_work_a -.-> comp_setup" in mermaid
        assert "comp_work_b -.-> comp_setup" in mermaid

    @pytest.mark.asyncio
    async def test_classic_saga_to_mermaid_sequential(self):
        """Test Mermaid generation for classic saga."""
        saga = ClassicSaga(name="classic")

        await saga.add_step("step_a", lambda ctx: "a")
        await saga.add_step("step_b", lambda ctx: "b")

        mermaid = saga.to_mermaid()

        assert "flowchart TB" in mermaid
        assert "step_a" in mermaid
        assert "step_b" in mermaid
        assert "step_a --> step_b" in mermaid

    @pytest.mark.asyncio
    async def test_classic_saga_to_mermaid_with_deps(self):
        """Test Mermaid generation for classic saga with dependencies."""
        saga = ClassicSaga(name="classic_dag")

        await saga.add_step("setup", lambda ctx: "setup", dependencies=set())
        await saga.add_step("work_a", lambda ctx: "a", dependencies={"setup"})
        await saga.add_step("work_b", lambda ctx: "b", dependencies={"setup"})
        await saga.add_step("done", lambda ctx: "done", dependencies={"work_a", "work_b"})

        mermaid = saga.to_mermaid()

        assert "setup --> work_a" in mermaid
        assert "setup --> work_b" in mermaid
        assert "work_a --> done" in mermaid
        assert "work_b --> done" in mermaid

    @pytest.mark.asyncio
    async def test_classic_saga_state_markers(self):
        """Test that state markers (START/SUCCESS/ROLLED_BACK) are generated."""
        saga = ClassicSaga(name="state_markers")

        async def action(ctx):
            return "done"

        async def comp(ctx):
            pass

        await saga.add_step("step_a", action, comp, dependencies=set())
        await saga.add_step("step_b", action, comp, dependencies={"step_a"})

        mermaid = saga.to_mermaid()

        # State markers present
        assert "START((●))" in mermaid
        assert "SUCCESS((◎))" in mermaid
        assert "ROLLED_BACK((◎))" in mermaid
        # START connects to root
        assert "START --> step_a" in mermaid
        # Leaf connects to SUCCESS
        assert "step_b --> SUCCESS" in mermaid
        # Root compensation connects to ROLLED_BACK
        assert "comp_step_a -.-> ROLLED_BACK" in mermaid
        # Styling class applied
        assert "class START,SUCCESS,ROLLED_BACK startEnd" in mermaid

    @pytest.mark.asyncio
    async def test_classic_saga_hide_state_markers(self):
        """Test show_state_markers=False hides state nodes."""
        saga = ClassicSaga(name="no_state")

        await saga.add_step("step_a", lambda ctx: "a")

        mermaid = saga.to_mermaid(show_state_markers=False)

        assert "START" not in mermaid
        assert "SUCCESS" not in mermaid
        assert "●" not in mermaid
        assert "◎" not in mermaid

    @pytest.mark.asyncio
    async def test_classic_saga_highlight_trail(self):
        """Test highlight_trail parameter colors executed steps."""
        saga = ClassicSaga(name="highlight")

        async def action(ctx):
            return "done"

        async def comp(ctx):
            pass

        await saga.add_step("step_a", action, comp, dependencies=set())
        await saga.add_step("step_b", action, comp, dependencies={"step_a"})
        await saga.add_step("step_c", action, comp, dependencies={"step_b"})

        # Simulate: step_a and step_b completed, step_c failed, step_b compensated
        mermaid = saga.to_mermaid(
            highlight_trail={
                "completed_steps": ["step_a", "step_b"],
                "failed_step": "step_c",
                "compensated_steps": ["step_b", "step_a"],
            }
        )

        # Completed steps have success class
        assert "class step_a,step_b success" in mermaid
        # Failed step marked as failure
        assert "class step_c failure" in mermaid
        # Compensated steps have compensation class (order is alphabetical)
        assert "class comp_step_a,comp_step_b compensation" in mermaid

        # Verify link highlighting - success (green) and compensation (yellow)
        assert "linkStyle" in mermaid
        assert "stroke:#28a745" in mermaid  # Green for success edges
        assert "stroke:#ffc107" in mermaid  # Yellow for compensation edges

    @pytest.mark.asyncio
    async def test_classic_saga_to_mermaid_with_execution_no_state(self):
        """Test to_mermaid_with_execution returns basic diagram when no state found."""
        saga = ClassicSaga(name="exec_test")
        await saga.add_step("step_a", lambda ctx: "a")

        # Mock storage that returns None
        mock_storage = MagicMock()
        mock_storage.load_saga_state = AsyncMock(return_value=None)

        mermaid = await saga.to_mermaid_with_execution("nonexistent-id", mock_storage)

        # Should still generate valid diagram without trail-specific highlighting
        assert "flowchart TB" in mermaid
        assert "step_a" in mermaid
        # No highlight class for static diagrams without trail

    @pytest.mark.asyncio
    async def test_classic_saga_to_mermaid_with_execution_with_state(self):
        """Test to_mermaid_with_execution highlights actual execution."""
        saga = ClassicSaga(name="exec_state")

        async def action(ctx):
            return "done"

        async def comp(ctx):
            pass

        await saga.add_step("step_a", action, comp, dependencies=set())
        await saga.add_step("step_b", action, comp, dependencies={"step_a"})

        # Mock saga state dict
        mock_data = {
            "steps": [
                {"name": "step_a", "status": "compensated"},
                {"name": "step_b", "status": "failed"},
            ]
        }

        mock_storage = MagicMock()
        mock_storage.load_saga_state = AsyncMock(return_value=mock_data)

        mermaid = await saga.to_mermaid_with_execution("test-saga-id", mock_storage)

        # Should highlight based on state
        # step_a was compensated, meaning it completed first -> success
        assert "class step_a success" in mermaid
        # step_a compensation also ran -> compensation
        # step_b failed -> failure
        assert "class step_b failure" in mermaid
        assert "class comp_step_a compensation" in mermaid

    @pytest.mark.asyncio
    async def test_classic_saga_to_mermaid_markdown(self):
        """Test to_mermaid_markdown wraps in code fence."""
        saga = ClassicSaga(name="markdown")
        await saga.add_step("step_a", lambda ctx: "a")

        markdown = saga.to_mermaid_markdown()

        assert markdown.startswith("```mermaid\n")
        assert markdown.endswith("\n```")
        assert "flowchart TB" in markdown

    def test_declarative_saga_state_markers(self):
        """Test state markers with declarative saga."""

        class StateSaga(Saga):
            saga_name = "state"

            @action("reserve")
            async def reserve(self, ctx):
                return {}

            @compensate("reserve")
            async def release(self, ctx):
                pass

            @action("charge", depends_on=["reserve"])
            async def charge(self, ctx):
                return {}

            @compensate("charge")
            async def refund(self, ctx):
                pass

        saga = StateSaga()
        mermaid = saga.to_mermaid()

        assert "START((●))" in mermaid
        assert "SUCCESS((◎))" in mermaid
        assert "ROLLED_BACK((◎))" in mermaid
        assert "START --> reserve" in mermaid
        assert "charge --> SUCCESS" in mermaid
        assert "comp_reserve -.-> ROLLED_BACK" in mermaid

    def test_declarative_saga_hide_state_markers(self):
        """Test show_state_markers=False with declarative saga."""

        class NoMarkerSaga(Saga):
            saga_name = "no_markers"

            @action("step")
            async def step(self, ctx):
                return {}

        saga = NoMarkerSaga()
        mermaid = saga.to_mermaid(show_state_markers=False)

        assert "START" not in mermaid
        assert "SUCCESS" not in mermaid

    def test_declarative_saga_highlight_trail(self):
        """Test highlight_trail with declarative saga."""

        class HighlightSaga(Saga):
            saga_name = "highlight"

            @action("a")
            async def a(self, ctx):
                return {}

            @compensate("a")
            async def undo_a(self, ctx):
                pass

            @action("b", depends_on=["a"])
            async def b(self, ctx):
                return {}

            @compensate("b")
            async def undo_b(self, ctx):
                pass

        saga = HighlightSaga()
        mermaid = saga.to_mermaid(
            highlight_trail={
                "completed_steps": ["a"],
                "failed_step": "b",
                "compensated_steps": ["a"],
            }
        )

        assert "class a success" in mermaid
        assert "class comp_a compensation" in mermaid

    @pytest.mark.asyncio
    async def test_declarative_saga_to_mermaid_with_execution(self):
        """Test to_mermaid_with_execution with declarative saga."""

        class ExecSaga(Saga):
            saga_name = "exec"

            @action("step")
            async def step(self, ctx):
                return {}

            @compensate("step")
            async def undo(self, ctx):
                pass

        saga = ExecSaga()

        # Mock saga state dict
        mock_data = {"steps": [{"name": "step", "status": "completed"}]}

        mock_storage = MagicMock()
        mock_storage.load_saga_state = AsyncMock(return_value=mock_data)

        mermaid = await saga.to_mermaid_with_execution("saga-id", mock_storage)

        assert "class step success" in mermaid


class TestConnectedGraphValidation:
    """Test that disjoint sagas are rejected."""

    @pytest.mark.asyncio
    async def test_connected_saga_passes_validation(self):
        """Test that connected saga passes validation."""
        saga = ClassicSaga(name="connected")

        async def action(ctx):
            return "done"

        await saga.add_step("root", action, dependencies=set())
        await saga.add_step("child", action, dependencies={"root"})

        # Should not raise - build batches calls validation
        result = await saga.execute()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_disjoint_saga_raises_error(self):
        """Test that disjoint saga raises ValueError."""
        saga = ClassicSaga(name="disjoint")

        async def action(ctx):
            return "done"

        # Two disconnected groups: A -> C and B -> D
        await saga.add_step("step_a", action, dependencies=set())
        await saga.add_step("step_b", action, dependencies=set())
        await saga.add_step("step_c", action, dependencies={"step_a"})
        await saga.add_step("step_d", action, dependencies={"step_b"})

        # Execution should fail with validation error
        result = await saga.execute()
        assert result.success is False
        assert "disconnected step groups" in str(result.error)

    @pytest.mark.asyncio
    async def test_single_step_saga_always_valid(self):
        """Test that single step saga is always valid."""
        saga = ClassicSaga(name="single")

        async def action(ctx):
            return "only"

        await saga.add_step("only_step", action, dependencies=set())

        result = await saga.execute()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_sequential_saga_always_valid(self):
        """Test that sequential saga (no explicit deps) is always valid."""
        saga = ClassicSaga(name="sequential")

        async def action1(ctx):
            return "1"

        async def action2(ctx):
            return "2"

        async def action3(ctx):
            return "3"

        # No dependencies specified = sequential execution
        await saga.add_step("step_1", action1)
        await saga.add_step("step_2", action2)
        await saga.add_step("step_3", action3)

        result = await saga.execute()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_three_component_disjoint_saga_shows_groups(self):
        """Test that error message shows all disconnected groups."""
        saga = ClassicSaga(name="three_groups")

        async def action(ctx):
            return "done"

        # Three disconnected groups
        await saga.add_step("group1_a", action, dependencies=set())
        await saga.add_step("group1_b", action, dependencies={"group1_a"})

        await saga.add_step("group2_a", action, dependencies=set())

        await saga.add_step("group3_a", action, dependencies=set())
        await saga.add_step("group3_b", action, dependencies={"group3_a"})

        result = await saga.execute()
        assert result.success is False
        error_msg = str(result.error)
        assert "3 disconnected step groups" in error_msg

    @pytest.mark.asyncio
    async def test_linear_chain_is_connected(self):
        """Test that a linear chain A -> B -> C -> D is connected."""
        saga = ClassicSaga(name="chain")

        async def action(ctx):
            return "done"

        await saga.add_step("a", action, dependencies=set())
        await saga.add_step("b", action, dependencies={"a"})
        await saga.add_step("c", action, dependencies={"b"})
        await saga.add_step("d", action, dependencies={"c"})

        result = await saga.execute()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_diamond_pattern_is_connected(self):
        """Test that diamond pattern is connected."""
        #     A
        #    / \
        #   B   C
        #    \ /
        #     D
        saga = ClassicSaga(name="diamond")

        async def action(ctx):
            return "done"

        await saga.add_step("a", action, dependencies=set())
        await saga.add_step("b", action, dependencies={"a"})
        await saga.add_step("c", action, dependencies={"a"})
        await saga.add_step("d", action, dependencies={"b", "c"})

        result = await saga.execute()
        assert result.success is True
