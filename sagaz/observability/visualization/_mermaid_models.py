"""Data models shared by the Mermaid diagram generator."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepInfo:
    """Normalized step information for Mermaid generation."""

    name: str
    has_compensation: bool
    depends_on: set[str] = field(default_factory=set)
    # v1.3.0: Pivot support
    pivot: bool = False
    """True if this step is a pivot (point of no return)."""
    tainted: bool = False
    """True if this step is tainted (ancestor of completed pivot)."""


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


class _MermaidState:
    """Attributes shared by the MermaidGenerator rendering mixins."""

    steps: list[StepInfo]
    direction: str
    show_compensation: bool
    show_state_markers: bool
    trail: HighlightTrail
    show_pivot_zones: bool
    _step_map: dict[str, StepInfo]
    _compensable_steps: list[StepInfo]
    _has_deps: bool
    _root_steps: list[StepInfo]
    _leaf_steps: list[StepInfo]
    _pivot_steps: list[StepInfo]
    _tainted_steps: list[StepInfo]
    _has_pivots: bool
    _lines: list[str]
    _link_count: int
    _success_links: list[str]
    _compensation_links: list[str]
