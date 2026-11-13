"""In-memory projection of visualization events into Saga run records.

The visualization server is fed by :class:`VisualizationSagaListener` over
HTTP. This module folds that event stream into bounded, process-local run
records that back the REST API (run list, run detail, runtime diagram and
metrics summary). Nothing here touches Saga storage backends.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

RunStatus = Literal["running", "compensating", "completed", "failed"]
StepStatus = Literal["running", "completed", "failed", "compensating", "compensated"]

RUN_STATUSES: tuple[RunStatus, ...] = ("running", "compensating", "completed", "failed")

_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed"})


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _duration_ms(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() * 1000, 3)


@dataclass(slots=True)
class StepRecord:
    name: str
    status: StepStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_type: str | None = None
    compensation_started_at: datetime | None = None
    compensated_at: datetime | None = None

    @property
    def duration_ms(self) -> float | None:
        return _duration_ms(self.started_at, self.finished_at)

    @property
    def compensation_duration_ms(self) -> float | None:
        return _duration_ms(self.compensation_started_at, self.compensated_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "error_type": self.error_type,
            "compensation_started_at": (
                self.compensation_started_at.isoformat() if self.compensation_started_at else None
            ),
            "compensated_at": self.compensated_at.isoformat() if self.compensated_at else None,
            "compensation_duration_ms": self.compensation_duration_ms,
        }


@dataclass(slots=True)
class RunRecord:
    saga_id: str
    saga_name: str
    status: RunStatus = "running"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
    error_type: str | None = None
    steps: OrderedDict[str, StepRecord] = field(default_factory=OrderedDict)
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=200))

    @property
    def duration_ms(self) -> float | None:
        return _duration_ms(self.started_at, self.finished_at)

    def summary(self) -> dict[str, Any]:
        return {
            "saga_id": self.saga_id,
            "saga_name": self.saga_name,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "duration_ms": self.duration_ms,
            "error_type": self.error_type,
            "step_count": len(self.steps),
            "current_step": self.current_step,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.summary()
        data["steps"] = [step.to_dict() for step in self.steps.values()]
        data["events"] = list(self.events)
        return data

    @property
    def current_step(self) -> str | None:
        for step in reversed(self.steps.values()):
            if step.status in {"running", "compensating"}:
                return step.name
        return None


class RunStore:
    """Bounded, process-local run projection with event de-duplication."""

    def __init__(self, max_runs: int = 1000, max_seen_event_ids: int = 10_000) -> None:
        if max_runs < 1:
            message = "max_runs must be positive"
            raise ValueError(message)
        if max_seen_event_ids < 1:
            message = "max_seen_event_ids must be positive"
            raise ValueError(message)

        self.max_runs = max_runs
        self._runs: OrderedDict[str, RunRecord] = OrderedDict()
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._max_seen = max_seen_event_ids

    def __len__(self) -> int:
        return len(self._runs)

    # ------------------------------------------------------------------ ingest

    def apply(self, event: dict[str, Any]) -> bool:
        """Fold one event into the projection.

        Returns ``False`` when the event id was already applied (duplicate).
        """
        event_id = str(event["event_id"])
        if event_id in self._seen_ids:
            return False
        self._remember(event_id)

        saga_id = str(event["saga_id"])
        run = self._runs.get(saga_id)
        if run is None:
            run = RunRecord(saga_id=saga_id, saga_name=str(event["saga_name"]))
            self._runs[saga_id] = run
            self._evict()
        else:
            self._runs.move_to_end(saga_id)

        occurred_at = _parse_ts(event["occurred_at"])
        run.updated_at = occurred_at
        run.events.append(event)
        self._apply_to_run(run, event, occurred_at)
        return True

    def _remember(self, event_id: str) -> None:
        self._seen_ids.add(event_id)
        self._seen_order.append(event_id)
        while len(self._seen_order) > self._max_seen:
            self._seen_ids.discard(self._seen_order.popleft())

    def _evict(self) -> None:
        while len(self._runs) > self.max_runs:
            victim = next(
                (sid for sid, r in self._runs.items() if r.status in _TERMINAL_RUN_STATUSES),
                next(iter(self._runs)),
            )
            del self._runs[victim]

    @staticmethod
    def _step(run: RunRecord, name: str) -> StepRecord:
        step = run.steps.get(name)
        if step is None:
            step = StepRecord(name=name, status="running")
            run.steps[name] = step
        return step

    def _apply_to_run(self, run: RunRecord, event: dict[str, Any], ts: datetime) -> None:
        event_type = event["event_type"]
        step_name = event.get("step_name")
        error_type = event.get("error_type")

        if event_type == "saga.started":
            run.started_at = ts
            run.status = "running"
        elif event_type == "saga.completed":
            run.status = "completed"
            run.finished_at = ts
        elif event_type == "saga.failed":
            run.status = "failed"
            run.finished_at = ts
            run.error_type = error_type
        elif step_name is not None:
            self._apply_step_event(run, event_type, step_name, error_type, ts)

    def _apply_step_event(
        self,
        run: RunRecord,
        event_type: str,
        step_name: str,
        error_type: str | None,
        ts: datetime,
    ) -> None:
        step = self._step(run, step_name)
        if event_type == "step.started":
            step.status = "running"
            step.started_at = ts
        elif event_type == "step.succeeded":
            step.status = "completed"
            step.finished_at = ts
        elif event_type == "step.failed":
            step.status = "failed"
            step.finished_at = ts
            step.error_type = error_type
        elif event_type == "step.compensation_started":
            step.status = "compensating"
            step.compensation_started_at = ts
            if run.status == "running":
                run.status = "compensating"
        elif event_type == "step.compensated":
            step.status = "compensated"
            step.compensated_at = ts

    # ------------------------------------------------------------------- query

    def get(self, saga_id: str) -> RunRecord | None:
        return self._runs.get(saga_id)

    def list(
        self,
        *,
        status: str | None = None,
        saga_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RunRecord], int]:
        """Return runs newest-first, filtered and paginated, plus the total."""
        runs = [
            run
            for run in reversed(self._runs.values())
            if (status is None or run.status == status)
            and (saga_name is None or run.saga_name == saga_name)
        ]
        return runs[offset : offset + limit], len(runs)

    def summary(self) -> dict[str, Any]:
        """Aggregate statistics over the retained runs."""
        by_status = dict.fromkeys(RUN_STATUSES, 0)
        by_saga: dict[str, dict[str, int]] = {}
        durations: list[float] = []
        steps: dict[str, dict[str, Any]] = {}

        for run in self._runs.values():
            by_status[run.status] += 1
            per_saga = by_saga.setdefault(run.saga_name, dict.fromkeys(RUN_STATUSES, 0))
            per_saga[run.status] += 1
            if run.duration_ms is not None:
                durations.append(run.duration_ms)
            for step in run.steps.values():
                self._accumulate_step(steps, run.saga_name, step)

        finished = by_status["completed"] + by_status["failed"]
        return {
            "total_runs": len(self._runs),
            "by_status": by_status,
            "success_rate": (by_status["completed"] / finished) if finished else None,
            "duration_ms": _duration_stats(durations),
            "by_saga": by_saga,
            "steps": [_finalise_step(entry) for entry in steps.values()],
        }

    @staticmethod
    def _accumulate_step(
        steps: dict[str, dict[str, Any]], saga_name: str, step: StepRecord
    ) -> None:
        key = f"{saga_name}\x00{step.name}"
        entry = steps.setdefault(
            key,
            {
                "saga_name": saga_name,
                "step_name": step.name,
                "executions": 0,
                "failures": 0,
                "compensations": 0,
                "_durations": [],
            },
        )
        entry["executions"] += 1
        if step.error_type is not None or step.status == "failed":
            entry["failures"] += 1
        if step.compensation_started_at is not None:
            entry["compensations"] += 1
        if step.duration_ms is not None:
            entry["_durations"].append(step.duration_ms)


def _duration_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"avg": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "avg": round(sum(ordered) / len(ordered), 3),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "max": ordered[-1],
    }


def _percentile(ordered: list[float], q: float) -> float:
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def _finalise_step(entry: dict[str, Any]) -> dict[str, Any]:
    durations = entry.pop("_durations")
    entry["avg_duration_ms"] = round(sum(durations) / len(durations), 3) if durations else None
    return entry


# ------------------------------------------------------------------- diagram

STEP_STATUS_STYLES: dict[str, str] = {
    "completed": "fill:#16a34a,stroke:#14532d,color:#ffffff",
    "failed": "fill:#dc2626,stroke:#7f1d1d,color:#ffffff",
    "compensating": "fill:#f59e0b,stroke:#78350f,color:#111827",
    "compensated": "fill:#4f46e5,stroke:#312e81,color:#ffffff",
    "running": "fill:#0ea5e9,stroke:#0c4a6e,color:#ffffff",
}


def _mermaid_label(text: str) -> str:
    """Escape untrusted text for a quoted Mermaid node label."""
    replacements = {
        "&": "#amp;",
        '"': "#quot;",
        "<": "#lt;",
        ">": "#gt;",
        "\n": " ",
        "\r": " ",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def saga_runtime_diagram(run: RunRecord, direction: str = "LR") -> str:
    """Render a run as a Mermaid flowchart colour-coded by step state.

    green = completed, red = failed, amber = compensating,
    indigo = compensated, blue = running.
    """
    lines = [f"flowchart {direction}", "  start((start))"]
    previous = "start"

    for index, step in enumerate(run.steps.values()):
        node = f"s{index}"
        label = _mermaid_label(step.name)
        if step.duration_ms is not None:
            label += f"<br/>{step.duration_ms:g} ms"
        lines.append(f'  {node}["{label}"]:::{step.status}')
        lines.append(f"  {previous} --> {node}")
        previous = node

    if run.status in _TERMINAL_RUN_STATUSES:
        end_class = "completed" if run.status == "completed" else "failed"
        end_label = "done" if run.status == "completed" else "rolled back"
        lines.append(f"  finish(({end_label})):::{end_class}")
        lines.append(f"  {previous} --> finish")

    lines.extend(f"  classDef {name} {style}" for name, style in STEP_STATUS_STYLES.items())
    return "\n".join(lines)
