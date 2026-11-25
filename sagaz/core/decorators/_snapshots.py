"""Snapshots and replay for ``sagaz.Saga`` (#544).

With ``SagaConfig(replay_config=ReplayConfig(enable_snapshots=True, ...),
snapshot_storage=...)``, a run saves a ``SagaSnapshot`` of its context and completed steps
at the points its strategy names: before or after each step, on completion, on failure.
``SagaReplay`` and ``SagaTimeTravel`` read them.

``saga.run_from_snapshot(snapshot)`` runs the saga again from a snapshot, as a new run:
the steps completed in the snapshot are adopted, not run again, and the rest run as
usual. If the replay then fails, the adopted steps are compensated too.

Snapshot storage identifies a saga by a UUID, and a saga id may be any string:
:func:`snapshot_saga_id` gives the UUID of a saga id (itself, if it is one).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sagaz.core.events import json_safe

if TYPE_CHECKING:
    from sagaz.core.replay import ReplayConfig, SagaSnapshot, SnapshotStrategy
    from sagaz.core.storage.interfaces.snapshot import SnapshotStorage

logger = logging.getLogger(__name__)


def snapshot_saga_id(saga_id: str | UUID) -> UUID:
    """The UUID under which *saga_id*'s snapshots are stored.

    A saga id that is a UUID is itself; any other string gets a stable UUID (version 5),
    so the same saga id always finds its snapshots.
    """
    if isinstance(saga_id, UUID):
        return saga_id
    try:
        return UUID(saga_id)
    except ValueError:
        return uuid5(NAMESPACE_URL, f"sagaz:saga:{saga_id}")


class Snapshots:
    """Saves one run's snapshots, and knows which steps a replay adopts."""

    def __init__(
        self,
        config: object = None,
        saga_name: str = "",
        saga_id: str = "",
        adopted: frozenset[str] = frozenset(),
    ) -> None:
        self._replay = _replay_config(config)
        self._storage: SnapshotStorage | None = getattr(config, "snapshot_storage", None)
        self._saga_name = saga_name
        self._saga_id = saga_id
        #: Steps completed in the snapshot being replayed: adopted, not run.
        self.adopted = adopted

    def _wants(self, moment: str) -> bool:
        replay = self._replay
        if replay is None or not replay.enable_snapshots:
            return False
        if self._storage is None:
            logger.warning("Snapshot capture enabled but no snapshot_storage configured")
            return False
        return _MOMENTS[moment] == _name(replay.snapshot_strategy)

    async def capture(
        self,
        moment: str,
        step_name: str,
        step_index: int,
        status: str,
        context: dict[str, Any],
        completed_steps: list[str],
        configuration: list[str],
    ) -> None:
        """Save a snapshot if the strategy asks for one at *moment*.

        *moment* is ``"before"`` or ``"after"`` a step, ``"completed"`` or ``"failed"``.
        A snapshot that cannot be saved is logged; the run goes on.
        """
        if not self._wants(moment):
            return
        from sagaz.core.replay import SagaSnapshot

        replay, storage = self._replay, self._storage
        assert replay is not None
        assert storage is not None
        try:
            snapshot = SagaSnapshot.create(
                saga_id=snapshot_saga_id(self._saga_id),
                saga_name=self._saga_name,
                step_name=step_name,
                step_index=step_index,
                status=status,
                context=json_safe(context),
                completed_steps=list(completed_steps),
                retention_until=replay.get_retention_until(),
                configuration=list(configuration),
            )
            await storage.save_snapshot(snapshot)
        except Exception as error:
            logger.error(f"Failed to capture snapshot: {error}", exc_info=True)


#: The strategy that asks for a snapshot at each moment.
_MOMENTS = {
    "before": "BEFORE_EACH_STEP",
    "after": "AFTER_EACH_STEP",
    "completed": "ON_COMPLETION",
    "failed": "ON_FAILURE",
}


