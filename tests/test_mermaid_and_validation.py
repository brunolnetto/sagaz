"""
Tests for Mermaid diagram generation and connected graph validation.
"""

import pytest

from sagaz import Saga, action, compensate
from sagaz.core import Saga as ClassicSaga


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
        # Each step should have a fail edge to its compensation
        assert "reserve -. fail .-> comp_reserve" in mermaid
        assert "charge -. fail .-> comp_charge" in mermaid
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
        assert "-. fail .->" not in mermaid  # No fail edges

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

        # Each step has fail edge
        assert "setup -. fail .-> comp_setup" in mermaid
        assert "work_a -. fail .-> comp_work_a" in mermaid
        assert "work_b -. fail .-> comp_work_b" in mermaid
        assert "finalize -. fail .-> comp_finalize" in mermaid

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
