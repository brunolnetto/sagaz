# Feature × Saga Mode Matrix

Which capability each saga mode has: orchestrated (a coordinator runs the steps) or
choreographed (participants react to events). Each cell is backed by a test
(`scripts/check_feature_matrix.py` fails if a cited test disappears). Audited on
2026-11-21 against `develop` (v2.4.0); gaps link to their issue.

## Modes

| Mode | What | Definition styles |
|---|---|---|
| **Orchestrated** | `sagaz.Saga`: a coordinator runs the steps and compensates them | declarative (`@action`/`@compensate`) and imperative (`add_step()`): same engine, same behavior |
| **Choreographed** | `sagaz.choreography`: participants react to events, no coordinator | declarative only (`@on_event`); imperative in [#560] |

Legend: ✅ supported · ⚠️ partial · ❌ missing · — does not apply to the mode.

## Execution and reliability

| Feature | Orchestrated | Choreographed |
|---|---|---|
| Step / handler definition | ✅ `tests/unit/core/test_decorators.py::TestSaga::test_collect_compensations` | ✅ `tests/unit/test_choreography.py::TestChoreographyEngine::test_duplicate_event_type_logs_warning` |
| Dependencies and parallel steps | ✅ steps without `depends_on` run in parallel `tests/unit/core/test_decorators.py::TestSaga::test_run_parallel_execution` | — the event topology is the graph |
| Parallel failure strategy | ⚠️ waits for every step of the level; `failure_strategy` unused ([#567]) | — |
| Step retries | ✅ `tests/unit/core/test_declarative_retries.py::test_a_step_is_attempted_max_retries_plus_one_times` | ❌ a handler runs once ([#561]) |
| Step timeouts | ✅ `tests/unit/core/test_declarative_retries.py::test_a_timed_out_attempt_is_retried` | ❌ ([#561]) |
| Compensation order | ✅ reverse dependency levels `tests/unit/core/test_decorators.py::TestSagaAdvanced::test_compensation_order_respected` | — each participant undoes its own actions, newest first `tests/unit/test_choreography_compensation.py::TestCompensation::test_compensation_runs_newest_first` |
| Compensation retries | ✅ `tests/unit/core/test_orchestrated_bug_fixes.py::TestCompensationRetries::test_a_flaky_compensation_is_retried` | ❌ ([#561]) |
| Pivot / taint | ✅ `tests/unit/core/test_pivot.py::TestPivotSagaIntegration::test_pivot_step_taints_ancestors` | ❌ ([#571]) |
| Forward recovery (`@forward_recovery`) | ❌ collected, never run ([#570]) | ❌ ([#570]) |
| Failure contract | ✅ raises `SagaFailedError` `tests/unit/core/test_failure_contract.py::TestSagaFailedError::test_a_rolled_back_saga` | ⚠️ outcome only through the tracker `tests/unit/test_choreography_compensation.py::TestCompensation::test_a_failing_participant_triggers_compensation_of_the_others` |
| State persistence | ✅ start, each level, outcome `tests/unit/core/test_saga_durability.py::TestProgressAndFailures::test_progress_is_saved_after_each_level` | ✅ participant state `tests/unit/test_choreography_state.py::TestAcrossProcesses::test_a_restarted_participant_compensates_earlier_actions` |
| A saga id runs once | ✅ `tests/unit/core/test_saga_durability.py::TestSagaIdRunsOnce::test_a_second_run_is_refused_before_any_step` | ❌ ([#562]) |
| Idempotency per step / delivery | ❌ ([#569]) | ✅ per `event_id` `tests/unit/test_choreography_compensation.py::TestIdempotency::test_redelivered_events_are_handled_once` |
| Whole-transaction deadline | ❌ ([#568]) | ✅ `tests/unit/test_choreography_deadlines.py::TestExpiry::test_an_expired_deadline_compensates_once` |
| Definition checks | ✅ `tests/unit/core/test_failure_contract.py::TestDefinitionErrors::test_a_cycle_shows_its_path` | ⚠️ duplicate handler only warns ([#560]) |
| Dry run / `sagaz validate` | ✅ `tests/unit/cli/test_dry_run.py::TestValidationMode::test_validate_detects_cycles` | ❌ |
| Compensation resume | ✅ `tests/unit/core/test_statechart_phase3.py::TestResume::test_a_compensation_resumes_from_its_last_checkpoint` | ✅ `tests/unit/test_choreography_state.py::TestAcrossProcesses::test_a_restarted_participant_compensates_earlier_actions` |
| StateChart | ✅ step chart with pivot/taint states `tests/unit/core/test_statechart_phase3.py::TestDeclarative::test_a_pivot_taints_its_ancestors` | — a status projection, not a chart |
| Snapshots, replay, time travel | ❌ ([#544]) | ❌ |
| Versioning | ✅ `tests/unit/versioning/test_schema_and_persistence.py::TestSagaVersionedMixin::test_run_options_reach_saga_run` | ❌ |
| Sync (`def`) steps / handlers | ✅ `tests/unit/core/test_failure_contract.py::TestRunInputs::test_sync_steps_and_compensations_work` | ✅ `tests/unit/test_choreography_compensation.py::TestCompensation::test_sync_handlers_and_compensations_work` |
| Step hooks (`on_enter`, …) | ✅ `tests/unit/core/test_orchestrated_bug_fixes.py::TestOnExit::test_on_exit_runs_after_success_and_failure` | — a handler is the hook |

## Integration and operations

| Feature | Orchestrated | Choreographed |
|---|---|---|
| Event sourcing | ✅ `tests/unit/core/test_event_sourcing.py::TestEventSourcedSaga::test_completed_run` | — its history is the tracker or the log |
| Unified saga log | ✅ `tests/unit/core/test_unified_orchestration.py::TestDeclarative::test_completed` | ✅ `tests/unit/test_choreography_unified.py::TestFlows::test_a_completed_order` |
| Log export (Fluss, Iceberg, CDC) | ✅ `tests/unit/test_fluss_export.py::TestExport::test_every_event_once` | ✅ `tests/unit/analytics/test_unified_analytics.py::TestUnifiedSource::test_one_summary_for_both_coordination_styles` |
| Transactional outbox | ⚠️ listener, not atomic with the state `tests/unit/core/test_saga_durability.py::TestOutboxStorageIsInitialized::test_the_listener_initializes_its_storage_once` | ✅ atomic on the log `tests/unit/test_choreography_unified.py::TestAtomicity::test_a_failed_write_records_neither_state_nor_event` |
| Schema registry | ✅ outbox brokers `tests/unit/test_schema_registry.py::TestOutbox::test_a_broker_publishes_registry_encoded_envelopes` | ⚠️ Kafka bus only ([#566]) |
| Tenancy: scope | ✅ `tests/unit/core/tenant/test_tenant_execution.py::TestSagaRunAsTenant::test_steps_run_in_the_tenant_scope_and_context_names_it` | ⚠️ trusts `Event.tenant_id` ([#564]) |
| Tenancy: quotas, registry | ✅ `tests/unit/core/tenant/test_tenant_execution.py::TestQuotasDuringExecution::test_concurrent_sagas_beyond_the_quota_are_refused` | ❌ ([#564]) |
| Multi-region steps | ✅ `tests/unit/core/test_regions.py::TestSagas::test_a_step_runs_in_its_region` | — a participant runs where it is deployed |
| Listeners (logging, metrics, custom) | ✅ `tests/unit/test_small_dx_fixes.py::test_extra_listeners_join_the_configured_ones` | ❌ ([#563]) |
| Prometheus metrics | ✅ `tests/unit/test_small_dx_fixes.py::test_two_prometheus_metrics_in_their_own_registries` | ✅ built in `tests/unit/test_choreography_compensation.py::TestCompensation::test_a_failing_participant_triggers_compensation_of_the_others` |
| OpenTelemetry tracing | ✅ `tests/unit/core/test_orchestrated_bug_fixes.py::TestTracingStatus::test_failed_compensation_is_traced` | ❌ ([#563]) |
| Analytics pipeline | ✅ `tests/unit/analytics/test_storage_pipeline.py` | ✅ `tests/unit/analytics/test_choreography_analytics.py::TestPipeline::test_summary_per_flow` |
| Mermaid diagram | ✅ `tests/unit/core/test_mermaid.py` | ❌ ([#565]) |
| Gradio monitor | ✅ `tests/unit/visualization/test_gradio_monitor.py` | ✅ causation graph `tests/unit/visualization/test_gradio_monitor.py` |
| `sagaz saga show` | ✅ `tests/unit/test_small_dx_fixes.py::test_saga_show` | ⚠️ tracker records only |
| `sagaz event-log` | ✅ `tests/unit/cli/test_cli_event_log.py::test_timeline` | ✅ `tests/unit/test_choreography_unified.py::test_event_log_reads_a_choreographed_transaction`; also `sagaz choreography status` |
| Triggers and web framework helpers | ✅ `tests/unit/core/triggers/test_triggers.py` | — `@on_event` and `begin()` are its triggers |
| Storage for its state | memory, SQLite, PostgreSQL, Redis `tests/unit/core/test_saga_durability.py` | memory, SQLite, PostgreSQL, unified log `tests/unit/test_choreography_state.py::TestFactory::test_urls` |

## Classic engine (until [#544])

Orchestration has one more implementation, `sagaz.core.saga.Saga` (`await add_step()`,
`execute() -> SagaResult`). It came before `sagaz.Saga` and stays because snapshot replay,
`SagaOrchestrator` and the phase 2 compensation resume run on it; [#544] moves them to
`sagaz.Saga` and removes this section. Where it differs from `sagaz.Saga`:

**Only in the classic engine** (each is a gap of `sagaz.Saga`):

- **Parallel failure strategy**: `tests/unit/core/test_core.py::TestParallelFailureStrategies::test_fail_fast_cancels_other_tasks`
- **Snapshots, replay, time travel**: library `tests/unit/core/test_replay.py::TestSagaReplay::test_replay_from_checkpoint_success`, CLI `tests/unit/cli/test_replay_real_storage.py::test_replay_runs_the_saga_again_from_a_checkpoint`

**Missing or partial in the classic engine** (all gone once [#544] lands):

- **State persistence**: ❌ writes no `SagaStorage` ([#544])
- **A saga id runs once**: ❌ ([#544])
- **Definition checks**: ⚠️ at `execute()`, as a failed result `tests/unit/core/test_core.py::TestSagaEdgeCases::test_missing_dependencies`
- **Versioning**: ❌
- **Step hooks (`on_enter`, …)**: ❌
- **Event sourcing**: ⚠️ constructor only, ignores `SagaConfig` `tests/unit/core/test_classic_saga_event_sourcing.py::TestSequential::test_completed`
- **Unified saga log**: ⚠️ constructor only `tests/unit/core/test_unified_orchestration.py::TestClassic::test_sequential_with_retries_and_participant`
- **Transactional outbox**: ❌
- **Schema registry**: ❌
- **Tenancy: scope**: ⚠️ through `SagaOrchestrator` `tests/unit/core/tenant/test_tenant_execution.py::TestOrchestrator::test_sagas_run_in_the_orchestrator_tenant`
- **Tenancy: quotas, registry**: ⚠️ through `SagaOrchestrator`
- **Multi-region steps**: ❌ ([#544])
- **Listeners (logging, metrics, custom)**: ❌ ([#544])
- **Prometheus metrics**: ⚠️ event-store counters only
- **OpenTelemetry tracing**: ⚠️ manual decorators
- **Analytics pipeline**: ⚠️ from the log only
- **Gradio monitor**: ⚠️ from the log
- **`sagaz saga show`**: ❌ nothing stored ([#544])
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
| Metric prefixes | `saga_*` | `sagaz_event_store_*` |

## Intrinsic to a mode, or a gap

Intrinsic (each mode keeps its own):

- **Choreography** dedups deliveries by `event_id` and watches a whole-transaction
  deadline, because nothing coordinates the transaction. It has no global compensation
  order: each participant undoes its own actions.
- **Orchestration** routes steps to regions and has step hooks: a participant already
  runs where it is deployed, and its handler is the hook.

Gaps, with their issue: see the ❌/⚠️ cells. The v2.6.0 milestone ("Mode Parity") holds
the parity work. The bugs the audit found (#549–#559) were fixed in v2.4.0.

## Inconsistencies across modes

| Topic | Orchestrated | Choreographed | Issue |
|---|---|---|---|
| Step timeout default | `SagaConfig.default_timeout` (60 s) | none | [#544], [#561] |
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
