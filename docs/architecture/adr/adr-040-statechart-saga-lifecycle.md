# ADR-040: StateChart Adoption for Saga Lifecycle State

## Status

**Proposed** | Date: 2026-11-10 | Priority: High | Target: v1.7.0 (Phase 1)

## Context

Sagaz currently uses flat `StateMachine` classes for the Saga and individual step lifecycles. The project lockfile already resolves `python-statemachine` 3.0.0, but the declared dependency range still permits 2.x. The current implementation also exposes only a scalar state, which is insufficient for future compound/parallel state configurations and makes persisted snapshots less expressive.

The migration must not silently change Saga orchestration semantics. The Saga executor currently owns exception handling and compensation; it catches callback failures from the state machine and performs compensation outside it. A mechanical switch to the SCXML defaults would change how unmatched events and callback exceptions are handled.

## Decision

### Phase 1: compatibility-preserving StateChart adoption

1. Raise the minimum supported dependency to `python-statemachine>=3.0.0`.
2. Migrate `SagaStateMachine` and `SagaStepStateMachine` to `StateChart`.
3. Retain the legacy StateMachine behavior explicitly:
   - `allow_event_without_transition = False`
   - `enable_self_transition_entries = False`
   - `atomic_configuration_update = True`
   - `catch_errors_as_events = False`
4. Preserve the existing `current_state` API as a State-object accessor for the current flat topology. Expose `active_configuration` as the serializable list of active state IDs. Add `configuration` to Saga status output without removing `current_state`.
5. Persist optional `configuration: list[str]` alongside the scalar Saga status. Existing callers that omit it continue to store `[status.value]`.
6. Include configuration in snapshots and storage transfer exports/imports. Historical snapshots and records without configuration load with `[status]`.
7. Upgrade existing PostgreSQL and SQLite schemas additively and idempotently. Backfill legacy rows from their scalar status. Redis records are normalized on read; in-memory records default to the scalar status.
8. Keep the Saga executor as the owner of failure handling and compensation.

### Deliberately deferred

- Do not enable `catch_errors_as_events` or route runtime callback failures through `error.execution` in this phase. Doing so before the Saga executor is adapted can swallow an exception inside the StateChart and allow the caller to continue under a failed state.
- Do not attach `SagaContext` as the StateChart domain model. `SagaContext` is currently a data/metadata container and has no dedicated state field; execution state should not be written into domain context implicitly.
- Do not introduce `State.Compound`, `State.Parallel`, `invoke`, `DoneData`, or `HistoryState`. Those are Phase 2 and remain tracked separately in issue #190.

## Consequences

### Positive

- Sagaz uses the StateChart API and exposes serializable active configuration.
- Existing public state inspection and runtime transition behavior remain compatible for flat Saga/step state machines.
- Existing database files and PostgreSQL installations receive additive upgrades instead of requiring users to recreate storage.
- Snapshot and storage-transfer data preserve configuration when supplied.

### Negative

- Phase 1 intentionally does not adopt SCXML's default event/error semantics.
- The compatibility `current_state` accessor is only valid while the topology has one active state. Compound configurations must use `active_configuration`.
- Older callers and records only know the scalar status; their configuration is represented as a one-element list until upgraded callers provide richer state IDs.

## Alternatives Considered

1. **Switch to StateChart defaults immediately.** Rejected because unmatched events would be silently ignored and callback exceptions could be converted to internal events, changing the Saga executor's compensation path.
2. **Keep StateMachine and postpone StateChart.** Rejected because the project already resolves 3.x and needs a supported configuration API before introducing compound states.
3. **Persist only the scalar status.** Rejected because it would lose the configuration representation required for snapshots and future statechart work.

## References

- [python-statemachine 3.0 migration guide](https://python-statemachine.readthedocs.io/en/latest/upgrading.html)
- [python-statemachine behavior compatibility](https://python-statemachine.readthedocs.io/en/latest/behaviour.html)
- Issue #188 — Phase 1 StateChart migration
- Issue #190 — deferred compound/parallel Phase 2
