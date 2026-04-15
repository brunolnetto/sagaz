# ADR-038: StateChart-Based Context-Scoped Saga State Management

## Status

**Proposed** — 🚧 **IN PROGRESS** (Phase 1: v1.6.0 · Phase 2: v2.3.0)

## Context

`python-statemachine` 3.0.0 (released February 24 2026) introduced `StateChart`
as the recommended base class for all new state machines, replacing `StateMachine`
with SCXML-compliant defaults.  The existing `SagaStateMachine` and
`SagaStepStateMachine` in `sagaz/execution/state_machine.py` still inherit from
the 2.x `StateMachine` class, which is now a backward-compatibility shim.

This creates several compounding problems:

| Problem | Impact |
|---------|--------|
| `current_state` is deprecated (returns a single `State`) | Misleading for compound/parallel regions; will break in a future release |
| No typed domain model attachment | `SagaContext` is not part of the state machine; callbacks rely on closures |
| Error handling in entry callbacks uses manual `try/except` | Scattered; no structured routing; exceptions can surface in the wrong layer |
| Parallel DAGSaga step tracking is purely external | `SagaStateMachine` has no visibility into which steps are currently active |
| Snapshot `current_state` field is a single string | Cannot represent concurrent step configurations |
| Storage layer persists only `status` (scalar enum) | Full execution configuration is invisible to operators and tooling |

The new `StateChart` class directly addresses all of these:

- **`StateChart[TModel]`** — typed generic attaches `SagaContext` as the domain
  model; `sm.model` resolves to `SagaContext` with full type inference.
- **`configuration` / `configuration_values`** — returns the full set of active
  states (an `OrderedSet[State]`) even when compound and parallel regions are active.
- **`is_terminated`** — correct termination check for flat, compound, and parallel
  topologies.
- **`error.execution` routing** — SCXML-native structured error handling replaces
  manual try/except inside state entry callbacks.
- **`State.Compound` / `State.Parallel`** — models concurrent step execution
  regions directly in the state machine (Phase 2).
- **`invoke`** — spawns step execution as background work when a state is entered
  and cancels it on exit; `done_state_` events fire automatically on completion
  (Phase 2).
- **`DoneData`** — final substates carry step results, removing the result-storage
  workaround in `_StepExecutor` (Phase 2).
- **`HistoryState`** — restores the compensation ordering on re-entry to
  `COMPENSATING` after an interrupted rollback (Phase 2).

## Decision

Migrate the saga execution engine to `StateChart` in two phases.

---

### Phase 1 — Base Class Migration & Storage Configuration Field

**Target**: v1.6.0 (Wave 1)

#### 1.1 Dependency upgrade

Bump `python-statemachine` to `^3.0` in `pyproject.toml`.  The existing
`StateMachine` class is a backward-compatible subclass of `StateChart` so the
upgrade does not break the 2.x behaviour for external consumers.

#### 1.2 Base class swap

```python
# Before
from statemachine import State, StateMachine

class SagaStateMachine(StateMachine):
    ...

class SagaStepStateMachine(StateMachine):
    ...
```

```python
# After
from statemachine import State, StateChart

class SagaStateMachine(StateChart["SagaContext"]):
    ...

class SagaStepStateMachine(StateChart):
    ...
```

The `StateChart` class enables SCXML defaults automatically:
`catch_errors_as_events`, `enable_self_transition_entries`, and non-atomic
configuration updates.

#### 1.3 `SagaContext` as typed model

`StateChart[SagaContext]` attaches the context as `sm.model`, injected at
construction time:

```python
sm = SagaStateMachine(model=saga_context)
# sm.model is SagaContext — fully typed
```

This removes the pattern of passing `saga` as an opaque attribute and
referencing `self.saga._on_enter_executing()` from callbacks.  Callbacks
receive the context directly via dependency injection.

#### 1.4 Replace `current_state` with `configuration_values`

All internal accesses to `sm.current_state` are replaced with
`sm.configuration_values` (returns `list[str]`).

```python
# sagaz/core/saga/_snapshot.py — before
@property
def current_state(self) -> str:
    return self._state_machine.current_state.name

# After
@property
def configuration(self) -> list[str]:
    return list(self._state_machine.configuration_values)
```

Snapshot schema is versioned: records written before Phase 1 have a
`current_state: str` field; the snapshot loader maps it to
`configuration: [current_state]` automatically.

#### 1.5 Structured error routing via `error.execution`

`StateChart` catches exceptions raised during transitions and dispatches an
internal `error.execution` event when `catch_errors_as_events = True` (the
default).  This removes the need for `try/except` blocks inside entry
callbacks:

```python
class SagaStateMachine(StateChart["SagaContext"]):
    ...
    # Transition triggered automatically when an exception occurs in callbacks
    error_execution = executing.to(failed)

    def on_enter_failed(self, error=None, **kwargs):
        # `error` injected by StateChart; no explicit try/except needed
        if error:
            logger.error("Saga execution failed", exc_info=error)
```

#### 1.6 `is_terminated` usage

Replace boolean checks against named final states with `sm.is_terminated`:

```python
# Before
if sm.current_state.id in {"completed", "rolled_back", "failed"}:
    ...

# After
if sm.is_terminated:
    ...
```

#### 1.7 Storage `configuration` field

Extend `save_saga_state` in all storage backends to accept and persist a
`configuration: list[str]` field alongside the existing `status` scalar.

```python
await storage.save_saga_state(
    saga_id=saga_id,
    status=SagaStatus.EXECUTING,
    configuration=["executing"],     # ← new field
    ...
)
```

