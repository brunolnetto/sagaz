"""
Visualization mixin for the declarative Saga class (decorators.py).

Extracted from Saga class in decorators.py to reduce module size.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.storage.base import SagaStorage


class _DecoratorVisualizationMixin:
    """Mixin providing Mermaid diagram generation for the declarative Saga class."""

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
        - Success path: green arrows and styling
        - Failure/compensation path: amber/yellow styling
        - Highlighted trail: bold styling for executed steps

        Args:
            direction: Flowchart direction - "TB" (top-bottom), "LR" (left-right)
            show_compensation: If True, show compensation nodes and fail branches
            highlight_trail: Optional dict with execution trail info:
                - completed_steps: list of step names that completed successfully
                - failed_step: name of step that failed (if any)
                - compensated_steps: list of steps that were compensated
            show_state_markers: If True, show initial (●) and final (◎) state nodes

        Returns:
            Mermaid diagram string that can be rendered in markdown.

        Example:
            >>> saga.to_mermaid(highlight_trail={
            ...     "completed_steps": ["reserve", "charge"],
            ...     "failed_step": "ship",
            ...     "compensated_steps": ["charge", "reserve"]
            ... })
        """
        from sagaz.visualization.mermaid import HighlightTrail, MermaidGenerator, StepInfo

        # Convert steps to StepInfo format
        steps = [
            StepInfo(
                name=s.step_id,
                has_compensation=s.compensation_fn is not None,
                depends_on=set(s.depends_on),
            )
            for s in self._steps  # type: ignore[attr-defined]
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

        Fetches the saga execution state from storage and highlights
        the actual path taken.

        Args:
            saga_id: The saga execution ID to visualize
            storage: SagaStorage instance to fetch execution data from
            direction: Flowchart direction
            show_compensation: If True, show compensation nodes
            show_state_markers: If True, show initial/final nodes

        Returns:
            Mermaid diagram with highlighted execution trail.

        Example:
            >>> from sagaz.storage import PostgreSQLSagaStorage
            >>> storage = PostgreSQLSagaStorage(...)
            >>> diagram = await saga.to_mermaid_with_execution(
            ...     saga_id="abc-123",
            ...     storage=storage
            ... )
        """
        # Fetch saga state from storage
        saga_data = await storage.load_saga_state(saga_id)

        if not saga_data:
            # No execution found, return diagram without highlighting
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

        # Build highlight trail
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
