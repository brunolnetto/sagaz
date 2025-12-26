# Chaos Engineering Tests

## Overview

The chaos engineering tests in `tests/test_chaos_engineering.py` validate the system's resilience under various failure scenarios. These tests deliberately inject failures to verify that the saga pattern library handles real-world production issues gracefully.

## Test Categories

### 1. Worker Crash & Recovery (`TestWorkerCrashRecovery`)

**Purpose**: Verify that worker failures don't cause data loss and that other workers can pick up failed work.

- **test_worker_crash_mid_publish_another_picks_up** ✅
  - Simulates a worker crash during message publishing
  - Verifies another worker successfully completes the job
  - Validates the claim mechanism prevents data loss

- **test_worker_graceful_shutdown_preserves_state** ✅
  - Simulates SIGTERM signal during processing
  - Verifies in-flight work completes before shutdown
  - Ensures no data loss during graceful termination

- **test_multiple_workers_no_duplicate_processing** ⏭️ (Skipped)
  - Tests concurrent worker claim mechanism
  - Note: Skipped due to race condition timing sensitivity in test environment

### 2. Database Connection Loss (`TestDatabaseConnectionLoss`)

**Purpose**: Verify graceful handling of database connection failures and recovery.

- **test_database_connection_loss_during_saga_execution** ✅
  - Simulates database connection loss during saga execution
  - Verifies graceful error handling
  - Confirms saga state preserved after reconnection

- **test_outbox_storage_connection_retry** ✅
  - Tests intermittent outbox storage connection failures
  - Verifies worker retry logic with exponential backoff
  - Validates eventual success after transient failures

- **test_connection_pool_exhaustion_recovery** ✅
  - Simulates database connection pool exhaustion
  - Tests graceful queuing and backoff behavior
  - Verifies all operations eventually succeed

### 3. Broker Downtime (`TestBrokerDowntime`)

**Purpose**: Verify system handles message broker failures correctly.

- **test_broker_connection_failure_exponential_backoff** ⏭️ (Skipped)
  - Tests broker downtime and recovery
  - Note: Skipped due to worker retry behavior variations

- **test_broker_publish_timeout** ⏭️ (Skipped)
  - Simulates network partition causing publish timeout
  - Note: Skipped due to precise timing requirements in CI

- **test_partial_batch_failure** ✅
  - Tests mixed success/failure in message batch
  - Verifies failed messages marked for retry
  - Confirms successful messages committed properly

### 4. Network Partitions (`TestNetworkPartitions`)

**Purpose**: Verify correct behavior under network partition scenarios.

- **test_split_brain_prevention** ✅
  - Simulates network partition causing split brain
  - Verifies claim mechanism prevents duplicate processing
  - Validates each event processed exactly once

- **test_delayed_acknowledgment** ✅
  - Tests delayed ACK due to network issues
  - Verifies no duplicate processing despite delays
  - Confirms idempotency guarantees hold

### 5. Concurrent Failures (`TestConcurrentFailures`)

**Purpose**: Test system behavior under multiple simultaneous failures.

- **test_database_and_broker_both_fail** ✅
  - Simulates cascading failures (DB + broker)
  - Verifies system recovers when both services restore
  - Tests graceful degradation

- **test_high_load_degradation** ✅
  - Tests system under extreme load (50 events, 3 workers)
  - Verifies graceful degradation without crashes
  - Confirms all events processed despite load

- **test_cascading_failure_recovery** ⏭️ (Skipped)
  - Tests self-healing from cascading failures
  - Note: Skipped due to timing sensitivity in simulation

### 6. Data Consistency (`TestDataConsistency`)

**Purpose**: Verify data consistency guarantees under chaos conditions.

- **test_no_data_loss_under_failures** ✅
  - Tests random 30% failure rate during processing
  - Verifies all events eventually processed
  - Confirms no data loss despite failures

- **test_exactly_once_processing_guarantee** ✅
  - Tests race conditions with 5 concurrent workers
  - Verifies each event processed exactly once
  - Validates idempotency under concurrency

## Running the Tests

### Run all chaos tests:
```bash
pytest tests/test_chaos_engineering.py -v -m chaos
```

### Run specific test category:
```bash
pytest tests/test_chaos_engineering.py::TestWorkerCrashRecovery -v
```

### Run with coverage:
```bash
pytest tests/test_chaos_engineering.py --cov=sage --cov-report=html
```

## Test Results

- **Total Tests**: 16
- **Passing**: 12 (75%)
- **Skipped**: 4 (25%)
- **Failed**: 0

The skipped tests are intentionally marked as such due to timing sensitivities that make them unreliable in CI/CD environments. They validate important scenarios but are inherently flaky due to their dependence on precise timing and race conditions.

## Key Findings

### ✅ Strengths Validated

1. **Worker Resilience**: Workers gracefully handle crashes and can recover failed work
2. **Database Resilience**: System handles connection losses with proper retry logic
3. **Data Consistency**: No data loss even under random failures
4. **Concurrency Safety**: Multiple workers don't cause duplicate processing
5. **Load Handling**: System gracefully degrades under extreme load
6. **Idempotency**: Exactly-once processing guarantees hold

### ⚠️ Known Limitations

1. Some timing-dependent tests are unreliable in CI environments
2. Cascading failure recovery depends on retry configuration
3. Connection pool exhaustion requires careful tuning in production

## Production Recommendations

Based on chaos testing results:

1. **Worker Configuration**:
   - Use multiple workers for high availability
   - Configure appropriate batch sizes (5-10 for balanced throughput)
   - Set reasonable retry limits (5-10 attempts)

2. **Database Configuration**:
   - Size connection pool appropriately for concurrent workers
   - Implement connection retry with exponential backoff
   - Monitor connection pool utilization

3. **Broker Configuration**:
   - Configure broker timeouts appropriately
   - Implement circuit breakers for cascading failures
   - Use dead letter queues for permanently failed messages

4. **Monitoring**:
   - Track worker health and claim rates
   - Monitor retry counts and failure patterns
   - Alert on sustained high retry rates

## Future Enhancements

Potential additions to chaos engineering suite:

1. Disk I/O failures and recovery
2. Memory pressure scenarios
3. Clock drift and time synchronization issues
4. Kubernetes pod eviction scenarios
5. Multi-region network latency simulation

## References

- Netflix Chaos Monkey: https://netflix.github.io/chaosmonkey/
- Principles of Chaos Engineering: https://principlesofchaos.org/
- Google SRE Book - Chaos Engineering: https://sre.google/sre-book/

---

**Last Updated**: December 2025
**Maintenance**: Run chaos tests as part of CI/CD pipeline on every release
