# ADR-040: StateChart for the Saga Lifecycle (Phase 1)

## Status

**Accepted** — 2026-11-11

- Initial implementation: v1.7.0 (PR #363)
- Dependency security floor: `python-statemachine>=3.2.0` (PR #365)
- Phase 1 completion evidence and regression hardening: v1.7.1
- Follow-up: Phase 2 remains separately scoped in issue #190

## Context

Sagaz originally modeled the Saga and individual Saga-step lifecycles with
`python-statemachine.StateMachine`. The library's 3.x line introduced
`StateChart`, which exposes the active state configuration and provides a
foundation for compound and parallel state topologies.

A direct migration to `StateChart` changes several runtime defaults to SCXML
semantics. In particular, unmatched events may be ignored, self-transitions may
run entry/exit callbacks, configuration changes may be visible incrementally
during a microstep, and callback exceptions may be converted to internal
`error.execution` events. Those changes are not compatible with Sagaz's
existing executor contract: the Saga executor owns error propagation and
compensation, and callers rely on invalid transitions failing explicitly.

The first migration therefore needs to expose serializable configuration while
preserving the flat lifecycle and its established runtime behavior. It must
also preserve records written by older versions in every supported Saga storage
backend and in historical snapshots.

## Decision

### 1. Adopt StateChart without enabling Phase 2 topology

`SagaStateMachine` and `SagaStepStateMachine` inherit from
`python-statemachine.StateChart`. Phase 1 keeps their state topology flat.
This migration does not introduce compound states, parallel regions, invoked
activities, completion data, or history states.

### 2. Explicitly retain the legacy runtime contract

Both state-machine classes declare these class-level settings:

| Attribute | Phase 1 value | Preserved behavior |
|---|---:|---|
| `allow_event_without_transition` | `False` | An unmatched event or failed guard raises `TransitionNotAllowed`. |
| `enable_self_transition_entries` | `False` | Disables target entry for internal self-transitions; external self-transitions still execute exit and entry callbacks. |
| `atomic_configuration_update` | `True` | Transition callbacks observe the pre-transition configuration; the configuration is replaced atomically after the transition callback completes. |
| `catch_errors_as_events` | `False` | Callback exceptions propagate to the caller and remain under Saga executor control. |

These values are intentional compatibility settings, not incidental library
defaults. Tests must verify their observable behavior as well as their values.

For self-transitions, `to.itself()` defaults to `internal=False`.
External self-transitions execute both exit and entry callbacks regardless
of `enable_self_transition_entries`.

For `internal=True`, the source state is not exited. With
`enable_self_transition_entries=False`, the target is not re-entered and no
lifecycle callbacks execute. With the flag set to `True`, the target is
entered and its entry callback executes, but no exit callback executes.

Phase 1's Saga and step lifecycle declarations do not currently define
self-transitions. The regression suite explicitly verifies both external and
internal self-transition behavior under the relevant flag settings.

### 3. Preserve existing state inspection APIs

The state-machine `current_state` accessor continues to return a State object
for the existing flat machines. The imperative Saga's `current_state` remains
its existing state-name representation.

The active StateChart configuration is exposed separately through
`Saga.state_configuration` and the Saga status projection. Configuration
values are serialized as a list of strings, so consumers do not need to depend
on StateChart's in-memory State objects.

### 4. Persist configuration additively and compatibly

The Saga storage interface accepts an optional
`configuration: list[str] | None` argument. When an older caller omits it,
storage uses the scalar Saga status as a one-element configuration:
`[status.value]`.

The field is preserved by Memory, Redis, SQLite, and PostgreSQL storage, as well
as by each backend's export/import path used for storage transfer.

Schema-backed stores upgrade in place:

- SQLite adds a nullable `configuration` column when absent and backfills
  missing or empty values from each row's existing `status`.
- PostgreSQL adds a JSONB `configuration` column when absent, backfills old
  rows with `jsonb_build_array(status)`, and establishes the default and
  non-null constraint.

The upgrade statements are idempotent. Existing Saga identifiers, statuses,
context, metadata, and step records are preserved.

### 5. Preserve historical snapshots

Snapshots include the serializable configuration. Deserializing a historical
snapshot without that field falls back to `[status]`. This keeps older snapshot
payloads readable without pretending they contain hierarchical state.

### 6. Keep runtime state out of SagaContext

`SagaContext` remains a domain data and metadata container. It is not attached
as the StateChart model because it does not own a dedicated state field.
Runtime state is exposed through the state-machine and Saga status APIs rather
than being written implicitly into domain context.

## Consequences

### Positive

- Sagaz can inspect and persist active StateChart configuration without
  changing the existing flat Saga execution contract.
- Invalid transitions, failed guards, compensation ownership, and callback
  exception propagation remain explicit.
- Existing SQLite and PostgreSQL databases can be upgraded in place.
- Redis and Memory records, storage transfers, and historical snapshots have
  backward-compatible configuration fallbacks.
- The migration establishes a stable Phase 1 baseline for a separately reviewed
  hierarchical execution model.

### Negative

- The SCXML capabilities of StateChart are intentionally constrained in Phase 1.
- The compatibility flags must remain covered by behavioral regression tests;
  relying on upstream defaults would be unsafe.
- Configuration is additive persisted data, so every storage export/import and
  serialization path must continue to preserve it.

## Alternatives Considered

1. **Keep the legacy StateMachine classes.** This avoids runtime migration but
   does not provide the explicit configuration abstraction needed for future
   hierarchical state support.
2. **Adopt all StateChart defaults immediately.** Rejected because it changes
   invalid-event handling, self-transition callbacks, configuration visibility,
   and callback exception handling in ways that conflict with the Saga executor.
3. **Persist configuration only in snapshots.** Rejected because status
   inspection, durable Saga state, and cross-backend storage transfer also need
   the active configuration.
4. **Attach SagaContext as the StateChart model.** Rejected because
   SagaContext is not a state-bearing model and should not acquire runtime state
   implicitly.

## Phase 2 Boundary

Compound and parallel regions, step-level StateChart topology, `invoke`,
`DoneData`, `HistoryState`, restart/re-entry semantics, and migration of nested
configurations are not part of this decision's Phase 1 implementation. They
remain deferred to [issue #190](https://github.com/brunolnetto/sagaz/issues/190)
and require a separate design and compatibility review.

## References

- [Issue #188 — Phase 1 migration](https://github.com/brunolnetto/sagaz/issues/188)
- [PR #363 — StateChart Phase 1 implementation](https://github.com/brunolnetto/sagaz/pull/363)
- [PR #365 — python-statemachine security upgrade](https://github.com/brunolnetto/sagaz/pull/365)
- [Issue #190 — StateChart Phase 2](https://github.com/brunolnetto/sagaz/issues/190)
- [python-statemachine: Behaviour](https://python-statemachine.readthedocs.io/en/latest/behaviour.html)
- [python-statemachine: Upgrading from 2.x to 3.0](https://python-statemachine.readthedocs.io/en/stable/releases/upgrade_2x_to_3.html)
