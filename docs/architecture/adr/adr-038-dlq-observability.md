# ADR-038: DLQ Observability — Error Classification, Replay Validation, and Pattern Detection

## Status

**Accepted** | Date: 2026-04-12 | Implemented: 2026-04-12 | Target: v1.3.0 | PR: #60

## Context

PR #60 introduced a Dead Letter Queue (DLQ) for the transactional outbox pattern, solving the
head-of-line blocking problem: failed events no longer block healthy events from being published.

However, as noted by @namrahov in issue #44, **DLQ shifts the problem rather than solving it
completely**. The next production challenges are:

1. Understanding root causes across many failed events
2. Avoiding blind replays that hit the same failure again
3. Detecting patterns like retry loops or sudden DLQ spikes

The DLQ infrastructure is reliable, but **operational visibility is what makes it reliable at
scale**.

## Decision

We will extend the DLQ implementation in three phases to address each challenge.

### Phase 1 — Error Classification and Enrichment (v1.3.0)

**Problem**: All failures are treated identically. A transient `ConnectionError` and a permanent
`ValidationError` both exhaust retries identically, wasting retries on non-retryable failures and
potentially sending retryable failures to DLQ prematurely.

**Solution**:

1. **Add `error_type` field** to `OutboxEvent` — the Python exception class name
   (`"ConnectionError"`, `"ValidationError"`, etc.).

2. **Add `error_classification` field** (`"TRANSIENT"` | `"PERMANENT"` | `"UNKNOWN"`) — populated
   by classifying the exception against known retryable and non-retryable error types.

3. **Add `error_fingerprint` field** — a short hex hash of a normalised error message (numbers and
   hostnames replaced by placeholders) so that many instances of the same error share one
   fingerprint. Operators can group DLQ events by fingerprint rather than reading free-text.

4. **Emit `error_type` label on Prometheus metrics** — `OUTBOX_DEAD_LETTER_EVENTS` gains an
   `error_type` dimension.

**Error classification rules** (extensible):

| Python exception class | Classification |
|------------------------|---------------|
| `ConnectionError`, `TimeoutError`, `OSError`, `asyncio.TimeoutError` | `TRANSIENT` |
| `ValueError`, `TypeError`, `KeyError`, `AssertionError`, `AttributeError` | `PERMANENT` |
| Anything else | `UNKNOWN` |

### Phase 2 — Replay Validation and Retry Loop Detection (v1.3.0)

**Problem**: Operators can replay DLQ events without understanding whether the root cause is fixed,
leading to repeat failures and retry loops going undetected.

**Solution**:

1. **Add `replay_count` field** — incremented each time the event is requeued via
   `requeue_dead_letter_event`.

2. **`replay_count` reset prevention** — `requeue_dead_letter_event` raises `ReplayLoopError` when
   `replay_count >= max_replays` (default: 3). Operators can override with `force=True`.

3. **Pre-replay validation** — `OutboxStorage.requeue_dead_letter_event` enforces the replay limit
   by default. A helper `DLQReplayValidator` (imported from `sagaz.core.outbox.dlq_validator`)
   provides `can_replay(event) -> (bool, str)` for programmatic checks before calling requeue.

4. **`OUTBOX_REPLAY_LOOP_DETECTED` counter** — incremented when `ReplayLoopError` is raised so
   AlertManager can fire on retry loops.

### Phase 3 — Pattern Detection (future, v1.4.0+)

Phase 3 adds a correlation engine that periodically scans DLQ events and:

- Groups by `error_fingerprint` to surface dominant failure modes
- Detects cascading failures when multiple sagas fail with the same `error_type` in a short window
- Emits `dlq_dominant_error_fingerprint` and `dlq_cascade_detected` gauge metrics

Phase 3 is out of scope for this ADR and will be covered by a separate ADR.

## Consequences

### Positive

- Operators can answer "what kind of error is this?" without reading free-text logs.
- Fingerprinting lets dashboards surface the top-N distinct failure modes.
- Replay loop protection prevents silent re-escalation of the same failure.
- All new fields are optional with `None` defaults — backward compatible with existing serialised
  events in all storage backends.

### Negative / Trade-offs

- `error_classification` is heuristic (based on exception class name). Domain-specific errors
  (e.g., a custom `PaymentGatewayError`) default to `UNKNOWN` until the classification map is
  extended.
- `error_fingerprint` normalises numbers and hostnames but is not semantic — two logically-different
  errors can share a fingerprint if their normalised text matches.
- The `ReplayLoopError` guard requires operators to use `force=True` for legitimate high-retry
  scenarios (e.g., a saga that was legitimately stuck for days).

## Alternatives Considered

### ML-based anomaly detection

Using a lightweight ML model to classify errors was considered but rejected for v1.3.0 because it
adds a heavyweight dependency, requires training data that does not yet exist, and the heuristic
rule-based approach covers the most common cases adequately.

### Separate DLQ service

Running DLQ management as a separate microservice was considered but rejected: the outbox pattern is
intentionally co-located with the saga executor to share the database transaction. Splitting it out
would reintroduce the distributed-commit problem.

## Implementation Notes

- `classify_error(exc)` lives in `sagaz/core/outbox/error_classifier.py`
- `create_error_fingerprint(message)` lives in the same module
- `DLQReplayValidator` lives in `sagaz/core/outbox/dlq_validator.py`
- `ReplayLoopError` is a subclass of `OutboxError` defined in `sagaz/core/outbox/types.py`
- All new `OutboxEvent` fields are included in `to_dict()` / `from_dict()` round-trips
- `InMemoryOutboxStorage.requeue_dead_letter_event` gains a `force: bool = False` parameter

## Dependencies

- ADR-016: Unified Storage Layer (Implemented) — storage interface extended here
- PR #60: DLQ infrastructure (this PR)
- PR #61: AlertManager rules (extends rules added in Phase 1/2)
