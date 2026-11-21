"""The asset monitor's data layer: saga state as rows and Mermaid (ADR-039).

Plain async functions over a unified saga log (``SagaLogStore``, ADR-041) or a
classic-layout ``SagaStorage``. They only read, and import nothing from Gradio, so the
UI layer stays thin and this one is tested without a browser.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sagaz.core.storage.saga_log._model import TRANSACTION_MARKER
from sagaz.core.tenant import system_scope, tenant_scope

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces import SagaStorage
    from sagaz.core.storage.saga_log import SagaLogStore

TRANSACTION_COLUMNS = (
    "tenant",
    "transaction",
    "coordination",
    "flow",
    "status",
    "initiator",
    "started",
    "duration_ms",
)
STEP_COLUMNS = ("step", "participant", "status", "attempt", "duration_ms", "error")
EVENT_COLUMNS = ("seq", "event", "kind", "source", "caused_by", "at")

# Mermaid classes per status (orchestrated steps and choreography events).
_STYLES = {
    "completed": "fill:#d3f9d8,stroke:#2b8a3e",
    "compensated": "fill:#fff3bf,stroke:#e67700",
    "compensating": "fill:#fff3bf,stroke:#e67700",
    "failed": "fill:#ffe3e3,stroke:#c92a2a",
    "compensation_failed": "fill:#ffe3e3,stroke:#c92a2a",
    "executing": "fill:#d0ebff,stroke:#1971c2",
    "pending": "fill:#f1f3f5,stroke:#868e96",
}


def _time(value: datetime | None) -> str:
    return "" if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


def _ms(start: datetime | None, end: datetime | None) -> float | None:
    return None if start is None or end is None else round((end - start).total_seconds() * 1000, 1)


def _label(text: str) -> str:
    """Text safe inside a Mermaid node label."""
    return re.sub(r'["<>{}\[\]|]', "", str(text))[:60] or "?"


def _classes(statuses: dict[str, str]) -> list[str]:
    used = sorted({s for s in statuses.values() if s in _STYLES})
    lines = [f"    classDef {s} {_STYLES[s]}" for s in used]
    lines += [f"    class {node} {s}" for node, s in statuses.items() if s in _STYLES]
    return lines


# -- unified saga log ----------------------------------------------------------------


async def list_transactions(
    log: SagaLogStore,
    *,
    coordination: str | None = None,
    flow: str | None = None,
    status: str | None = None,
    tenant: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Transactions of every tenant (or *tenant*), newest first."""
    scope = system_scope() if not tenant else tenant_scope(tenant)
    with scope:
        transactions = await log.list_transactions(
            flow=flow or None, coordination=coordination or None, status=status or None, limit=limit
        )
    return [
        {
            "tenant": t.tenant_id,
            "transaction": t.transaction_id,
            "coordination": str(t.coordination),
            "flow": t.flow,
            "status": t.status,
            "initiator": t.initiator or "",
            "started": _time(t.started_at),
            "duration_ms": _ms(t.started_at, t.ended_at),
        }
        for t in transactions
    ]


async def transaction_detail(
    log: SagaLogStore, tenant: str, transaction_id: str
) -> dict[str, Any] | None:
    """A transaction's steps, events, context and diagram, or None if unknown."""
    with tenant_scope(tenant):
        transaction = await log.get_transaction(transaction_id)
        if transaction is None:
            return None
        activities = await log.activities(transaction_id)
        events = await log.events(transaction_id)
    steps = [a for a in activities if a.name != TRANSACTION_MARKER]
    choreographed = str(transaction.coordination) == "choreographed"
    return {
        "transaction": transaction_id,
        "coordination": str(transaction.coordination),
        "status": transaction.status,
        "steps": [
            {
                "step": a.name,
                "participant": a.participant,
                "status": a.status,
                "attempt": a.attempt,
                "duration_ms": a.duration_ms,
                "error": a.error or "",
            }
            for a in steps
        ],
        "events": [
            {
                "seq": e.sequence,
                "event": e.event_type,
                "kind": str(e.kind),
                "source": e.source or "",
                "caused_by": e.causation_id or "",
                "at": _time(e.occurred_at),
            }
            for e in events
        ],
        "context": transaction.context,
        "mermaid": causation_diagram(events) if choreographed else steps_diagram(steps),
    }


