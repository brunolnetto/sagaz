"""A static Mermaid diagram of a choreography (#565).

Orchestrated sagas draw their steps with ``to_mermaid()``. A choreography is drawn from
its participants' declarations: the event types each one handles, which of those it can
compensate, and what each handler declared it emits (``emits=``). The graph has
an event → participant edge for each event type a participant handles, and a
participant → event edge for each type a handler declared it emits.

A handler without ``emits=`` is drawn with a note, ``emits undeclared on <event>``: what
it publishes is only known at run time. Completion events are drawn as final nodes. When
every handler declared what it emits, the events nobody emits are drawn as entry points.

The diagram shows the participants given, for example those registered on one engine.
A choreography spread across services is drawn whole from its shared definition (#626,
#627).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sagaz.choreography.events import COMPENSATE

if TYPE_CHECKING:
    from sagaz.choreography.saga import ChoreographedSaga

_DIRECTIONS = frozenset({"TB", "TD", "BT", "LR", "RL"})

_STYLES = (
    "classDef participant fill:#e8f0fe,stroke:#4a6fa5,color:#1a2b4a",
    "classDef event fill:#f6f8fa,stroke:#8c959f,color:#24292f",
    "classDef entry fill:#e6f4ea,stroke:#2e7d32,color:#1b4d20",
    "classDef completion fill:#e6f4ea,stroke:#2e7d32,stroke-width:3px,color:#1b4d20",
    "classDef compensate fill:#fff4e5,stroke:#b26a00,color:#5c3700",
    "classDef undeclared stroke-dasharray:4 3",
)


def label(text: str) -> str:
    """Escape *text* for a quoted Mermaid label."""
    replacements = {"&": "#amp;", '"': "#quot;", "<": "#lt;", ">": "#gt;", "\n": " ", "\r": " "}
    return "".join(replacements.get(ch, ch) for ch in text)


def choreography_mermaid(
    participants: Iterable[ChoreographedSaga],
    *,
    completion_events: Iterable[str] = (),
    direction: str = "LR",
    show_compensation: bool = True,
) -> str:
    """A Mermaid flowchart of *participants* and the events between them.

    Args:
        participants: The participants to draw (for example an engine's).
        completion_events: Event types that complete a transaction: final nodes.
        direction: ``"LR"`` (left to right), ``"TB"`` (top to bottom), ...
        show_compensation: Draw ``choreography.compensate`` and who compensates on it.
    """
    if direction not in _DIRECTIONS:
        msg = f"direction must be one of {sorted(_DIRECTIONS)}, not {direction!r}"
        raise ValueError(msg)
    diagram = _Diagram(sorted(participants, key=lambda p: p.name), frozenset(completion_events))
    lines = [f"flowchart {direction}"]
    lines += diagram.event_nodes()
    lines += diagram.participant_nodes()
    lines += diagram.edges()
    if show_compensation:
        lines += diagram.compensation()
    lines += _STYLES
    return "\n".join(lines[:1] + [f"    {line}" for line in lines[1:]])


class _Diagram:
    """The participants' declarations, as nodes and edges."""

    def __init__(self, participants: list[ChoreographedSaga], completion: frozenset[str]) -> None:
        self.participants = participants
        self.completion = completion
        # participant -> {event type it handles -> what it declared it emits, or None}
        self.declared = {p.name: {e: p.emits(e) for e in sorted(p._handlers)} for p in participants}
        self.emitted = {t for d in self._declarations() if d for t in d}
        self.complete = all(d is not None for d in self._declarations())
        self.event_id = {event: f"e{i}" for i, event in enumerate(self._events())}
        self.participant_id = {p.name: f"p{i}" for i, p in enumerate(participants)}

    def _events(self) -> list[str]:
        """Every event type drawn: handled, declared emitted, or completing."""
        handled = {event for emits in self.declared.values() for event in emits}
        return sorted(self.completion | self.emitted | handled)

    def _declarations(self) -> list[frozenset[str] | None]:
        return [d for emits in self.declared.values() for d in emits.values()]

    def event_nodes(self) -> list[str]:
        lines = []
        for event, node in self.event_id.items():
            if event in self.completion:
                lines.append(f'{node}((("{label(event)}"))):::completion')
            else:
                entry = self.complete and event not in self.emitted
                lines.append(f'{node}(["{label(event)}"]):::{"entry" if entry else "event"}')
        return lines

    def participant_nodes(self) -> list[str]:
        lines = []
        for p in self.participants:
            missing = [e for e, d in self.declared[p.name].items() if d is None]
            text = label(p.name)
            if missing:
                text += "<br/>" + label("emits undeclared on " + ", ".join(missing))
            node = self.participant_id[p.name]
            lines.append(f'{node}["{text}"]:::participant')
            if missing:  # ``:::`` takes one class
                lines.append(f"class {node} undeclared")
        return lines

    def edges(self) -> list[str]:
        lines = []
        for p in self.participants:
            node = self.participant_id[p.name]
            for event, emits in self.declared[p.name].items():
                arrow = '-->|"compensable"|' if event in p._compensators else "-->"
                lines.append(f"{self.event_id[event]} {arrow} {node}")
                lines += [f"{node} --> {self.event_id[out]}" for out in sorted(emits or ())]
        return lines

    def compensation(self) -> list[str]:
        undoers = [p for p in self.participants if p._compensators]
        if not undoers:
            return []
        lines = [f'compensate(["{label(COMPENSATE)}"]):::compensate']
        for p in undoers:
            undone = label("undo " + ", ".join(sorted(p._compensators)))
            lines.append(f'compensate -.->|"{undone}"| {self.participant_id[p.name]}')
        return lines
