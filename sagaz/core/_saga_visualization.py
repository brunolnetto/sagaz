"""Saga visualization mixin - Mermaid diagram generation for imperative Saga."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.storage.base import SagaStorage


class _SagaVisualizationMixin:
    """Mixin adding Mermaid diagram generation to the Saga class."""

    def to_mermaid(
        self,
        direction: str = "TB",
        show_compensation: bool = True,
        highlight_trail: dict[str, Any] | None = None,
        show_state_markers: bool = True,
    ) -> str:
        """
        Generate a Mermaid flowchart diagram of the saga.

        Shows a decision tree where each step can succeed (go to next) or fail
        (trigger compensation chain backwards).

        Colors:
        - Success path: green styling
        - Failure/compensation path: amber/yellow styling
        - Highlighted trail: bold styling for executed steps

        Args:
            direction: Flowchart direction - "TB" (top-bottom), "LR" (left-right)
            show_compensation: If True, show compensation nodes and fail branches
            highlight_trail: Optional dict with execution trail info
            show_state_markers: If True, show initial (●) and final (◎) state nodes

        Returns:
            Mermaid diagram string that can be rendered in markdown.
        """
        from sagaz.visualization.mermaid import HighlightTrail, MermaidGenerator, StepInfo

        # Convert steps to StepInfo format
        steps = [
            StepInfo(
                name=s.name,
                has_compensation=s.compensation is not None,
                depends_on=set(self.step_dependencies.get(s.name, set())),
            )
            for s in self.steps
        ]

        # Create generator and generate diagram
        generator = MermaidGenerator(
            steps=steps,
            direction=direction,
            show_compensation=show_compensation,
            show_state_markers=show_state_markers,
            highlight_trail=HighlightTrail.from_dict(highlight_trail),
        )

        return generator.generate()

    async def to_mermaid_with_execution(
        self,
        saga_id: str,
        storage: "SagaStorage",
        direction: str = "TB",
        show_compensation: bool = True,
        show_state_markers: bool = True,
    ) -> str:
        """
        Generate Mermaid diagram with execution trail from storage.

        Args:
            saga_id: The saga execution ID to visualize
            storage: SagaStorage instance to fetch execution data from
            direction: Flowchart direction
            show_compensation: If True, show compensation nodes
            show_state_markers: If True, show initial/final nodes

        Returns:
            Mermaid diagram with highlighted execution trail.
        """
        saga_data = await storage.load_saga_state(saga_id)

        if not saga_data:
            return self.to_mermaid(direction, show_compensation, None, show_state_markers)

        # Parse steps to build highlight trail
        steps_data = saga_data.get("steps", [])
        completed_steps = set()
        failed_step = None
        compensated_steps = set()

        for step_info in steps_data:
            status = step_info.get("status")
            name = step_info.get("name")

            if status == "completed":
                completed_steps.add(name)
            elif status == "failed":
                failed_step = name
            elif status == "compensated":
                compensated_steps.add(name)
                # A compensated step must have completed first
                completed_steps.add(name)
            elif status == "compensating":
                compensated_steps.add(name)
                completed_steps.add(name)

        highlight_trail = {
            "completed_steps": list(completed_steps),
            "failed_step": failed_step,
            "compensated_steps": list(compensated_steps),
        }

        return self.to_mermaid(direction, show_compensation, highlight_trail, show_state_markers)

    def to_mermaid_markdown(
        self,
        direction: str = "TB",
        show_compensation: bool = True,
        highlight_trail: dict[str, Any] | None = None,
        show_state_markers: bool = True,
    ) -> str:
        """
        Generate a Mermaid diagram wrapped in markdown code fence.

        Args:
            direction: Flowchart direction
            show_compensation: If True, show compensation nodes and flows
            highlight_trail: Optional execution trail to highlight
            show_state_markers: If True, show initial/final nodes

        Returns:
            Mermaid diagram in markdown format.
        """
        return f"```mermaid\n{self.to_mermaid(direction, show_compensation, highlight_trail, show_state_markers)}\n```"