def steps_diagram(steps: list[Any]) -> str:
    """Orchestrated steps in start order, colored by status."""
    ordered = sorted(steps, key=lambda a: (a.started_at is None, a.started_at or datetime.min))
    lines = ["flowchart LR"]
    statuses: dict[str, str] = {}
    for i, step in enumerate(ordered):
        node = f"s{i}"
        lines.append(f'    {node}["{_label(step.name)}<br/>{_label(step.status)}"]')
        statuses[node] = step.status
        if i:
            lines.append(f"    s{i - 1} --> {node}")
    if not ordered:
        lines.append('    empty["no steps recorded"]')
    return "\n".join(lines + _classes(statuses))


def causation_diagram(events: list[Any]) -> str:
    """Choreography events as a causation graph, labelled by participant."""
    lines = ["flowchart LR"]
    nodes = {e.event_id: f"e{i}" for i, e in enumerate(events)}
    statuses: dict[str, str] = {}
    for event in events:
        node = nodes[event.event_id]
        who = event.source or "?"
        lines.append(f'    {node}["{_label(who)}: {_label(event.event_type)}"]')
        kind = str(event.kind)
        if kind == "compensate":
            statuses[node] = "failed"
        elif kind == "compensated":
            statuses[node] = "compensated"
        elif kind == "business":
            statuses[node] = "completed"
        cause = nodes.get(event.causation_id or "")
        if cause is not None:
            lines.append(f"    {cause} --> {node}")
    if not events:
        lines.append('    empty["no events recorded"]')
    return "\n".join(lines + _classes(statuses))


# -- classic saga storage ------------------------------------------------------------


async def list_sagas(
    storage: SagaStorage, *, status: str | None = None, limit: int = 200
) -> list[dict]:
    """Sagas of a classic-layout ``SagaStorage``, as transaction rows."""
    from sagaz.core.types import SagaStatus

    with system_scope():
        sagas = await storage.list_sagas(status=SagaStatus(status) if status else None, limit=limit)
    return [
        {
            "tenant": saga.get("tenant_id") or "default",
            "transaction": saga.get("saga_id"),
            "coordination": "orchestrated",
            "flow": saga.get("saga_name") or "",
            "status": str(saga.get("status") or ""),
            "initiator": "",
            "started": str(saga.get("created_at") or "")[:19],
            "duration_ms": None,
        }
        for saga in sagas
    ]


async def saga_detail(storage: SagaStorage, tenant: str, saga_id: str) -> dict[str, Any] | None:
    """A classic-layout saga's steps, context and diagram, or None if unknown."""
    with tenant_scope(tenant):
        state = await storage.load_saga_state(saga_id)
    if not state:
        return None
    raw_steps = state.get("steps") or []
    steps = [
        {
            "step": s.get("name", "?"),
            "participant": "",
            "status": str(s.get("status", "")),
            "attempt": s.get("retry_count", 0) + 1,
            "duration_ms": None,
            "error": s.get("error") or "",
        }
        for s in raw_steps
    ]
    lines = ["flowchart LR"]
    statuses: dict[str, str] = {}
    for i, step in enumerate(steps):
        lines.append(f'    s{i}["{_label(step["step"])}<br/>{_label(step["status"])}"]')
        statuses[f"s{i}"] = step["status"]
        if i:
            lines.append(f"    s{i - 1} --> s{i}")
    return {
        "transaction": saga_id,
        "coordination": "orchestrated",
        "status": str(state.get("status") or ""),
        "steps": steps,
        "events": [],
        "context": state.get("context") or {},
        "mermaid": "\n".join(lines + _classes(statuses)),
    }


def mermaid_markdown(diagram: str) -> str:
    """The diagram as a Markdown fence, which Gradio renders."""
    return f"```mermaid\n{diagram}\n```"


def as_json(value: Any) -> Any:
    """A JSON-safe copy (contexts may hold datetimes or other objects)."""
    return json.loads(json.dumps(value, default=str))
