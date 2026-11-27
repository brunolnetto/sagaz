# Feature × Saga Mode Matrix

Which capability each saga mode has: orchestrated (a coordinator runs the steps) or
choreographed (participants react to events). Each cell is backed by a test
(`scripts/check_feature_matrix.py` fails if a cited test disappears). Gaps link to their
issue.

> **Audited**: 2026-11-27 | **Version**: v2.6.0 | **Revision**: `6b16e4c495e77ed0fedd0477bc4d6c0511ff98e5`

The audit is a person's review of each cell against that revision of `develop`: the
claim, the code and the cited test. A script can check that the cited tests exist and
that this header names the released version; it cannot check that a claim is true. See
[Keeping this current](#keeping-this-current).

## Modes

| Mode | What | Definition styles |
|---|---|---|
| **Orchestrated** | `sagaz.Saga`: a coordinator runs the steps and compensates them | declarative (`@action`/`@compensate`) and imperative (`add_step()`): same engine, same behavior |
| **Choreographed** | `sagaz.choreography`: participants react to events, no coordinator | declarative (`@on_event`/`@compensate`) and imperative (`on()`): same engine, same behavior |

Legend: ✅ supported · ⚠️ partial · ❌ missing · — does not apply to the mode.

## Execution and reliability

| Feature | Orchestrated | Choreographed |
|---|---|---|
| Step / handler definition | ✅ `tests/unit/core/test_decorators.py::TestSaga::test_collect_compensations` | ✅ `tests/unit/test_choreography.py::TestChoreographyEngine::test_duplicate_event_type_is_a_definition_error` |
| Dependencies and parallel steps | ✅ steps without `depends_on` run in parallel `tests/unit/core/test_decorators.py::TestSaga::test_run_parallel_execution` | — the event topology is the graph |
| Parallel failure strategy | ✅ `WAIT_ALL`, `FAIL_FAST`, `FAIL_FAST_WITH_GRACE` `tests/unit/core/test_parallel_failure_strategies.py::TestStrategies::test_fail_fast_cancels_the_steps_still_running` | — |
| Step retries | ✅ `tests/unit/core/test_declarative_retries.py::test_a_step_is_attempted_max_retries_plus_one_times` | ✅ `tests/unit/test_choreography_retries.py::test_a_failing_handler_is_retried_three_times_by_default` |
| Step timeouts | ✅ `tests/unit/core/test_declarative_retries.py::test_a_timed_out_attempt_is_retried` | ✅ `tests/unit/test_choreography_retries.py::test_each_attempt_has_its_timeout` |
| Compensation order | ✅ reverse dependency levels `tests/unit/core/test_decorators.py::TestSagaAdvanced::test_compensation_order_respected` | — each participant undoes its own actions, newest first `tests/unit/test_choreography_compensation.py::TestCompensation::test_compensation_runs_newest_first` |
| Compensation retries | ✅ `tests/unit/core/test_orchestrated_bug_fixes.py::TestCompensationRetries::test_a_flaky_compensation_is_retried` | ✅ `tests/unit/test_choreography_retries.py::test_a_flaky_compensation_is_retried` |
| Pivot / taint | ✅ `@action(pivot=True)` `tests/unit/core/test_pivot.py::TestPivotSagaIntegration::test_pivot_step_taints_ancestors`, `add_step(pivot=True)` `tests/unit/core/test_imperative_pivots.py::TestAddStepPivot::test_a_failure_after_an_imperative_pivot_is_partially_committed`; pivots in parallel branches warn `tests/unit/core/test_imperative_pivots.py::TestParallelPivots::test_pivots_in_parallel_branches_warn_once_naming_both` | ✅ `tests/unit/test_choreography_pivot.py::TestAFailureAfterThePivot::test_what_led_to_the_pivot_is_kept_and_what_followed_is_undone` |
| Forward recovery (`@forward_recovery`) | ✅ `tests/unit/core/test_forward_recovery.py::TestRetry::test_retry_runs_the_step_again_until_it_succeeds`, `add_step(forward_recovery=)` `tests/unit/core/test_imperative_pivots.py::TestAddStepPivot::test_a_plain_function_recovers_forward` | ❌ ([#665]) |
| Failure contract | ✅ raises `SagaFailedError` `tests/unit/core/test_failure_contract.py::TestSagaFailedError::test_a_rolled_back_saga` | ⚠️ outcome only through the tracker `tests/unit/test_choreography_compensation.py::TestCompensation::test_a_failing_participant_triggers_compensation_of_the_others` |
| State persistence | ✅ start, each level, outcome `tests/unit/core/test_saga_durability.py::TestProgressAndFailures::test_progress_is_saved_after_each_level` | ✅ participant state `tests/unit/test_choreography_state.py::TestAcrossProcesses::test_a_restarted_participant_compensates_earlier_actions` |
| A saga id runs once | ✅ `tests/unit/core/test_saga_durability.py::TestSagaIdRunsOnce::test_a_second_run_is_refused_before_any_step` | ✅ a given `correlation_id` `tests/unit/test_choreography_runs_once.py::test_a_second_begin_with_the_same_id_is_refused_before_publishing` |
| Idempotency per step / delivery | ✅ `idempotency_key=` per step, across sagas `tests/unit/core/test_step_idempotency_keys.py::TestRunsOnce::test_a_second_saga_with_the_key_reuses_the_stored_result` | ✅ per `event_id` `tests/unit/test_choreography_compensation.py::TestIdempotency::test_redelivered_events_are_handled_once` |
| Whole-transaction deadline | ✅ `run(deadline=)` `tests/unit/core/test_saga_deadline.py::TestExpiry::test_past_the_deadline_the_saga_is_cancelled_compensated_and_fails` | ✅ `tests/unit/test_choreography_deadlines.py::TestExpiry::test_an_expired_deadline_compensates_once` |
| Definition checks | ⚠️ cycles, unknown dependencies, duplicate steps; an inventory lists the invalid values still accepted ([#660]) `tests/unit/core/test_failure_contract.py::TestDefinitionErrors::test_a_cycle_shows_its_path`, `tests/unit/permissiveness/test_inventory.py` | ⚠️ duplicate handlers and names, mixed styles; the same inventory ([#660]) `tests/unit/test_choreography_imperative.py::test_two_handlers_for_one_event_type_are_a_definition_error` |
| Dry run / `sagaz validate` | ✅ `tests/unit/cli/test_dry_run.py::TestValidationMode::test_validate_detects_cycles` | ❌ |
| Compensation resume | ✅ `tests/unit/core/test_statechart_phase3.py::TestResume::test_a_compensation_resumes_from_its_last_checkpoint` | ✅ `tests/unit/test_choreography_state.py::TestAcrossProcesses::test_a_restarted_participant_compensates_earlier_actions` |
| StateChart | ✅ step chart with pivot/taint states `tests/unit/core/test_statechart_phase3.py::TestDeclarative::test_a_pivot_taints_its_ancestors` | — a status projection, not a chart |
| Snapshots, replay, time travel | ✅ `tests/unit/core/test_saga_snapshot_replay.py::TestRunFromSnapshot::test_completed_steps_are_adopted_and_the_rest_run` | ❌ |
| Versioning | ✅ `tests/unit/versioning/test_schema_and_persistence.py::TestSagaVersionedMixin::test_run_options_reach_saga_run` | ❌ |
| Sync (`def`) steps / handlers | ✅ `tests/unit/core/test_failure_contract.py::TestRunInputs::test_sync_steps_and_compensations_work` | ✅ `tests/unit/test_choreography_compensation.py::TestCompensation::test_sync_handlers_and_compensations_work` |
| Step hooks (`on_enter`, …) | ✅ `tests/unit/core/test_orchestrated_bug_fixes.py::TestOnExit::test_on_exit_runs_after_success_and_failure` | — a handler is the hook |

## Integration and operations

| Feature | Orchestrated | Choreographed |
|---|---|---|
| Event sourcing | ⚠️ a saga that stops after a pivot is recorded as rolled back or failed ([#673]) `tests/unit/core/test_event_sourcing.py::TestEventSourcedSaga::test_completed_run` | — its history is the tracker or the log |
| Unified saga log | ✅ `tests/unit/core/test_unified_orchestration.py::TestDeclarative::test_completed` | ✅ `tests/unit/test_choreography_unified.py::TestFlows::test_a_completed_order` |
| Log export (Fluss, Iceberg, CDC) | ✅ `tests/unit/test_fluss_export.py::TestExport::test_every_event_once` | ✅ `tests/unit/analytics/test_unified_analytics.py::TestUnifiedSource::test_one_summary_for_both_coordination_styles` |
| Transactional outbox | ⚠️ listener, not atomic with the state `tests/unit/core/test_saga_durability.py::TestOutboxStorageIsInitialized::test_the_listener_initializes_its_storage_once` | ✅ atomic on the log `tests/unit/test_choreography_unified.py::TestAtomicity::test_a_failed_write_records_neither_state_nor_event` |
| Schema registry | ✅ outbox brokers `tests/unit/test_schema_registry.py::TestOutbox::test_a_broker_publishes_registry_encoded_envelopes` | ✅ Kafka, RabbitMQ and Redis Streams buses `tests/unit/test_bus_serializers.py::TestRedisStreams::test_with_a_serializer_one_field_holds_the_envelope` |
| Tenancy: scope | ✅ `tests/unit/core/tenant/test_tenant_execution.py::TestSagaRunAsTenant::test_steps_run_in_the_tenant_scope_and_context_names_it` | ✅ checked against the registry `tests/unit/test_choreography_tenancy.py::TestDeliveries::test_an_unknown_tenant_is_refused_and_compensated` |
| Tenancy: quotas, registry | ✅ `tests/unit/core/tenant/test_tenant_execution.py::TestQuotasDuringExecution::test_concurrent_sagas_beyond_the_quota_are_refused` | ✅ a delivery waits for a slot `tests/unit/test_choreography_tenancy.py::TestDeliveries::test_a_delivery_over_the_quota_waits_for_a_slot` |
| Multi-region steps | ✅ `tests/unit/core/test_regions.py::TestSagas::test_a_step_runs_in_its_region` | — a participant runs where it is deployed |
| Listeners (logging, metrics, custom) | ✅ `tests/unit/test_small_dx_fixes.py::test_extra_listeners_join_the_configured_ones` | ✅ steps per participant, sagas once per transaction (tracker) `tests/unit/test_choreography_observability.py::TestTransactionListeners::test_a_rolled_back_transaction_fails_once_with_the_reported_reason` |
| Prometheus metrics | ✅ `tests/unit/test_small_dx_fixes.py::test_two_prometheus_metrics_in_their_own_registries` | ✅ built in `tests/unit/test_choreography_compensation.py::TestCompensation::test_a_failing_participant_triggers_compensation_of_the_others` |
| OpenTelemetry tracing | ✅ `tests/unit/core/test_orchestrated_bug_fixes.py::TestTracingStatus::test_failed_compensation_is_traced` | ✅ one trace per transaction `tests/unit/test_choreography_observability.py::TestTracing::test_a_transaction_is_one_trace` |
| Analytics pipeline | ⚠️ the reports do not count `partially_committed` nor `forward_recovery` ([#673]) `tests/unit/analytics/test_storage_pipeline.py` | ⚠️ the same ([#673]) `tests/unit/analytics/test_choreography_analytics.py::TestPipeline::test_summary_per_flow` |
| Mermaid diagram | ✅ `tests/unit/core/test_mermaid.py` | ✅ from declared `emits=` `tests/unit/test_choreography_diagram.py::TestTheGraph::test_events_flow_through_the_participants_that_handle_and_emit_them` |
| Gradio monitor | ✅ `tests/unit/visualization/test_gradio_monitor.py` | ✅ causation graph `tests/unit/visualization/test_gradio_monitor.py` |
| `sagaz saga show` | ✅ `tests/unit/test_small_dx_fixes.py::test_saga_show` | ⚠️ tracker records only |
| `sagaz event-log` | ✅ `tests/unit/cli/test_cli_event_log.py::test_timeline` | ✅ `tests/unit/test_choreography_unified.py::test_event_log_reads_a_choreographed_transaction`; also `sagaz choreography status` |
| Triggers and web framework helpers | ✅ `tests/unit/core/triggers/test_triggers.py` | — `@on_event` and `begin()` are its triggers |
| Storage for its state | memory, SQLite, PostgreSQL, Redis `tests/unit/core/test_saga_durability.py` | memory, SQLite, PostgreSQL, unified log `tests/unit/test_choreography_state.py::TestFactory::test_urls` |

## Classic engine (deprecated, removed in 3.0)

Orchestration has one more implementation, `sagaz.core.saga.Saga` (`await add_step()`,
`execute() -> SagaResult`). It came before `sagaz.Saga`. Nothing runs only on it any more:
`sagaz.Saga` has what it had, so creating one emits a `DeprecationWarning` since 2.6.0
(`tests/unit/core/test_classic_saga_deprecation.py::test_creating_a_classic_saga_warns_and_names_the_replacement`, [#544]),
and 3.0 removes it with this section. [Migrating from the classic Saga](../guides/migrating-from-the-classic-saga.md)
maps one to the other.

- **`SagaOrchestrator`** runs both kinds: `tests/unit/test_orchestrator_runs_sagaz_saga.py::TestBothKinds::test_statistics_and_counts_cover_classic_and_sagaz_sagas`
- **Compensation resume:** `sagaz.Saga` resumes and lists what is pending: `tests/unit/core/test_statechart_phase3.py::TestResume::test_pending_compensations_are_what_a_resume_would_undo`
- **Snapshots and replay:** `SagaReplay` runs both kinds: `tests/unit/core/test_saga_snapshot_replay.py::TestSagaReplay::test_from_checkpoint_runs_a_sagaz_saga` (classic: `tests/unit/core/test_replay.py::TestSagaReplay::test_replay_from_checkpoint_success`, CLI `tests/unit/cli/test_replay_real_storage.py::test_replay_runs_the_saga_again_from_a_checkpoint`)

**Missing or partial in the classic engine.** These stay as they are: the class is
deprecated, and `sagaz.Saga` has each of them.

- **State persistence**: ❌ writes no `SagaStorage`
- **A saga id runs once**: ❌
- **Definition checks**: ⚠️ at `execute()`, as a failed result `tests/unit/core/test_core.py::TestSagaEdgeCases::test_missing_dependencies`
- **Versioning**: ❌
- **Step hooks (`on_enter`, …)**: ❌
- **Event sourcing**: ⚠️ constructor only, ignores `SagaConfig` `tests/unit/core/test_classic_saga_event_sourcing.py::TestSequential::test_completed`
- **Unified saga log**: ⚠️ constructor only `tests/unit/core/test_unified_orchestration.py::TestClassic::test_sequential_with_retries_and_participant`
- **Transactional outbox**: ❌
- **Schema registry**: ❌
- **Tenancy: scope**: ⚠️ through `SagaOrchestrator` `tests/unit/core/tenant/test_tenant_execution.py::TestOrchestrator::test_sagas_run_in_the_orchestrator_tenant`
- **Tenancy: quotas, registry**: ⚠️ through `SagaOrchestrator`
- **Multi-region steps**: ❌
- **Listeners (logging, metrics, custom)**: ❌
- **Prometheus metrics**: ⚠️ event-store counters only
- **OpenTelemetry tracing**: ⚠️ manual decorators
- **Analytics pipeline**: ⚠️ from the log only
- **Gradio monitor**: ⚠️ from the log
- **`sagaz saga show`**: ❌ nothing stored
- **Triggers and web framework helpers**: ❌

**Different defaults and signatures:**

| Topic | `sagaz.Saga` | Classic engine |
|---|---|---|
| Storage for its state | memory, SQLite, PostgreSQL, Redis `tests/unit/core/test_saga_durability.py` | snapshots: memory, filesystem, Redis, PostgreSQL, S3 |
| Step timeout default | `SagaConfig.default_timeout` (60 s) | 30 s fixed |
| No dependencies declared | steps run in parallel | steps run in sequence |
| Compensation signature | `undo(ctx)` | `undo(result, ctx)` |
| `compensation_errors` | dict | list |
| Tenant entry point | `run(tenant=)` | `SagaOrchestrator(tenant=)` |
| Metric prefixes | `sagaz_saga_*` | `sagaz_event_store_*` |

## Intrinsic to a mode, or a gap

Intrinsic (each mode keeps its own):

- **Choreography** dedups deliveries by `event_id` and watches a whole-transaction
  deadline, because nothing coordinates the transaction. It has no global compensation
  order: each participant undoes its own actions.
- **Orchestration** routes steps to regions and has step hooks: a participant already
  runs where it is deployed, and its handler is the hook.

Gaps, with their issue: see the ❌/⚠️ cells. v2.6.0 ("Mode Parity") closed the parity
gaps of the first audit; the one that remains, forward recovery for a choreography, is
planned for v2.7.0. The bugs the first audit found (#549–#559) were fixed in v2.4.0.

## Inconsistencies across modes

| Topic | Orchestrated | Choreographed | Issue |
|---|---|---|---|
| Step timeout default | `SagaConfig.default_timeout` (60 s) | `ChoreographyEngine(default_timeout=)` (60 s) | [#544] |
| Compensation signature | `undo(ctx)` | `undo(event)` | [#572] |
| `compensation_errors` | dict | — | [#572] |
| Status of an undone saga | `rolled_back` | `rolled_back` (`compensated` before 2.6.0, still read) | [#572] |
| Tenant entry point | `run(tenant=)` | `begin(tenant=)` (the old names work until 3.0) | [#572] |
| Metric prefixes | `sagaz_saga_*`, `sagaz_outbox_*`, `sagaz_inbox_*` (old names until 3.0) | `sagaz_choreography_*` | [#572] |

## Other axes

The mode is one axis; these also change what a feature guarantees:

- **Storage backend × store kind.** Redis has no event store, saga log or participant
  state. A saga id runs once across processes only with a shared storage (the default
  in-memory storage is per process).
- **Storage layout** (classic tables or unified log). Outbox atomicity, `saga show` and
  `event-log` behave differently.
- **Broker × role** (outbox broker, choreography bus, region transport). Serializers and
  redelivery differ by broker.
- **Delivery semantics** per publish path (at most once, at least once, atomic).
- **Crash recovery point.** What survives a crash mid-step, mid-level or mid-compensation,
  and what resumes it.

## Keeping this current

Cite a test for every ✅ and ⚠️ cell. `python scripts/check_feature_matrix.py` fails
when a cited test file, class or function no longer exists, and runs in CI.

**After a release, or a change of what a mode can do,** refresh the audit:

1. Read each row you touched (after a release, every row) against the code: is the cell
   still true, and does the cited test still show it? Run the cited tests.
2. Update the header: the date, the released version (`project.version` in
   `pyproject.toml`) and the revision you read, as `git rev-parse HEAD` gives it.
3. Update the [roadmap](../ROADMAP.md) and the [release plan](../planning/release-plan.md)
   in the same pull request: the latest release, what is in development, what comes next.
4. Run `python scripts/check_release_docs.py`. It checks that the three documents name
   the same released version as `pyproject.toml` and that the header's revision is a full
   commit id. It does not check that a claim is true: that is step 1.

[#544]: https://github.com/brunolnetto/sagaz/issues/544
[#560]: https://github.com/brunolnetto/sagaz/issues/560
[#561]: https://github.com/brunolnetto/sagaz/issues/561
[#562]: https://github.com/brunolnetto/sagaz/issues/562
[#563]: https://github.com/brunolnetto/sagaz/issues/563
[#564]: https://github.com/brunolnetto/sagaz/issues/564
[#565]: https://github.com/brunolnetto/sagaz/issues/565
[#566]: https://github.com/brunolnetto/sagaz/issues/566
[#567]: https://github.com/brunolnetto/sagaz/issues/567
[#568]: https://github.com/brunolnetto/sagaz/issues/568
[#569]: https://github.com/brunolnetto/sagaz/issues/569
[#570]: https://github.com/brunolnetto/sagaz/issues/570
[#571]: https://github.com/brunolnetto/sagaz/issues/571
[#572]: https://github.com/brunolnetto/sagaz/issues/572
[#660]: https://github.com/brunolnetto/sagaz/issues/660
[#665]: https://github.com/brunolnetto/sagaz/issues/665
[#673]: https://github.com/brunolnetto/sagaz/issues/673