def _name(strategy: SnapshotStrategy) -> str:
    return str(getattr(strategy, "name", strategy)).upper()


def _replay_config(config: object) -> ReplayConfig | None:
    """``config.replay_config`` if it is a ReplayConfig (a config may be any object, even a mock)."""
    from sagaz.core.replay import ReplayConfig

    value = getattr(config, "replay_config", None)
    return value if isinstance(value, ReplayConfig) else None


class _Step(Protocol):
    """What adopting a step reads of its definition."""

    step_id: str
    pivot: bool


class _ReplayEngine(Protocol):
    """What ``run_from_snapshot`` uses of the saga's execution engine."""

    adopted: frozenset[str]

    async def run(
        self, initial_context: dict[str, Any], saga_id: str | None = None
    ) -> dict[str, Any]: ...


def replay_context(
    snapshot: SagaSnapshot, context_override: dict[str, Any] | None
) -> dict[str, Any]:
    """The context a replay of *snapshot* starts from: the snapshot's, then the overrides."""
    context = dict(snapshot.context)
    context.pop("saga_id", None)  # the replay is a new run, with its own id
    context.update(context_override or {})
    return context


class _EngineSnapshotMixin:
    """Snapshot capture and step adoption for the execution engine."""

    if TYPE_CHECKING:
        saga: Any
        _ledger: Any
        _snapshots: Snapshots

        async def _chart_step(self, step_id: str, event: str) -> None: ...
        async def _chart_taint(self, step_ids: set[str]) -> None: ...

    async def _snapshot(self, moment: str, step_name: str = "") -> None:
        """Save a snapshot at *moment* if the saga's replay strategy asks for one."""
        # In execution order (level by level), which is the order a replay follows.
        names = [step.step_id for level in self.saga.get_execution_order() for step in level]
        context = self.saga._context
        status = moment if moment in ("completed", "failed") else "executing"
        await self._snapshots.capture(
            moment,
            step_name,
            names.index(step_name) if step_name in names else len(names),
            status,
            context,
            [name for name in names if context.get(f"__{name}_completed")],
            self.saga.state_configuration,
        )

    async def _adopt(self, step: _Step) -> None:
        """Take a step the replayed snapshot completed as done, without running it."""
        step_id = step.step_id
        logger.info(f"Skipping step '{step_id}' - completed in the replayed snapshot")
        self._ledger.started(step_id)
        self._ledger.finished(step_id)
        await self._chart_step(step_id, "adopt")
        self.saga._context[f"__{step_id}_completed"] = True
        self.saga._compensation_graph.mark_step_executed(step_id)  # undone if the replay fails
        if step.pivot:
            await self._chart_taint(self.saga._propagate_taint_from_pivot(step_id))


class _DecoratorSnapshotMixin:
    """``run_from_snapshot`` for the declarative Saga class."""

    if TYPE_CHECKING:
        _steps: list[Any]

        def _engine(self, allow_rerun: bool) -> _ReplayEngine: ...

    async def run_from_snapshot(
        self,
        snapshot: SagaSnapshot,
        context_override: dict[str, Any] | None = None,
        saga_id: str | None = None,
    ) -> dict[str, Any]:
        """Run this saga again from *snapshot*, as a new run (#544).

        The steps the snapshot completed are adopted, not run again; the rest run as in
        ``run()``, from the snapshot's context with *context_override* applied. If the
        replay fails, the adopted steps are compensated with the others. Returns and
        raises what ``run()`` does. *saga_id* is the new run's id (generated if omitted).
        """
        known = {step.step_id for step in self._steps}
        unknown = sorted(set(snapshot.completed_steps) - known)
        if unknown:
            msg = f"the snapshot completed steps this saga does not define: {unknown}"
            raise ValueError(msg)
        engine = self._engine(False)
        engine.adopted = frozenset(snapshot.completed_steps)
        return await engine.run(replay_context(snapshot, context_override), saga_id)