Schema / serialisation rules:
- **Memory**: new key `"configuration"` in the saga record dict
- **PostgreSQL**: new nullable `JSON` column `configuration` (migration script provided)
- **Redis**: new key `{saga_id}:configuration` (JSON-serialized list)
- **Backward compatibility**: when loading a record without `configuration`,
  default to `[record["status"]]`

---

### Phase 2 — Compound/Parallel Step Regions

**Target**: v2.3.0 (Wave 5) · Protected behind `SagaConfig.use_step_statechart`

Phase 2 remodels the flat `EXECUTING` state as an `State.Compound` that
contains one sub-state per step (or per parallel region in `DAGSaga`):

```
executing (Compound)
├── step_reserve_inventory (Compound)
│   ├── pending (initial)
│   ├── running
│   └── done (final)
├── step_charge_payment (Compound)    ← parallel via State.Parallel wrapper
│   ├── pending (initial)
│   ├── running
│   └── done (final)
```

**`invoke` for step lifecycle** — each compound step state launches its action
via the `invoke` parameter, so its execution is tied to state entry/exit:

```python
class step_reserve_inventory(State.Compound):
    pending = State(initial=True)
    running = State(invoke=_run_step)
    done = State(final=True, donedata="get_result")
    start = pending.to(running)
    done_invoke_running = running.to(done)
```

**`DoneData` for result propagation** — when a step's final substate is
reached, its `donedata` callback fires and the result flows into
`SagaContext` via the `done_state_` event, removing the result-storage
workaround in `_StepExecutor`.

**`HistoryState` for compensation** — the `COMPENSATING` compound state uses
`HistoryState(type="deep")` so re-entering it after an interruption restores
exactly which compensations were in progress.

**Opt-in flag**:

```python
config = SagaConfig(
    use_step_statechart=True,   # Phase 2 behaviour (default: False)
    ...
)
```

When `False` (default), the Phase 1 flat statechart is used unchanged.

---

## Alternatives Considered

### A: Stay on `StateMachine` (2.x)

No migration cost, but `current_state` deprecation warnings will accumulate and
the API will eventually be removed.  Parallel step state is fundamentally
unrepresentable in a flat machine.  Rejected.

### B: Replace python-statemachine with a custom state engine

Full control over internals but loses the SCXML-compliance work, the
well-tested library semantics, and vendor support.  Estimated at 3× the
engineering cost.  Rejected.

### C: Keep `StateMachine` base, add `configuration` property manually

Possible short-term, but pollutes the API with a parallel abstraction that
diverges from the upstream library.  Does not enable Phase 2 compound states.
Rejected.

### D: Implement Phase 2 immediately (skip Phase 1)

Phase 1 is a prerequisite: `StateChart` base class and typed model must be in
place before compound substates are added.  Skipping it makes Phase 2 harder
to review and test in isolation.  Rejected.

## Consequences

### Positive

- `current_state` deprecation warnings disappear across the codebase.
- `SagaContext` is the typed domain model for the state machine;
  dependency injection makes callbacks cleaner and testable in isolation.
- Storage `configuration` field gives operators and debugging tooling a full
  record of the active state set, not just the coarse scalar `status`.
- Snapshot/replay (ADR-024) can reconstruct parallel-step configurations
  precisely, ending gaps where concurrent step state was opaque.
- Phase 2 enables `DAGSaga` parallel step regions to be modelled natively,
  removing the external polling loop in `SagaExecutionGraph`.
- Structured `error.execution` routing reduces cognitive load for contributors;
  error paths are declared alongside state topology, not scattered through
  entry callbacks.

### Negative

- Phase 1 requires a storage schema migration for PostgreSQL deployments
  (new `configuration` column).  The migration script is additive and safe to
  run online.
- Phase 2 is a significant redesign of `SagaStateMachine`; the opt-in flag
  means two code paths must be maintained until Phase 2 is the default.
- `StateChart` SCXML defaults differ from `StateMachine` 2.x in self-transition
  behaviour and configuration-update timing.  All existing state machine unit
  tests must be reviewed against the upgrade guide.

## Implementation Reference

| File | Change |
|------|--------|
| `pyproject.toml` | `python-statemachine ^3.0` |
| `sagaz/execution/state_machine.py` | `StateMachine` → `StateChart`; `configuration_values`; `error.execution`; `is_terminated` |
| `sagaz/core/saga/_snapshot.py` | `current_state` → `configuration` (list) |
| `sagaz/storage/base.py` | `configuration: list[str]` in `save_saga_state` signature |
| `sagaz/storage/memory.py` | Persist `configuration` field |
| `sagaz/storage/redis.py` | Persist `configuration` field |
| `sagaz/storage/postgresql.py` | Persist `configuration` column; migration script |
| `docs/planning/release-plan.md` | Insert Phase 1 PR into Wave 1 |
| `docs/ROADMAP.md` | Mention StateChart migration under Q2 2026 |

## Links

- [python-statemachine 3.0.0 release notes](https://python-statemachine.readthedocs.io/en/latest/releases/3.0.0.html)
- [StateChart runtime reference](https://python-statemachine.readthedocs.io/en/latest/statechart.html)
- [Upgrading from 2.x to 3.0](https://python-statemachine.readthedocs.io/en/latest/releases/upgrade_2x_to_3.html)
- [ADR-024: Saga Replay & Time-Travel](adr-024-saga-replay.md)
- [ADR-036: Lifecycle Hooks & Observers](adr-036-lifecycle-hooks-observers.md)
- [GitHub Issue #188](https://github.com/brunolnetto/sagaz/issues/188)
