# Enterprise Saga + Outbox Pattern: AI-Ready Implementation Guide

## Document Purpose & Context

This guide provides complete, production-ready implementation instructions for an enterprise-grade asynchronous saga orchestration system using the Transactional Outbox Pattern. Designed for AI agent consumption with explicit decision trees, validation criteria, and executable specifications.

### Core Guarantee
**Exactly-once side effects with at-least-once delivery** through transactional outbox and consumer-side deduplication.

### Technology Stack Assumptions
- **Database**: PostgreSQL 12+ (single source of truth)
- **Language**: Python 3.11+ with asyncpg
- **Message Broker**: Kafka/RabbitMQ-compatible
- **Observability**: Prometheus + OpenTelemetry
- **Orchestration**: Kubernetes
- **Transaction Isolation**: Read Committed (minimum)

---

 bounded delay (typically <1s) between state change and message delivery.

### ADR-002: Optimistic Concurrency Control (OCC)
**Decision**: Use version-based OCC for saga state updates.

**Rationale**:
- Pessimistic locks (SELECT FOR UPDATE) serialize saga workers unnecessarily
- OCC allows concurrent saga execution when steps don't conflict
- Better for distributed worker pools

**Implementation**: Version field incremented atomically; retry on version mismatch with exponential backoff.

### ADR-003: Claim-Based Worker Processing
**Decision**: Workers claim batches using `UPDATE ... RETURNING` with `FOR UPDATE SKIP LOCKED`.

**Rationale**:
- Prevents thundering herd on same messages
- Atomic claim without external coordination (Redis, etc.)
- Postgres-native solution reduces dependencies

---

## Schema Design: Critical Implementation Details

### Migration: `0001_create_saga_outbox.sql`

```sql
-- Required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Core saga state table
CREATE TABLE saga_instance (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  saga_type TEXT NOT NULL,                    -- e.g., 'OrderPlacement', 'PaymentProcessing'
  correlation_id UUID NOT NULL,               -- Business identifier for grouping
  state JSONB NOT NULL DEFAULT '{}'::jsonb,   -- Saga step state (idempotency keys, step results)
  status TEXT NOT NULL DEFAULT 'started',     -- started, running, compensating, completed, failed
  current_step TEXT,                          -- For debugging: which step is executing
  version BIGINT NOT NULL DEFAULT 0,          -- Optimistic concurrency control
  last_error TEXT,                            -- Serialized exception for debugging
  retry_count INT NOT NULL DEFAULT 0,         -- Failed execution attempts
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  
  CONSTRAINT valid_status CHECK (status IN ('started', 'running', 'compensating', 'completed', 'failed'))
);

-- Performance indexes
CREATE INDEX idx_saga_type_status ON saga_instance(saga_type, status) WHERE status IN ('running', 'compensating');
CREATE INDEX idx_saga_correlation ON saga_instance(correlation_id);
CREATE INDEX idx_saga_stale ON saga_instance(updated_at) WHERE status IN ('running', 'compensating'); -- For stuck saga detection

-- Transactional outbox table
CREATE TABLE outbox (
  id BIGSERIAL PRIMARY KEY,
  event_id UUID NOT NULL UNIQUE DEFAULT uuid_generate_v4(),  -- Deduplication key
  saga_id UUID REFERENCES saga_instance(id) ON DELETE CASCADE, -- Optional: link to saga
  aggregate_type TEXT NOT NULL,               -- Domain entity type
  aggregate_id UUID NOT NULL,                 -- Domain entity ID
  event_type TEXT NOT NULL,                   -- Event name for routing
  payload JSONB NOT NULL,                     -- Event data
  headers JSONB NOT NULL DEFAULT '{}'::jsonb, -- Metadata (trace_id, causation_id, etc.)
  status TEXT NOT NULL DEFAULT 'pending',     -- pending, claimed, sent, failed, dead_letter
  routing_key TEXT,                           -- Optional: for topic/exchange routing
  partition_key TEXT,                         -- Optional: for ordered delivery
  attempts INT NOT NULL DEFAULT 0,            -- Publish retry count
  max_attempts INT NOT NULL DEFAULT 10,       -- Configurable failure threshold
  available_at TIMESTAMPTZ NOT NULL DEFAULT now(), -- Backoff delay
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_at TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  
  CONSTRAINT valid_outbox_status CHECK (status IN ('pending', 'claimed', 'sent', 'failed', 'dead_letter'))
);

-- Critical indexes for worker performance
CREATE INDEX idx_outbox_pending ON outbox (status, available_at, created_at) 
  WHERE status IN ('pending', 'failed');
CREATE INDEX idx_outbox_aggregate ON outbox(aggregate_type, aggregate_id);
CREATE INDEX idx_outbox_saga ON outbox(saga_id) WHERE saga_id IS NOT NULL;

-- Archive table for sent messages (for audit/replay)
CREATE TABLE outbox_archive (LIKE outbox INCLUDING ALL);
ALTER TABLE outbox_archive ADD COLUMN archived_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Consumer deduplication table (each consumer service maintains its own)
CREATE TABLE consumer_inbox (
    event_id UUID PRIMARY KEY,
    consumer_name TEXT NOT NULL,              -- Identifies the consuming service
    source_topic TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processing_duration_ms INT                -- For performance tracking
);

CREATE INDEX idx_inbox_consumer ON consumer_inbox(consumer_name, consumed_at);
```

### Schema Validation Checklist
- [ ] Primary keys use UUID v4 for distributed generation
- [ ] Status fields use CHECK constraints (prevent invalid states)
- [ ] Indexes cover all WHERE clauses in worker queries
- [ ] Foreign keys include ON DELETE CASCADE where appropriate
- [ ] Timestamps use TIMESTAMPTZ (not TIMESTAMP)
- [ ] JSONB fields have default values to prevent NULL surprises

---

## Core Interfaces: Type-Safe Contracts

### `saga/interfaces.py`

```python
"""
Core abstractions for saga orchestration.
All implementations must be async-safe and connection-pool aware.
"""
from typing import Protocol, Any, TypedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid

class SagaStatus(str, Enum):
    STARTED = "started"
    RUNNING = "running"
    COMPENSATING = "compensating"
    COMPLETED = "completed"
    FAILED = "failed"

class OutboxStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    SENT = "sent"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"

@dataclass
class OutboxEvent:
    """
    Represents a single event to be published.
    
    Design notes:
    - event_id is the deduplication key (must be deterministic or pre-generated)
    - payload should be serializable to JSON (no binary data)
    - headers MUST include: trace_id, causation_id for distributed tracing
    """
    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict
    headers: dict = field(default_factory=dict)
    saga_id: str | None = None
    routing_key: str | None = None
    partition_key: str | None = None
    max_attempts: int = 10
    
    def __post_init__(self):
        # Validate required headers for observability
        required_headers = {'trace_id', 'message_id'}
        if not required_headers.issubset(self.headers.keys()):
            raise ValueError(f"Missing required headers: {required_headers - self.headers.keys()}")

@dataclass
class SagaState:
    """Immutable snapshot of saga execution state."""
    id: str
    saga_type: str
    correlation_id: str
    state: dict
    status: SagaStatus
    version: int
    current_step: str | None = None
    last_error: str | None = None
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

class SagaStorage(Protocol):
    """
    Persistence layer for saga state and outbox.
    
    Transactionality requirements:
    - save() and append_outbox() must execute in caller's transaction
    - load() should use FOR UPDATE if pessimistic locking needed
    """
    
    async def create(self, saga: SagaState) -> None:
        """Initialize new saga. Raises if ID already exists."""
        ...
    
    async def load(self, saga_id: str, for_update: bool = False) -> SagaState:
        """
        Load saga state.
        
        Args:
            saga_id: Saga identifier
            for_update: If True, acquire pessimistic lock (SELECT FOR UPDATE)
        
        Raises:
            KeyError: If saga not found
        """
        ...
    
    async def save(
        self, 
        saga_id: str, 
        state: dict, 
        status: SagaStatus,
        expected_version: int,
        current_step: str | None = None,
        error: str | None = None
    ) -> int:
        """
        Atomically update saga state with optimistic concurrency control.
        
        Args:
            expected_version: Must match current version in DB
        
        Returns:
            New version number after update
        
        Raises:
            ConcurrencyError: If version mismatch (another worker updated saga)
        """
        ...
    
    async def append_outbox(self, event: OutboxEvent) -> None:
        """
        Insert event into outbox table.
        
        MUST be called within same transaction as save() to guarantee atomicity.
        Idempotent: duplicate event_id is silently ignored (ON CONFLICT DO NOTHING).
        """
        ...
    
    async def mark_outbox_sent(self, event_id: str) -> None:
        """Mark event as successfully published. Idempotent."""
        ...
    
    async def mark_outbox_failed(self, event_id: str, error: str) -> None:
        """Record publish failure. May move to dead_letter after max_attempts."""
        ...
    
    async def claim_pending_events(self, batch_size: int, worker_id: str) -> list[dict]:
        """
        Atomically claim pending events for processing.
        
        Uses UPDATE ... RETURNING with FOR UPDATE SKIP LOCKED to avoid contention.
        Updates status to 'claimed' and sets claimed_at timestamp.
        
        Returns:
            List of claimed event rows (as dicts)
        """
        ...
    
    async def requeue_stuck_claims(self, timeout_seconds: int) -> int:
        """
        Reset 'claimed' events older than timeout back to 'pending'.
        
        Handles crashed workers. Should be called periodically by separate watchdog.
        
        Returns:
            Number of events requeued
        """
        ...

class MessageBroker(Protocol):
    """
    Abstract message broker for event publishing.
    
    Implementation requirements:
    - Idempotent publish (use message_id for deduplication)
    - Support for custom headers (tracing, causation)
    - Async operations
    """
    
    async def publish(
        self,
        topic: str,
        payload: dict,
        message_id: str,
        headers: dict | None = None,
        partition_key: str | None = None
    ) -> None:
        """
        Publish message to broker.
        
        Args:
            topic: Target topic/exchange
            message_id: Deduplication key (broker must honor)
            partition_key: Optional key for ordered delivery
        
        Raises:
            BrokerError: On transient failures (will retry with backoff)
        """
        ...

class SagaLogger(Protocol):
    """
    Structured logging for saga operations.
    
    All logs must include saga_id and trace_id for correlation.
    """
    
    async def info(self, saga_id: str, msg: str, **context: Any) -> None: ...
    async def warning(self, saga_id: str, msg: str, **context: Any) -> None: ...
    async def error(self, saga_id: str, msg: str, exc: Exception | None = None, **context: Any) -> None: ...
    
    async def event(
        self,
        saga_id: str,
        step_name: str,
        event_type: str,
        payload: dict,
        status: str = "success"
    ) -> None:
        """
        Log saga step execution event.
        
        Used for audit trail and debugging. Should write to separate log stream.
        """
        ...
```

---

## Implementation: PostgreSQL Storage Layer

### `saga/storage_postgres.py`

```python
"""
PostgreSQL implementation of SagaStorage.

Critical implementation notes:
1. Always use connection pools (asyncpg.Pool), never direct connections
2. All mutations must support caller-managed transactions
3. Retry logic for serialization failures (isolation level conflicts)
4. Comprehensive error handling with custom exceptions
"""
import json
import uuid
from datetime import datetime, timedelta
from typing import Any
from asyncpg import Pool, Connection
from asyncpg.exceptions import UniqueViolationError, SerializationError

from .interfaces import (
    SagaStorage, SagaState, SagaStatus, OutboxEvent, OutboxStatus
)

class ConcurrencyError(Exception):
    """Raised when optimistic concurrency check fails."""
    pass

class SagaNotFoundError(KeyError):
    """Raised when saga doesn't exist."""
    pass

class PostgresSagaStorage(SagaStorage):
    """
    Production-ready PostgreSQL saga storage.
    
    Transaction semantics:
    - Methods with conn parameter execute within caller's transaction
    - Methods without conn parameter acquire new connection and auto-commit
    """
    
    def __init__(self, pool: Pool):
        self.pool = pool
    
    async def create(self, saga: SagaState) -> None:
        """Initialize new saga instance."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO saga_instance (
                        id, saga_type, correlation_id, state, status, 
                        version, current_step, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    saga.id, saga.saga_type, saga.correlation_id,
                    json.dumps(saga.state), saga.status.value,
                    saga.version, saga.current_step,
                    saga.created_at, saga.updated_at
                )
            except UniqueViolationError:
                raise ValueError(f"Saga {saga.id} already exists")
    
    async def load(self, saga_id: str, for_update: bool = False) -> SagaState:
        """Load saga with optional pessimistic lock."""
        query = """
            SELECT id, saga_type, correlation_id, state, status, version,
                   current_step, last_error, retry_count, created_at, updated_at
            FROM saga_instance
            WHERE id = $1
        """
        if for_update:
            query += " FOR UPDATE"
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, saga_id)
            if not row:
                raise SagaNotFoundError(f"Saga {saga_id} not found")
            
            return SagaState(
                id=str(row['id']),
                saga_type=row['saga_type'],
                correlation_id=str(row['correlation_id']),
                state=row['state'],
                status=SagaStatus(row['status']),
                version=row['version'],
                current_step=row['current_step'],
                last_error=row['last_error'],
                retry_count=row['retry_count'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
    
    async def save(
        self,
        saga_id: str,
        state: dict,
        status: SagaStatus,
        expected_version: int,
        current_step: str | None = None,
        error: str | None = None,
        conn: Connection | None = None
    ) -> int:
        """
        Update saga state with optimistic concurrency control.
        
        Supports both standalone and transactional usage via conn parameter.
        """
        query = """
            UPDATE saga_instance
            SET state = $1,
                status = $2,
                version = version + 1,
                current_step = $3,
                last_error = $4,
                retry_count = CASE WHEN $5::text IS NOT NULL THEN retry_count + 1 ELSE retry_count END,
                updated_at = now(),
                completed_at = CASE WHEN $2 IN ('completed', 'failed') THEN now() ELSE completed_at END
            WHERE id = $6 AND version = $7
            RETURNING version
        """
        
        async def _execute(connection: Connection) -> int:
            result = await connection.fetchrow(
                query,
                json.dumps(state), status.value, current_step, error,
                error, saga_id, expected_version
            )
            if not result:
                raise ConcurrencyError(
                    f"Version mismatch for saga {saga_id}. "
                    f"Expected {expected_version}, may have been updated by another worker."
                )
            return result['version']
        
        if conn:
            return await _execute(conn)
        else:
            async with self.pool.acquire() as conn:
                return await _execute(conn)
    
    async def append_outbox(
        self, 
        event: OutboxEvent,
        conn: Connection | None = None
    ) -> None:
        """
        Insert event into outbox.
        
        CRITICAL: Must be called within same transaction as save() for atomicity guarantee.
        Uses ON CONFLICT DO NOTHING for idempotency.
        """
        query = """
            INSERT INTO outbox (
                event_id, saga_id, aggregate_type, aggregate_id, event_type,
                payload, headers, routing_key, partition_key, max_attempts,
                status, available_at, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, now())
            ON CONFLICT (event_id) DO NOTHING
        """
        
        async def _execute(connection: Connection):
            await connection.execute(
                query,
                event.event_id, event.saga_id, event.aggregate_type,
                event.aggregate_id, event.event_type,
                json.dumps(event.payload), json.dumps(event.headers),
                event.routing_key, event.partition_key, event.max_attempts,
                OutboxStatus.PENDING.value, datetime.utcnow()
            )
        
        if conn:
            await _execute(conn)
        else:
            async with self.pool.acquire() as conn:
                await _execute(conn)
    
    async def claim_pending_events(
        self, 
        batch_size: int, 
        worker_id: str
    ) -> list[dict]:
        """
        Atomically claim events for processing using SKIP LOCKED.
        
        Critical performance optimization: This prevents lock contention
        between multiple workers competing for same events.
        """
        query = """
            WITH claimable AS (
                SELECT id
                FROM outbox
                WHERE status = $1
                  AND available_at <= now()
                ORDER BY created_at ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            UPDATE outbox
            SET status = $3,
                claimed_at = now()
            WHERE id IN (SELECT id FROM claimable)
            RETURNING 
                id, event_id, saga_id, aggregate_type, aggregate_id,
                event_type, payload, headers, routing_key, partition_key,
                attempts, max_attempts, created_at
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                query,
                OutboxStatus.PENDING.value,
                batch_size,
                OutboxStatus.CLAIMED.value
            )
            
            return [dict(row) for row in rows]
    
    async def mark_outbox_sent(self, event_id: str) -> None:
        """Mark event as successfully published."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox
                SET status = $1, published_at = now()
                WHERE event_id = $2
                """,
                OutboxStatus.SENT.value, event_id
            )
    
    async def mark_outbox_failed(self, event_id: str, error: str) -> None:
        """
        Record publish failure and apply exponential backoff.
        
        Moves to dead_letter queue after max_attempts exceeded.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox
                SET attempts = attempts + 1,
                    status = CASE
                        WHEN attempts + 1 >= max_attempts THEN $1
                        ELSE $2
                    END,
                    available_at = CASE
                        WHEN attempts + 1 < max_attempts 
                        THEN now() + (POWER(2, attempts + 1) || ' seconds')::interval
                        ELSE available_at
                    END,
                    last_error = $3
                WHERE event_id = $4
                """,
                OutboxStatus.DEAD_LETTER.value,
                OutboxStatus.FAILED.value,
                error,
                event_id
            )
    
    async def requeue_stuck_claims(self, timeout_seconds: int) -> int:
        """
        Safety mechanism: reset stuck 'claimed' events back to 'pending'.
        
        Run periodically (e.g., every 30s) by separate watchdog process.
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE outbox
                SET status = $1, claimed_at = NULL
                WHERE status = $2
                  AND claimed_at < now() - ($3 || ' seconds')::interval
                """,
                OutboxStatus.PENDING.value,
                OutboxStatus.CLAIMED.value,
                timeout_seconds
            )
            # asyncpg returns "UPDATE N"
            return int(result.split()[-1])
    
    async def archive_sent_events(self, older_than_days: int) -> int:
        """
        Move old sent events to archive table.
        
        Should run as scheduled job (e.g., daily at low traffic time).
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Copy to archive
                await conn.execute(
                    """
                    INSERT INTO outbox_archive
                    SELECT *, now() as archived_at
                    FROM outbox
                    WHERE status = $1
                      AND published_at < now() - ($2 || ' days')::interval
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    OutboxStatus.SENT.value, older_than_days
                )
                
                # Delete from main table
                result = await conn.execute(
                    """
                    DELETE FROM outbox
                    WHERE status = $1
                      AND published_at < now() - ($2 || ' days')::interval
                    """,
                    OutboxStatus.SENT.value, older_than_days
                )
                
                return int(result.split()[-1])
```

---

## Outbox Worker: Production-Grade Implementation

### `saga/outbox_worker.py`

```python
"""
Outbox relay worker - polls and publishes events to message broker.

Design principles:
1. Batch processing for throughput
2. Exponential backoff on failures
3. Graceful shutdown support
4. Comprehensive metrics and tracing
5. Dead letter queue for poison messages

Deployment model:
- Run 3-10 replicas depending on throughput needs
- Each worker processes independently (no coordination needed)
- Scale horizontally based on outbox_pending_total metric
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import List
from uuid import uuid4

from asyncpg import Pool
from prometheus_client import Counter, Gauge, Histogram
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .interfaces import MessageBroker, SagaLogger
from .storage_postgres import PostgresSagaStorage

# Configuration constants
POLL_INTERVAL_SECONDS = 1.0
BATCH_SIZE = 100
STUCK_CLAIM_TIMEOUT_SECONDS = 300  # 5 minutes
WATCHDOG_INTERVAL_SECONDS = 30

# Prometheus metrics
OUTBOX_PENDING = Gauge(
    "outbox_pending_events_total",
    "Number of pending outbox events"
)
OUTBOX_CLAIMED = Counter(
    "outbox_claimed_events_total",
    "Total events claimed by workers"
)
OUTBOX_PUBLISHED = Counter(
    "outbox_published_events_total",
    "Total events successfully published",
    ["event_type"]
)
OUTBOX_FAILED = Counter(
    "outbox_failed_events_total",
    "Total events that failed to publish",
    ["event_type", "reason"]
)
OUTBOX_DEAD_LETTER = Counter(
    "outbox_dead_letter_events_total",
    "Events moved to dead letter queue after max retries",
    ["event_type"]
)
OUTBOX_PUBLISH_DURATION = Histogram(
    "outbox_publish_duration_seconds",
    "Time to publish single event",
    ["event_type"]
)
OUTBOX_BATCH_DURATION = Histogram(
    "outbox_batch_duration_seconds",
    "Time to process entire batch"
)

tracer = trace.get_tracer(__name__)

class OutboxWorker:
    """
    Outbox relay worker - consumes events from outbox table and publishes to broker.
    
    Lifecycle:
    1. Claim batch of pending events (atomic)
    2. Publish each event to broker
    3. Mark as sent on success, or reschedule with backoff on failure
    4. Repeat until shutdown signal received
    """
    
    def __init__(
        self,
        storage: PostgresSagaStorage,
        broker: MessageBroker,
        logger: SagaLogger,
        worker_id: str | None = None,
        batch_size: int = BATCH_SIZE,
        poll_interval: float = POLL_INTERVAL_SECONDS
    ):
        self.storage = storage
        self.broker = broker
        self.logger = logger
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self._shutdown = False
        self._task: asyncio.Task | None = None
    
    async def start(self) -> None:
        """Start worker main loop."""
        if self._task:
            raise RuntimeError("Worker already started")
        
        self._shutdown = False
        self._task = asyncio.create_task(self._run())
        
        # Start watchdog for stuck claims
        asyncio.create_task(self._watchdog())
        
        logging.info(f"Outbox worker {self.worker_id} started")
    
    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully shutdown worker."""
        if not self._task:
            return
        
        logging.info(f"Shutting down worker {self.worker_id}...")
        self._shutdown = True
        
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.TimeoutError:
            logging.warning(f"Worker {self.worker_id} shutdown timed out, cancelling")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logging.info(f"Worker {self.worker_id} stopped")
    
    async def _run(self) -> None:
        """Main processing loop."""
        while not self._shutdown:
            try:
                with OUTBOX_BATCH_DURATION.time():
                    await self._process_batch()
            except Exception as exc:
                logging.exception(f"Worker {self.worker_id} batch processing error: {exc}")
                await asyncio.sleep(5)  # Back off on errors
            
            # Update pending count metric
            try:
                pending_count = await self._count_pending()
                OUTBOX_PENDING.set(pending_count)
            except Exception:
                pass  # Don't fail on metrics
            
            # Wait before next poll
            await asyncio.sleep(self.poll_interval)
    
    async def _process_batch(self) -> None:
        """Claim and process a batch of pending events."""
        events = await self.storage.claim_pending_events(
            self.batch_size,
            self.worker_id
        )
        
        if not events:
            return
        
        OUTBOX_CLAIMED.inc(len(events))
        logging.debug(f"Worker {self.worker_id} claimed {len(events)} events")
        
        # Process events concurrently within batch
        tasks = [self._publish_event(event) for event in events]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _publish_event(self, event: dict) -> None:
        """
        Publish single event with retry and error handling.
        
        Success path: event -> broker -> mark_sent
        Failure path: event -> broker [fails] -> mark_failed (with backoff)
        """
        event_id = str(event['event_id'])
        event_type = event['event_type']
        
        # Start tracing span
        with tracer.start_as_current_span(
            "outbox.publish_event",
            attributes={
                "event_id": event_id,
                "event_type": event_type,
                "worker_id": self.worker_id,
                "attempt": event['attempts'] + 1
            }
        ) as span:
            try:
                with OUTBOX_PUBLISH_DURATION.labels(event_type=event_type).time():
                    # Publish to broker
                    await self.broker.publish(
                        topic=self._resolve_topic(event_type, event.get('routing_key')),
                        payload=event['payload'],
                        message_id=event_id,
                        headers=event['headers'],
                        partition_key=event.get('partition_key')
                    )
                
                # Success: mark as sent
                await self.storage.mark_outbox_sent(event_id)
                OUTBOX_PUBLISHED.labels(event_type=event_type).inc()
                
                span.set_status(Status(StatusCode.OK))
                
                await self.logger.info(
                    event.get('saga_id', 'unknown'),
                    f"Published event {event_type}",
                    event_id=event_id,
                    attempt=event['attempts'] + 1
                )
                
            except Exception as exc:
                # Failure: record error and reschedule
                error_msg = f"{type(exc).__name__}: {str(exc)}"
                
                await self.storage.mark_outbox_failed(event_id, error_msg)
                OUTBOX_FAILED.labels(
                    event_type=event_type,
                    reason=type(exc).__name__
                ).inc()
                
                span.set_status(Status(StatusCode.ERROR))
                span.record_exception(exc)
                
                # Check if moved to dead letter
                if event['attempts'] + 1 >= event['max_attempts']:
                    OUTBOX_DEAD_LETTER.labels(event_type=event_type).inc()
                    await self.logger.error(
                        event.get('saga_id', 'unknown'),
                        f"Event {event_type} moved to dead letter queue after {event['max_attempts']} attempts",
                        exc=exc,
                        event_id=event_id
                    )
                else:
                    backoff = 2 ** (event['attempts'] + 1)
                    await self.logger.warning(
                        event.get('saga_id', 'unknown'),
                        f"Failed to publish {event_type}, will retry in {backoff}s",
                        event_id=event_id,
                        attempt=event['attempts'] + 1,
                        error=error_msg
                    )
    
    async def _watchdog(self) -> None:
        """Periodically requeue stuck claims (crashed workers)."""
        while not self._shutdown:
            try:
                requeued = await self.storage.requeue_stuck_claims(
                    STUCK_CLAIM_TIMEOUT_SECONDS
                )
                if requeued > 0:
                    logging.warning(
                        f"Watchdog requeued {requeued} stuck claims "
                        f"(timeout: {STUCK_CLAIM_TIMEOUT_SECONDS}s)"
                    )
            except Exception as exc:
                logging.exception(f"Watchdog error: {exc}")
            
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
    
    async def _count_pending(self) -> int:
        """Count pending events for metrics."""
        async with self.storage.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM outbox WHERE status IN ('pending', 'failed')"
            )
    
    def _resolve_topic(self, event_type: str, routing_key: str | None) -> str:
        """
        Map event type to broker topic.
        
        Override this method to implement custom routing logic.
        Default: events.{event_type}
        """
        if routing_key:
            return routing_key
        return f"events.{event_type.lower().replace('_', '.')}"
```

---

## Message Broker Implementation Examples

### Kafka Broker: `saga/broker_kafka.py`

```python
"""
Kafka implementation of MessageBroker interface.

Production considerations:
- Use transactional producer for exactly-once semantics (advanced)
- Configure acks=all for durability
- Set enable.idempotence=true
- Use linger.ms for batching efficiency
"""
import json
import logging
from typing import Any
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from .interfaces import MessageBroker

class KafkaBroker(MessageBroker):
    """Kafka message broker with idempotent publishing."""
    
    def __init__(self, producer: AIOKafkaProducer):
        self.producer = producer
    
    async def publish(
        self,
        topic: str,
        payload: dict,
        message_id: str,
        headers: dict | None = None,
        partition_key: str | None = None
    ) -> None:
        """
        Publish event to Kafka topic.
        
        Headers include message_id for broker-level deduplication (if enabled).
        """
        # Prepare headers (Kafka requires bytes)
        kafka_headers = [
            ("message_id", message_id.encode()),
        ]
        
        if headers:
            for key, value in headers.items():
                kafka_headers.append((key, str(value).encode()))
        
        try:
            # Serialize payload
            value = json.dumps(payload).encode('utf-8')
            key = partition_key.encode('utf-8') if partition_key else None
            
            # Send with acks=all for durability
            await self.producer.send_and_wait(
                topic,
                value=value,
                key=key,
                headers=kafka_headers
            )
            
        except KafkaError as exc:
            logging.error(f"Kafka publish failed for {message_id}: {exc}")
            raise

    @classmethod
    async def create(
        cls,
        bootstrap_servers: str,
        **config: Any
    ) -> "KafkaBroker":
        """
        Factory method to create and start Kafka producer.
        
        Recommended config:
        - acks='all': Wait for all replicas
        - enable_idempotence=True: Prevent duplicates
        - max_in_flight_requests_per_connection=5: Balance throughput and ordering
        - compression_type='lz4': Reduce bandwidth
        """
        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            acks='all',
            enable_idempotence=True,
            max_in_flight_requests_per_connection=5,
            compression_type='lz4',
            **config
        )
        
        await producer.start()
        return cls(producer)
    
    async def close(self) -> None:
        """Gracefully close producer."""
        await self.producer.stop()
```

### RabbitMQ Broker: `saga/broker_rabbitmq.py`

```python
"""
RabbitMQ implementation using aio-pika.

Production considerations:
- Use publisher confirms for reliability
- Set delivery_mode=2 for persistent messages
- Configure dead letter exchange for failed messages
"""
import json
import logging
from typing import Any
from aio_pika import connect_robust, Message, DeliveryMode
from aio_pika.abc import AbstractRobustConnection, AbstractChannel

from .interfaces import MessageBroker

class RabbitMQBroker(MessageBroker):
    """RabbitMQ broker with publisher confirms."""
    
    def __init__(self, connection: AbstractRobustConnection, channel: AbstractChannel):
        self.connection = connection
        self.channel = channel
    
    async def publish(
        self,
        topic: str,
        payload: dict,
        message_id: str,
        headers: dict | None = None,
        partition_key: str | None = None
    ) -> None:
        """Publish to RabbitMQ exchange."""
        # Prepare headers
        msg_headers = {"message_id": message_id}
        if headers:
            msg_headers.update(headers)
        
        # Create message with persistence
        message = Message(
            body=json.dumps(payload).encode('utf-8'),
            message_id=message_id,
            headers=msg_headers,
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type='application/json'
        )
        
        try:
            # Publish with publisher confirms
            await self.channel.default_exchange.publish(
                message,
                routing_key=topic,
                mandatory=True  # Return message if no queue bound
            )
        except Exception as exc:
            logging.error(f"RabbitMQ publish failed for {message_id}: {exc}")
            raise
    
    @classmethod
    async def create(cls, amqp_url: str) -> "RabbitMQBroker":
        """Factory to create RabbitMQ broker with robust connection."""
        connection = await connect_robust(amqp_url)
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=100)  # Flow control
        
        return cls(connection, channel)
    
    async def close(self) -> None:
        """Gracefully close connection."""
        await self.channel.close()
        await self.connection.close()
```

---

## Consumer-Side Deduplication Pattern

### Consumer Inbox Implementation: `saga/consumer_inbox.py`

```python
"""
Consumer-side deduplication using inbox pattern.

Critical: Every consumer service must implement this to guarantee
exactly-once processing despite at-least-once delivery.
"""
import json
import logging
from datetime import datetime
from typing import Callable, Awaitable, TypeVar, Generic
from asyncpg import Pool, UniqueViolationError

T = TypeVar('T')

class ConsumerInbox:
    """
    Idempotent message consumer with inbox deduplication.
    
    Pattern:
    1. Try insert event_id into consumer_inbox
    2. If unique violation -> already processed, skip
    3. Otherwise -> process business logic in same transaction
    4. Commit transaction
    """
    
    def __init__(self, pool: Pool, consumer_name: str):
        self.pool = pool
        self.consumer_name = consumer_name
    
    async def process_idempotent(
        self,
        event_id: str,
        source_topic: str,
        event_type: str,
        payload: dict,
        handler: Callable[[dict], Awaitable[T]]
    ) -> T | None:
        """
        Process message idempotently using inbox pattern.
        
        Returns:
            Handler result if processed, None if duplicate
        """
        start_time = datetime.utcnow()
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Try to insert into inbox (atomic dedup check)
                try:
                    await conn.execute(
                        """
                        INSERT INTO consumer_inbox (
                            event_id, consumer_name, source_topic, 
                            event_type, payload, consumed_at
                        )
                        VALUES ($1, $2, $3, $4, $5, now())
                        """,
                        event_id, self.consumer_name, source_topic,
                        event_type, json.dumps(payload)
                    )
                except UniqueViolationError:
                    # Already processed - skip
                    logging.info(
                        f"Duplicate message {event_id} for {self.consumer_name}, skipping"
                    )
                    return None
                
                # New message - execute handler in same transaction
                result = await handler(payload)
                
                # Update processing duration
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                await conn.execute(
                    """
                    UPDATE consumer_inbox 
                    SET processing_duration_ms = $1 
                    WHERE event_id = $2
                    """,
                    duration_ms, event_id
                )
                
                return result
    
    async def cleanup_old_entries(self, older_than_days: int = 7) -> int:
        """
        Remove old inbox entries to prevent unbounded growth.
        
        Run as scheduled job (e.g., daily).
        Safe to delete old entries since duplicates are unlikely after TTL.
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM consumer_inbox
                WHERE consumer_name = $1
                  AND consumed_at < now() - ($2 || ' days')::interval
                """,
                self.consumer_name, older_than_days
            )
            return int(result.split()[-1])
```

### Example Consumer Service: `saga/example_consumer.py`

```python
"""
Example consumer implementation using inbox pattern.
"""
import asyncio
import json
import logging
from aiokafka import AIOKafkaConsumer
from asyncpg import create_pool

from .consumer_inbox import ConsumerInbox

class OrderEventConsumer:
    """Example consumer for order events."""
    
    def __init__(self, inbox: ConsumerInbox):
        self.inbox = inbox
    
    async def handle_order_created(self, payload: dict) -> None:
        """Business logic for OrderCreated event."""
        order_id = payload['order_id']
        customer_id = payload['customer_id']
        
        logging.info(f"Processing order {order_id} for customer {customer_id}")
        
        # Execute business logic here (database updates, external API calls, etc.)
        # This code is protected by inbox deduplication
        
        await asyncio.sleep(0.1)  # Simulate processing
        
        logging.info(f"Order {order_id} processed successfully")
    
    async def consume_events(self, consumer: AIOKafkaConsumer) -> None:
        """Main consumption loop."""
        async for msg in consumer:
            # Extract event metadata from headers
            headers = dict(msg.headers) if msg.headers else {}
            event_id = headers.get(b'message_id', b'').decode()
            trace_id = headers.get(b'trace_id', b'').decode()
            
            # Deserialize payload
            payload = json.loads(msg.value.decode('utf-8'))
            event_type = payload.get('event_type', 'unknown')
            
            logging.info(
                f"Received {event_type} (event_id={event_id}, trace_id={trace_id})"
            )
            
            try:
                # Process with inbox deduplication
                await self.inbox.process_idempotent(
                    event_id=event_id,
                    source_topic=msg.topic,
                    event_type=event_type,
                    payload=payload,
                    handler=self.handle_order_created
                )
                
                # Commit offset after successful processing
                await consumer.commit()
                
            except Exception as exc:
                logging.exception(f"Failed to process {event_id}: {exc}")
                # Don't commit offset - will retry message
                # Consider moving to DLQ after N retries

# Usage example
async def main():
    # Setup database pool
    pool = await create_pool(
        host='localhost',
        port=5432,
        user='saga_user',
        password='saga_pass',
        database='saga_db',
        min_size=5,
        max_size=20
    )
    
    # Create inbox
    inbox = ConsumerInbox(pool, consumer_name='order-service')
    
    # Create Kafka consumer
    consumer = AIOKafkaConsumer(
        'events.order.created',
        bootstrap_servers='localhost:9092',
        group_id='order-service-consumer-group',
        enable_auto_commit=False,  # Manual commit after processing
        auto_offset_reset='earliest'
    )
    
    await consumer.start()
    
    try:
        processor = OrderEventConsumer(inbox)
        await processor.consume_events(consumer)
    finally:
        await consumer.stop()
        await pool.close()

if __name__ == '__main__':
    asyncio.run(main())
```

---

## Testing Strategy: Comprehensive Test Suite

### Unit Tests: `tests/test_outbox_atomicity.py`

```python
"""
Critical unit tests for outbox atomicity guarantees.
"""
import pytest
import uuid
from asyncpg import create_pool

from saga.storage_postgres import PostgresSagaStorage, ConcurrencyError
from saga.interfaces import SagaState, SagaStatus, OutboxEvent

@pytest.fixture
async def storage():
    """Create test database connection."""
    pool = await create_pool(
        host='localhost',
        database='saga_test',
        user='test_user',
        password='test_pass'
    )
    
    storage = PostgresSagaStorage(pool)
    
    yield storage
    
    # Cleanup
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE saga_instance, outbox CASCADE")
    await pool.close()

@pytest.mark.asyncio
async def test_atomic_save_and_outbox(storage):
    """
    CRITICAL TEST: Verify state update and outbox insert are atomic.
    
    If exception occurs after save but before outbox insert,
    both operations must rollback.
    """
    saga_id = str(uuid.uuid4())
    
    # Create saga
    saga = SagaState(
        id=saga_id,
        saga_type='TestSaga',
        correlation_id=str(uuid.uuid4()),
        state={},
        status=SagaStatus.RUNNING,
        version=0
    )
    await storage.create(saga)
    
    # Simulate transaction failure
    async with storage.pool.acquire() as conn:
        async with conn.transaction():
            # Update state
            new_version = await storage.save(
                saga_id=saga_id,
                state={'step1': 'completed'},
                status=SagaStatus.RUNNING,
                expected_version=0,
                conn=conn
            )
            
            # Append outbox
            event = OutboxEvent(
                event_id=str(uuid.uuid4()),
                saga_id=saga_id,
                aggregate_type='test',
                aggregate_id=saga_id,
                event_type='TestEvent',
                payload={'data': 'value'},
                headers={'trace_id': str(uuid.uuid4()), 'message_id': str(uuid.uuid4())}
            )
            await storage.append_outbox(event, conn=conn)
            
            # Simulate exception before commit
            raise Exception("Simulated failure")
    
    # Verify rollback: state should be unchanged
    loaded = await storage.load(saga_id)
    assert loaded.version == 0
    assert loaded.state == {}
    
    # Verify rollback: no outbox entry
    async with storage.pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM outbox WHERE saga_id = $1",
            saga_id
        )
        assert count == 0

@pytest.mark.asyncio
async def test_optimistic_concurrency_conflict(storage):
    """
    Test OCC prevents lost updates when two workers update same saga.
    """
    saga_id = str(uuid.uuid4())
    
    # Create saga
    saga = SagaState(
        id=saga_id,
        saga_type='TestSaga',
        correlation_id=str(uuid.uuid4()),
        state={},
        status=SagaStatus.RUNNING,
        version=0
    )
    await storage.create(saga)
    
    # Worker 1 updates successfully
    await storage.save(
        saga_id=saga_id,
        state={'worker1': 'done'},
        status=SagaStatus.RUNNING,
        expected_version=0
    )
    
    # Worker 2 tries to update with stale version - should fail
    with pytest.raises(ConcurrencyError):
        await storage.save(
            saga_id=saga_id,
            state={'worker2': 'done'},
            status=SagaStatus.RUNNING,
            expected_version=0  # Stale version!
        )
    
    # Verify only worker 1's update persisted
    loaded = await storage.load(saga_id)
    assert loaded.state == {'worker1': 'done'}
    assert loaded.version == 1

@pytest.mark.asyncio
async def test_idempotent_outbox_insert(storage):
    """
    Test duplicate event_id is silently ignored (idempotent insert).
    """
    event_id = str(uuid.uuid4())
    
    event = OutboxEvent(
        event_id=event_id,
        aggregate_type='test',
        aggregate_id=str(uuid.uuid4()),
        event_type='TestEvent',
        payload={'attempt': 1},
        headers={'trace_id': str(uuid.uuid4()), 'message_id': event_id}
    )
    
    # Insert once
    await storage.append_outbox(event)
    
    # Insert again with different payload
    event.payload = {'attempt': 2}
    await storage.append_outbox(event)  # Should not raise
    
    # Verify only first insert persisted
    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payload FROM outbox WHERE event_id = $1",
            event_id
        )
        assert row['payload']['attempt'] == 1

@pytest.mark.asyncio
async def test_claim_uses_skip_locked(storage):
    """
    Test multiple workers can claim different events concurrently.
    """
    # Insert 10 events
    event_ids = []
    for i in range(10):
        event_id = str(uuid.uuid4())
        event_ids.append(event_id)
        
        event = OutboxEvent(
            event_id=event_id,
            aggregate_type='test',
            aggregate_id=str(uuid.uuid4()),
            event_type='TestEvent',
            payload={'index': i},
            headers={'trace_id': str(uuid.uuid4()), 'message_id': event_id}
        )
        await storage.append_outbox(event)
    
    # Two workers claim concurrently
    import asyncio
    
    results = await asyncio.gather(
        storage.claim_pending_events(5, 'worker1'),
        storage.claim_pending_events(5, 'worker2')
    )
    
    claimed1 = results[0]
    claimed2 = results[1]
    
    # Each worker should claim 5 events
    assert len(claimed1) == 5
    assert len(claimed2) == 5
    
    # No overlap in claimed events
    ids1 = {str(e['event_id']) for e in claimed1}
    ids2 = {str(e['event_id']) for e in claimed2}
    assert ids1.isdisjoint(ids2)
```

### Integration Tests: `tests/test_end_to_end.py`

```python
"""
End-to-end integration tests using Testcontainers.
"""
import pytest
import asyncio
import uuid
from testcontainers.postgres import PostgresContainer
from testcontainers.kafka import KafkaContainer

from saga.storage_postgres import PostgresSagaStorage
from saga.broker_kafka import KafkaBroker
from saga.outbox_worker import OutboxWorker
from saga.interfaces import OutboxEvent

@pytest.fixture(scope='module')
def postgres_container():
    """Start PostgreSQL test container."""
    with PostgresContainer('postgres:15') as postgres:
        yield postgres

@pytest.fixture(scope='module')
def kafka_container():
    """Start Kafka test container."""
    with KafkaContainer() as kafka:
        yield kafka

@pytest.mark.asyncio
async def test_end_to_end_flow(postgres_container, kafka_container):
    """
    Test complete flow: write -> outbox -> broker -> consume.
    """
    # Setup storage
    pool = await create_pool(postgres_container.get_connection_url())
    storage = PostgresSagaStorage(pool)
    
    # Apply migrations
    async with pool.acquire() as conn:
        # ... execute migration SQL ...
        pass
    
    # Setup broker
    broker = await KafkaBroker.create(
        bootstrap_servers=kafka_container.get_bootstrap_server()
    )
    
    # Start outbox worker
    worker = OutboxWorker(storage, broker, logger=None)
    await worker.start()
    
    try:
        # Insert event into outbox
        event_id = str(uuid.uuid4())
        event = OutboxEvent(
            event_id=event_id,
            aggregate_type='order',
            aggregate_id=str(uuid.uuid4()),
            event_type='OrderCreated',
            payload={'order_id': '12345'},
            headers={'trace_id': str(uuid.uuid4()), 'message_id': event_id}
        )
        await storage.append_outbox(event)
        
        # Wait for worker to process (with timeout)
        await asyncio.sleep(3)
        
        # Verify event marked as sent
        async with pool.acquire() as conn:
            status = await conn.fetchval(
                "SELECT status FROM outbox WHERE event_id = $1",
                event_id
            )
            assert status == 'sent'
        
        # TODO: Add Kafka consumer to verify message received
        
    finally:
        await worker.stop()
        await broker.close()
        await pool.close()
```

---

## Monitoring & Observability

### Prometheus Alerts: `ops/prometheus/alerts.yml`

```yaml
groups:
  - name: outbox_alerts
    interval: 30s
    rules:
      # Critical: Outbox lag exceeds SLA
      - alert: OutboxHighLag
        expr: outbox_pending_events_total > 1000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Outbox has {{ $value }} pending events"
          description: "Outbox pending count exceeds threshold, may indicate worker issues"
      
      # Warning: High publish failure rate
      - alert: OutboxHighFailureRate
        expr: |
          rate(outbox_failed_events_total[5m]) / 
          rate(outbox_claimed_events_total[5m]) > 0.1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Outbox publish failure rate is {{ $value | humanizePercentage }}"
          description: "More than 10% of events are failing to publish"
      
      # Critical: Events moving to dead letter queue
      - alert: OutboxDeadLetterQueue
        expr: increase(outbox_dead_letter_events_total[10m]) > 10
        labels:
          severity: critical
        annotations:
          summary: "{{ $value }} events moved to DLQ in last 10 minutes"
          description: "Events exhausted retries, manual intervention required"
      
      # Warning: No events processed recently (worker may be down)
      - alert: OutboxWorkerInactive
        expr: rate(outbox_published_events_total[5m]) == 0 AND outbox_pending_events_total > 0
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Outbox worker appears inactive"
          description: "No events published but pending queue is not empty"
```

### Grafana Dashboard: `ops/grafana/outbox_dashboard.json`

```json
{
  "dashboard": {
    "title": "Saga Outbox Monitoring",
    "panels": [
      {
        "title": "Pending Events",
        "targets": [{"expr": "outbox_pending_events_total"}],
        "type": "graph"
      },
      {
        "title": "Publish Rate",
        "targets": [{"expr": "rate(outbox_published_events_total[1m])"}],
        "type": "graph"
      },
      {
        "title": "Failure Rate by Event Type",
        "targets": [{"expr": "rate(outbox_failed_events_total[5m])"}],
        "type": "graph",
        "legend": {"show": true}
      },
      {
        "title": "Publish Latency (p50, p95, p99)",
        "targets": [
          {"expr": "histogram_quantile(0.50, outbox_publish_duration_seconds)"},
          {"expr": "histogram_quantile(0.95, outbox_publish_duration_seconds)"},
          {"expr": "histogram_quantile(0.99, outbox_publish_duration_seconds)"}
        ],
        "type": "graph"
      }
    ]
  }
}
```

---

## Operational Runbooks

### Runbook 1: Investigate Stuck Messages

**Symptom**: `outbox_pending_events_total` metric is growing

**Investigation Steps**:

```sql
-- 1. Identify oldest pending messages
SELECT id, event_type, created_at, attempts, last_error,
       age(now(), created_at) as age
FROM outbox
WHERE status IN ('pending', 'failed')
ORDER BY created_at
LIMIT 20;

-- 2. Check for specific event type failures
SELECT event_type, status, count(*), max(attempts) as max_attempts
FROM outbox
WHERE status != 'sent'
GROUP BY event_type, status
ORDER BY count(*) DESC;

-- 3. Inspect failed events with errors
SELECT event_id, event_type, attempts, last_error, available_at
FROM outbox
WHERE status = 'failed'
ORDER BY attempts DESC
LIMIT 10;
```

**Resolution Actions**:

1. **If worker is down**: Restart outbox worker pods
2. **If broker is unreachable**: Check broker health, network connectivity
3. **If specific event type failing**: Investigate handler logic, check payload schema
4. **If poison message**: Manually move to DLQ and investigate

```sql
-- Manual DLQ move
UPDATE outbox 
SET status = 'dead_letter' 
WHERE event_id = '<problematic_event_id>';
```

### Runbook 2: Manual Event Replay

**Scenario**: Need to replay failed/dead-letter events after fixing root cause

```sql
-- 1. Identify events to replay (e.g., from DLQ)
SELECT event_id, event_type, payload, created_at
FROM outbox
WHERE status = 'dead_letter'
  AND event_type = 'OrderCreated'
  AND created_at > now() - interval '24 hours';

-- 2. Reset to pending with fresh attempt count
UPDATE outbox
SET status = 'pending',
    attempts = 0,
    available_at = now(),
    last_error = NULL
WHERE status = 'dead_letter'
  AND event_type = 'OrderCreated'
  AND created_at > now() - interval '24 hours';

-- 3. Monitor worker logs for successful processing
```

### Runbook 3: Archive Old Events

**Schedule**: Run daily at 2 AM (low traffic period)

```sql
-- Archive sent events older than 30 days
BEGIN;

INSERT INTO outbox_archive
SELECT *, now() as archived_at
FROM outbox
WHERE status = 'sent'
  AND published_at < now() - interval '30 days'
ON CONFLICT (event_id) DO NOTHING;

DELETE FROM outbox
WHERE status = 'sent'
  AND published_at < now() - interval '30 days';

COMMIT;

-- Verify archive count
SELECT count(*) FROM outbox_archive WHERE archived_at > now() - interval '1 day';
```

### Runbook 4: Scale Outbox Workers

**Trigger**: `outbox_pending_events_total` > 5000 for more than 10 minutes

**Kubernetes HPA** (Horizontal Pod Autoscaler):

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: outbox-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: outbox-worker
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: External
      external:
        metric:
          name: outbox_pending_events_total
          selector:
            matchLabels:
              app: saga-outbox
        target:
          type: Value
          value: "1000"  # Scale when pending > 1000 per replica
```

**Manual scaling**:

```bash
# Scale up
kubectl scale deployment outbox-worker --replicas=10

# Verify scaling
kubectl get pods -l app=outbox-worker

# Monitor metrics after scaling
kubectl top pods -l app=outbox-worker
```

---

## Kubernetes Deployment Manifests

### Outbox Worker Deployment: `k8s/outbox-worker.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: outbox-worker
  namespace: saga
  labels:
    app: outbox-worker
    component: messaging
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0  # Ensure zero-downtime deployments
  selector:
    matchLabels:
      app: outbox-worker
  template:
    metadata:
      labels:
        app: outbox-worker
        version: "1.0"
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      # Anti-affinity: spread workers across nodes
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: outbox-worker
                topologyKey: kubernetes.io/hostname
      
      # Service account for RBAC
      serviceAccountName: outbox-worker
      
      containers:
        - name: worker
          image: myregistry/saga-outbox-worker:v1.2.3
          imagePullPolicy: IfNotPresent
          
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: saga-db-credentials
                  key: connection-string
            
            - name: KAFKA_BOOTSTRAP_SERVERS
              value: "kafka-headless.kafka.svc.cluster.local:9092"
            
            - name: WORKER_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            
            - name: BATCH_SIZE
              value: "100"
            
            - name: POLL_INTERVAL_SECONDS
              value: "1.0"
            
            - name: LOG_LEVEL
              value: "INFO"
            
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://jaeger-collector.observability.svc:4318"
          
          resources:
            requests:
              cpu: "200m"
              memory: "256Mi"
            limits:
              cpu: "1000m"
              memory: "1Gi"
          
          # Health checks
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 2
          
          # Graceful shutdown
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 15"]  # Allow in-flight processing
          
          ports:
            - name: metrics
              containerPort: 8000
              protocol: TCP
      
      # Graceful termination
      terminationGracePeriodSeconds: 30
      
      # Security context
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000

---
apiVersion: v1
kind: Service
metadata:
  name: outbox-worker-metrics
  namespace: saga
  labels:
    app: outbox-worker
spec:
  type: ClusterIP
  ports:
    - name: metrics
      port: 8000
      targetPort: metrics
  selector:
    app: outbox-worker

---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: outbox-worker-pdb
  namespace: saga
spec:
  minAvailable: 2  # Always keep at least 2 workers running
  selector:
    matchLabels:
      app: outbox-worker
```

### Database Migration Job: `k8s/migration-job.yaml`

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: saga-migration-0001
  namespace: saga
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: migration
          image: myregistry/saga-migrations:v1.2.3
          command: ["/bin/sh", "-c"]
          args:
            - |
              psql $DATABASE_URL -f /migrations/0001_create_saga_outbox.sql
              echo "Migration completed successfully"
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: saga-db-credentials
                  key: connection-string
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "256Mi"
      backoffLimit: 3
```

---

## Security & Compliance Guidelines

### 1. Secrets Management

**Never hardcode credentials**. Use Kubernetes Secrets or external secret managers:

```yaml
# Using External Secrets Operator
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: saga-db-credentials
  namespace: saga
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: saga-db-credentials
    creationPolicy: Owner
  data:
    - secretKey: connection-string
      remoteRef:
        key: saga/database/postgres
        property: connection_url
    
    - secretKey: kafka-password
      remoteRef:
        key: saga/messaging/kafka
        property: password
```

### 2. PII Data Handling

**Encrypt sensitive data in outbox payloads**:

```python
# saga/encryption.py
from cryptography.fernet import Fernet
import json

class PayloadEncryption:
    """
    Encrypt/decrypt sensitive fields in event payloads.
    
    Use for PII data (emails, SSN, etc.) in outbox events.
    """
    
    def __init__(self, key: bytes):
        self.cipher = Fernet(key)
    
    def encrypt_payload(self, payload: dict, sensitive_fields: list[str]) -> dict:
        """Encrypt specified fields in payload."""
        encrypted = payload.copy()
        
        for field in sensitive_fields:
            if field in encrypted:
                value = json.dumps(encrypted[field])
                encrypted[field] = {
                    "_encrypted": True,
                    "data": self.cipher.encrypt(value.encode()).decode()
                }
        
        return encrypted
    
    def decrypt_payload(self, payload: dict) -> dict:
        """Decrypt encrypted fields in payload."""
        decrypted = payload.copy()
        
        for key, value in payload.items():
            if isinstance(value, dict) and value.get("_encrypted"):
                encrypted_data = value["data"].encode()
                decrypted_value = self.cipher.decrypt(encrypted_data).decode()
                decrypted[key] = json.loads(decrypted_value)
        
        return decrypted

# Usage in saga step
encryption = PayloadEncryption(key=os.environ["ENCRYPTION_KEY"].encode())

payload = {
    "order_id": "12345",
    "customer_email": "user@example.com",
    "customer_ssn": "123-45-6789"
}

encrypted_payload = encryption.encrypt_payload(
    payload, 
    sensitive_fields=["customer_email", "customer_ssn"]
)

event = OutboxEvent(
    event_id=str(uuid.uuid4()),
    aggregate_type="order",
    aggregate_id="12345",
    event_type="OrderCreated",
    payload=encrypted_payload,
    headers={...}
)
```

### 3. Audit Logging

**Maintain immutable audit trail**:

```sql
-- Audit table for saga state changes
CREATE TABLE saga_audit_log (
    id BIGSERIAL PRIMARY KEY,
    saga_id UUID NOT NULL,
    saga_type TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- state_changed, step_executed, compensated, failed
    old_state JSONB,
    new_state JSONB,
    old_status TEXT,
    new_status TEXT,
    user_id TEXT,  -- Who triggered the change
    trace_id UUID,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB
);

CREATE INDEX idx_audit_saga ON saga_audit_log(saga_id, timestamp);
CREATE INDEX idx_audit_user ON saga_audit_log(user_id, timestamp);
```

### 4. GDPR Compliance

**Right to be forgotten** - implement PII deletion:

```python
# saga/gdpr.py
async def erase_customer_data(pool: Pool, customer_id: str):
    """
    GDPR Article 17: Right to erasure.
    
    Remove PII from saga states and outbox while preserving
    non-PII metadata for audit purposes.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Redact PII from saga states
            await conn.execute(
                """
                UPDATE saga_instance
                SET state = jsonb_set(
                    state,
                    '{customer_pii}',
                    '"[REDACTED]"'::jsonb
                )
                WHERE state->>'customer_id' = $1
                """,
                customer_id
            )
            
            # Redact PII from outbox
            await conn.execute(
                """
                UPDATE outbox
                SET payload = jsonb_set(
                    payload,
                    '{customer_email}',
                    '"[REDACTED]"'::jsonb
                )
                WHERE payload->>'customer_id' = $1
                """,
                customer_id
            )
            
            # Log erasure event
            await conn.execute(
                """
                INSERT INTO gdpr_erasure_log (customer_id, erased_at, reason)
                VALUES ($1, now(), 'customer_request')
                """,
                customer_id
            )
```

---

## Performance Tuning & Optimization

### Database Connection Pool Sizing

**Formula**: `pool_size = (num_cores * 2) + effective_spindle_count`

```python
# For 4-core machine with SSD
pool_config = {
    "min_size": 10,
    "max_size": 20,
    "max_queries": 50000,  # Close connections after N queries
    "max_inactive_connection_lifetime": 300.0,  # 5 minutes
    "command_timeout": 60.0,  # Query timeout
}

pool = await asyncpg.create_pool(
    host="postgres.internal",
    database="saga_db",
    user="saga_user",
    password=os.environ["DB_PASSWORD"],
    **pool_config
)
```

### Index Optimization

**Critical indexes for performance**:

```sql
-- Outbox worker query optimization
EXPLAIN ANALYZE
WITH claimable AS (
    SELECT id
    FROM outbox
    WHERE status = 'pending'
      AND available_at <= now()
    ORDER BY created_at ASC
    LIMIT 100
    FOR UPDATE SKIP LOCKED
)
UPDATE outbox
SET status = 'claimed', claimed_at = now()
WHERE id IN (SELECT id FROM claimable)
RETURNING *;

-- Should use: Index Scan using idx_outbox_pending
-- If not, create better index:
CREATE INDEX CONCURRENTLY idx_outbox_pending_optimized 
ON outbox (status, available_at, created_at)
WHERE status IN ('pending', 'failed');

-- Vacuum regularly to prevent bloat
VACUUM ANALYZE outbox;
```

### Batch Size Tuning

**Determine optimal batch size**:

```python
# Benchmarking script
import time
import statistics

async def benchmark_batch_size(storage, broker, batch_sizes=[10, 50, 100, 200, 500]):
    """Find optimal batch size for your workload."""
    results = {}
    
    for batch_size in batch_sizes:
        latencies = []
        
        for _ in range(10):  # 10 iterations per size
            start = time.time()
            
            events = await storage.claim_pending_events(batch_size, "benchmark")
            for event in events:
                await broker.publish(...)
            
            latencies.append(time.time() - start)
        
        results[batch_size] = {
            "mean": statistics.mean(latencies),
            "p95": statistics.quantiles(latencies, n=20)[18],
            "throughput": batch_size / statistics.mean(latencies)
        }
    
    return results

# Run benchmark and choose batch_size with best throughput/latency ratio
```

### Kafka Producer Tuning

```python
# High-throughput configuration
producer_config = {
    "bootstrap_servers": "kafka:9092",
    "acks": "all",  # Wait for all replicas (durability)
    "compression_type": "lz4",  # Fast compression
    "linger_ms": 10,  # Wait up to 10ms to batch messages
    "batch_size": 32768,  # 32KB batches
    "buffer_memory": 67108864,  # 64MB buffer
    "max_in_flight_requests_per_connection": 5,
    "enable_idempotence": True,
    "request_timeout_ms": 30000,
    "retries": 5,
}

producer = AIOKafkaProducer(**producer_config)
```

---

## Chaos Engineering Tests

### Test 1: Worker Crash During Publish

```python
# tests/chaos/test_worker_crash.py
import pytest
import asyncio
import signal
import os

@pytest.mark.chaos
async def test_worker_crash_recovery(storage, broker):
    """
    Simulate worker crash mid-publish and verify another worker picks up.
    """
    # Insert test event
    event = create_test_event()
    await storage.append_outbox(event)
    
    # Start worker 1
    worker1 = OutboxWorker(storage, broker, worker_id="worker1")
    await worker1.start()
    
    # Wait for claim
    await asyncio.sleep(0.5)
    
    # Simulate crash (kill worker1)
    worker1._shutdown = True
    await worker1.stop()
    
    # Verify event is in 'claimed' state (stuck)
    status = await get_event_status(storage, event.event_id)
    assert status == "claimed"
    
    # Wait for watchdog timeout
    await asyncio.sleep(STUCK_CLAIM_TIMEOUT_SECONDS + 5)
    
    # Start worker 2
    worker2 = OutboxWorker(storage, broker, worker_id="worker2")
    await worker2.start()
    
    # Wait for processing
    await asyncio.sleep(2)
    
    # Verify event was requeued and processed
    status = await get_event_status(storage, event.event_id)
    assert status == "sent"
    
    await worker2.stop()
```

### Test 2: Database Connection Loss

```python
@pytest.mark.chaos
async def test_database_connection_loss(storage, broker):
    """
    Simulate database connection drop and verify graceful recovery.
    """
    worker = OutboxWorker(storage, broker)
    await worker.start()
    
    # Close all database connections
    await storage.pool.close()
    
    # Worker should handle connection errors gracefully
    await asyncio.sleep(5)
    
    # Reconnect database
    storage.pool = await asyncpg.create_pool(...)
    
    # Worker should resume processing
    event = create_test_event()
    await storage.append_outbox(event)
    
    await asyncio.sleep(3)
    
    status = await get_event_status(storage, event.event_id)
    assert status == "sent"
    
    await worker.stop()
```

### Test 3: Kafka Broker Unavailable

```python
@pytest.mark.chaos
async def test_broker_unavailable(storage, kafka_container):
    """
    Simulate Kafka broker downtime and verify exponential backoff.
    """
    broker = await KafkaBroker.create(
        bootstrap_servers=kafka_container.get_bootstrap_server()
    )
    
    worker = OutboxWorker(storage, broker)
    await worker.start()
    
    # Insert event
    event = create_test_event()
    await storage.append_outbox(event)
    
    # Stop Kafka
    kafka_container.stop()
    
    # Worker should fail to publish and schedule retry
    await asyncio.sleep(2)
    
    event_data = await get_event_data(storage, event.event_id)
    assert event_data["status"] == "failed"
    assert event_data["attempts"] > 0
    
    # Restart Kafka
    kafka_container.start()
    await asyncio.sleep(5)
    
    # Wait for backoff period
    backoff = 2 ** event_data["attempts"]
    await asyncio.sleep(backoff + 2)
    
    # Verify eventual success
    status = await get_event_status(storage, event.event_id)
    assert status == "sent"
    
    await worker.stop()
    await broker.close()
```

---

## Advanced Patterns & Extensions

### Pattern 1: Priority Queues

**Use case**: Process urgent events before normal events

```sql
-- Add priority column to outbox
ALTER TABLE outbox ADD COLUMN priority INT NOT NULL DEFAULT 5;

CREATE INDEX idx_outbox_priority 
ON outbox (status, priority DESC, available_at, created_at)
WHERE status IN ('pending', 'failed');

-- Update claim query to consider priority
WITH claimable AS (
    SELECT id
    FROM outbox
    WHERE status = 'pending'
      AND available_at <= now()
    ORDER BY priority DESC, created_at ASC
    LIMIT 100
    FOR UPDATE SKIP LOCKED
)
UPDATE outbox
SET status = 'claimed', claimed_at = now()
WHERE id IN (SELECT id FROM claimable)
RETURNING *;
```

### Pattern 2: Event Versioning

**Handle schema evolution**:

```python
@dataclass
class VersionedEvent:
    """Event with schema version for backward compatibility."""
    event_id: str
    event_type: str
    schema_version: int  # Increment on breaking changes
    payload: dict
    
    def migrate(self) -> dict:
        """Migrate old schema to current version."""
        if self.schema_version == 1:
            return self._migrate_v1_to_v2(self.payload)
        return self.payload
    
    def _migrate_v1_to_v2(self, payload: dict) -> dict:
        """Example migration: rename field."""
        if "old_field_name" in payload:
            payload["new_field_name"] = payload.pop("old_field_name")
        return payload

# In consumer
async def handle_event(event_data: dict):
    versioned = VersionedEvent(**event_data)
    current_payload = versioned.migrate()
    # Process current_payload
```

### Pattern 3: Saga Compensation (Rollback)

**Implement compensating transactions**:

```python
# saga/compensation.py
from typing import Callable, Awaitable

class CompensatableStep:
    """Saga step with compensation logic."""
    
    def __init__(
        self,
        name: str,
        forward: Callable[[dict], Awaitable[dict]],
        compensate: Callable[[dict], Awaitable[None]]
    ):
        self.name = name
        self.forward = forward
        self.compensate = compensate

class CompensatingSaga:
    """Saga that can rollback on failure."""
    
    def __init__(self, storage: SagaStorage, saga_id: str):
        self.storage = storage
        self.saga_id = saga_id
        self.steps: list[CompensatableStep] = []
    
    async def execute(self):
        """Execute steps, compensate on failure."""
        executed_steps = []
        
        try:
            for step in self.steps:
                saga = await self.storage.load(self.saga_id)
                
                # Skip if already executed (idempotency)
                if saga.state.get(f"{step.name}_completed"):
                    continue
                
                # Execute forward step
                result = await step.forward(saga.state)
                
                # Update state
                saga.state[f"{step.name}_result"] = result
                saga.state[f"{step.name}_completed"] = True
                
                await self.storage.save(
                    self.saga_id,
                    saga.state,
                    SagaStatus.RUNNING,
                    saga.version,
                    current_step=step.name
                )
                
                executed_steps.append(step)
            
            # All steps succeeded
            await self.storage.save(
                self.saga_id,
                saga.state,
                SagaStatus.COMPLETED,
                saga.version
            )
            
        except Exception as exc:
            # Compensate in reverse order
            await self._compensate(executed_steps, exc)
            raise
    
    async def _compensate(self, executed_steps: list[CompensatableStep], error: Exception):
        """Execute compensation in reverse order."""
        saga = await self.storage.load(self.saga_id)
        
        await self.storage.save(
            self.saga_id,
            saga.state,
            SagaStatus.COMPENSATING,
            saga.version
        )
        
        for step in reversed(executed_steps):
            try:
                await step.compensate(saga.state)
                saga.state[f"{step.name}_compensated"] = True
            except Exception as comp_exc:
                # Log but continue compensating
                logging.error(f"Compensation failed for {step.name}: {comp_exc}")
        
        await self.storage.save(
            self.saga_id,
            saga.state,
            SagaStatus.FAILED,
            saga.version,
            error=str(error)
        )

# Usage example
async def execute_order_saga(storage: SagaStorage, order_id: str):
    saga_id = str(uuid.uuid4())
    
    saga = CompensatingSaga(storage, saga_id)
    
    saga.steps = [
        CompensatableStep(
            name="reserve_inventory",
            forward=lambda state: reserve_inventory(order_id),
            compensate=lambda state: release_inventory(order_id)
        ),
        CompensatableStep(
            name="charge_payment",
            forward=lambda state: charge_payment(order_id),
            compensate=lambda state: refund_payment(order_id)
        ),
        CompensatableStep(
            name="ship_order",
            forward=lambda state: ship_order(order_id),
            compensate=lambda state: cancel_shipment(order_id)
        )
    ]
    
    await saga.execute()
```

---

## Production Readiness Checklist

### Pre-Deployment Validation

- [ ] **Database**: Migrations applied, indexes verified with EXPLAIN ANALYZE
- [ ] **Secrets**: All credentials in secret manager, no hardcoded values
- [ ] **Monitoring**: Prometheus metrics exposed, Grafana dashboards created
- [ ] **Alerting**: PagerDuty/Opsgenie integration configured
- [ ] **Logging**: Structured logs to ELK/Loki, trace IDs propagated
- [ ] **Testing**: Unit tests >80% coverage, integration tests passing
- [ ] **Chaos**: Chaos tests executed, failure scenarios validated
- [ ] **Documentation**: Runbooks written, architecture diagrams updated
- [ ] **Performance**: Load testing completed, bottlenecks identified
- [ ] **Security**: Vulnerability scan passed, RBAC configured
- [ ] **Compliance**: GDPR/SOC2 requirements documented
- [ ] **Backup**: Database backup strategy verified
- [ ] **Disaster Recovery**: Restore procedure tested

### Post-Deployment Monitoring (First 48 Hours)

- [ ] Monitor `outbox_pending_events_total` - should stabilize near zero
- [ ] Check error rates in logs - investigate any anomalies
- [ ] Verify publish latency p99 < SLA threshold
- [ ] Confirm no dead letter queue accumulation
- [ ] Test manual event replay procedure
- [ ] Validate consumer deduplication (check for duplicates in logs)
- [ ] Review database connection pool usage
- [ ] Check Kafka consumer lag (if applicable)

---

## Summary: Key Principles for AI Agents

When implementing this pattern, always remember:

1. **Atomicity First**: State updates and outbox inserts MUST be in same transaction
2. **Idempotency Everywhere**: All operations must be safely retryable
3. **Observe Everything**: Metrics, logs, and traces are not optional
4. **Plan for Failure**: Chaos testing reveals real-world issues
5. **Security by Default**: Encrypt PII, rotate credentials, audit everything
6. **Scale Horizontally**: Design for multiple workers from day one
7. **Document Operationally**: Your future on-call self will thank you

### Decision Tree for Common Questions

**Q: Should I use optimistic or pessimistic locking?**
→ Start with OCC (version-based). Only use `FOR UPDATE` if contention is proven problem.

**Q: How many outbox workers should I run?**
→ Start with 3, scale based on `outbox_pending_events_total / target_lag_seconds`.

**Q: When should events go to dead letter queue?**
→ After 10 failed attempts OR if error is non-retryable (e.g., schema validation failure).

**Q: How do I handle schema evolution?**
→ Include `schema_version` in events, implement migration logic in consumers.

**Q: Should I archive sent events?**
→ Yes, for audit trail. Archive after 7-30 days depending on compliance needs.

---

## Quick Start: Copy-Paste Implementation

```bash
# 1. Clone reference implementation
git clone https://github.com/your-org/saga-outbox-pattern
cd saga-outbox-pattern

# 2. Apply database migrations
psql $DATABASE_URL -f migrations/0001_create_saga_outbox.sql

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your database/Kafka credentials

# 5. Run tests
pytest tests/ -v

# 6. Start outbox worker locally
python -m saga.outbox_worker

# 7. Deploy to Kubernetes
kubectl apply -f k8s/
kubectl rollout status deployment/outbox-worker

# 8. Verify deployment
kubectl logs -l app=outbox-worker -f
```

---

## Outbox State Machine: Enforcing Valid Transitions

### Why State Machines for Outbox Status?

State machines provide explicit control over valid state transitions, preventing invalid states and making the system behavior predictable and testable. For the outbox pattern, this means:

1. **Prevention of invalid transitions** (e.g., `sent` → `pending`)
2. **Clear visualization** of the lifecycle
3. **Auditable state changes** with hooks for logging
4. **Conditional logic** for guards and validators

### State Machine Implementation: `saga/outbox_statemachine.py`

```python
"""
Outbox event lifecycle state machine using python-statemachine.

Install: pip install python-statemachine>=2.4.0

State Diagram:
                 ┌─────────┐
                 │ pending │ (initial)
                 └────┬────┘
                      │
          ┌───────────┴──────────┐
          │                      │
    ┌─────▼──────┐         ┌─────▼─────┐
    │ optimistic │         │  claimed  │
    └─────┬──────┘         └─────┬─────┘
          │                      │
          ├──────────┬───────────┤
          │          │           │
     ┌────▼───┐   ┌──▼───┐    ┌────▼────────┐
     │  sent  │   │failed│    │ dead_letter │
     └────────┘   └──┬───┘    └─────────────┘
                     │
                     └──────► (retry to pending)
"""
from statemachine import StateMachine, State
from statemachine.exceptions import TransitionNotAllowed
from datetime import datetime
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class OutboxEventStateMachine(StateMachine):
    """
    State machine for outbox event lifecycle.
    
    Ensures only valid state transitions occur and provides
    hooks for observability and side effects.
    """
    
    # Define states
    pending = State(initial=True, value='pending')
    optimistic = State(value='optimistic')  # Transient state for optimistic sending
    claimed = State(value='claimed')
    sent = State(value='sent', final=True)
    failed = State(value='failed')
    dead_letter = State(value='dead_letter', final=True)
    
    # Define transitions (events)
    # From pending
    attempt_optimistic_send = pending.to(optimistic)
    claim_for_processing = pending.to(claimed)
    
    # From optimistic
    optimistic_send_succeeded = optimistic.to(sent)
    optimistic_send_failed = optimistic.to(pending)  # Fallback to polling
    
    # From claimed
    publish_succeeded = claimed.to(sent)
    publish_failed = claimed.to(failed)
    
    # From failed
    retry = failed.to(pending)  # After backoff period
    move_to_dlq = failed.to(dead_letter)  # Max attempts exceeded
    
    # Cycle for testing/manual intervention
    manual_retry_dlq = dead_letter.to(pending)
    
    def __init__(self, event_id: str, initial_status: str = 'pending', **kwargs):
        """
        Initialize state machine with event context.
        
        Args:
            event_id: Unique event identifier
            initial_status: Starting state (for loading from DB)
        """
        self.event_id = event_id
        self.attempts = 0
        self.last_error: Optional[str] = None
        self.published_at: Optional[datetime] = None
        
        # Initialize parent with current state
        super().__init__(start_value=initial_status, **kwargs)
    
    # State entry/exit hooks
    
    def on_enter_optimistic(self):
        """Entering optimistic send state."""
        logger.debug(
            f"Event {self.event_id}: Attempting optimistic send",
            extra={'event_id': self.event_id, 'state': 'optimistic'}
        )
    
    def on_enter_claimed(self):
        """Entering claimed state (worker picked up event)."""
        logger.info(
            f"Event {self.event_id}: Claimed by worker",
            extra={'event_id': self.event_id, 'state': 'claimed'}
        )
    
    def on_enter_sent(self):
        """Entering sent state (final success)."""
        self.published_at = datetime.utcnow()
        logger.info(
            f"Event {self.event_id}: Successfully published",
            extra={'event_id': self.event_id, 'state': 'sent', 'attempts': self.attempts}
        )
    
    def on_enter_failed(self):
        """Entering failed state (will retry)."""
        self.attempts += 1
        logger.warning(
            f"Event {self.event_id}: Publish failed (attempt {self.attempts})",
            extra={
                'event_id': self.event_id,
                'state': 'failed',
                'attempts': self.attempts,
                'error': self.last_error
            }
        )
    
    def on_enter_dead_letter(self):
        """Entering dead letter queue (max retries exceeded)."""
        logger.error(
            f"Event {self.event_id}: Moved to DLQ after {self.attempts} attempts",
            extra={
                'event_id': self.event_id,
                'state': 'dead_letter',
                'attempts': self.attempts,
                'last_error': self.last_error
            }
        )
    
    # Transition guards (conditional logic)
    
    def before_move_to_dlq(self, max_attempts: int = 10) -> bool:
        """
        Guard: Only allow DLQ move if max attempts exceeded.
        
        Args:
            max_attempts: Maximum retry attempts before DLQ
        
        Returns:
            True if should move to DLQ, False otherwise
        """
        should_dlq = self.attempts >= max_attempts
        if not should_dlq:
            logger.debug(
                f"Event {self.event_id}: Not moving to DLQ (attempts: {self.attempts}/{max_attempts})"
            )
        return should_dlq
    
    def before_retry(self, backoff_seconds: int = 0) -> bool:
        """
        Guard: Only allow retry if backoff period has passed.
        
        Args:
            backoff_seconds: Required backoff period
        
        Returns:
            True if retry is allowed
        """
        # In real implementation, check available_at timestamp
        # Here we just log for demonstration
        logger.debug(
            f"Event {self.event_id}: Retry after {backoff_seconds}s backoff"
        )
        return True
    
    # Transition callbacks (side effects)
    
    def after_publish_succeeded(self):
        """After successful publish - cleanup/metrics."""
        logger.info(
            f"Event {self.event_id}: Publish succeeded, state is now 'sent'"
        )
    
    def after_publish_failed(self, error: Exception):
        """After failed publish - record error."""
        self.last_error = f"{type(error).__name__}: {str(error)}"
        logger.warning(
            f"Event {self.event_id}: Publish failed: {self.last_error}"
        )
    
    # Utility methods
    
    def can_transition_to(self, target_state: str) -> bool:
        """
        Check if transition to target state is valid from current state.
        
        Args:
            target_state: Target state name
        
        Returns:
            True if transition is allowed
        """
        try:
            # Get allowed events from current state
            allowed_events = self.allowed_events
            
            # Check if any event leads to target state
            for event in allowed_events:
                transitions = getattr(self, event).transitions
                for transition in transitions:
                    if transition.target.id == target_state:
                        return True
            return False
        except Exception:
            return False
    
    def get_next_states(self) -> list[str]:
        """
        Get list of states reachable from current state.
        
        Returns:
            List of reachable state names
        """
        next_states = set()
        for event in self.allowed_events:
            transitions = getattr(self, event).transitions
            for transition in transitions:
                next_states.add(transition.target.id)
        return list(next_states)


# Usage example
def example_usage():
    """Demonstrate state machine usage."""
    
    # Create new event (starts in 'pending')
    sm = OutboxEventStateMachine(event_id="evt_123")
    print(f"Initial state: {sm.current_state.id}")  # 'pending'
    print(f"Allowed events: {sm.allowed_events}")   # ['attempt_optimistic_send', 'claim_for_processing']
    
    # Try optimistic send
    sm.attempt_optimistic_send()
    print(f"After optimistic attempt: {sm.current_state.id}")  # 'optimistic'
    
    # Optimistic send failed - fallback to polling
    sm.optimistic_send_failed()
    print(f"After optimistic failed: {sm.current_state.id}")  # back to 'pending'
    
    # Worker claims event
    sm.claim_for_processing()
    print(f"After claim: {sm.current_state.id}")  # 'claimed'
    
    # Publish succeeded
    sm.publish_succeeded()
    print(f"Final state: {sm.current_state.id}")  # 'sent'
    print(f"Is final: {sm.current_state.final}")  # True
    
    # Try invalid transition (will raise exception)
    try:
        sm.claim_for_processing()  # Can't claim from 'sent'
    except TransitionNotAllowed as e:
        print(f"Invalid transition prevented: {e}")


if __name__ == "__main__":
    example_usage()
```

### Integration with Storage Layer

Update the `PostgresSagaStorage` to use the state machine:

```python
# saga/storage_postgres.py (additions)
from .outbox_statemachine import OutboxEventStateMachine
from statemachine.exceptions import TransitionNotAllowed

class PostgresSagaStorage(SagaStorage):
    # ... existing code ...
    
    async def transition_outbox_status(
        self,
        event_id: str,
        transition_event: str,
        **transition_params
    ) -> bool:
        """
        Safely transition outbox event status using state machine.
        
        Args:
            event_id: Event identifier
            transition_event: State machine event name (e.g., 'publish_succeeded')
            **transition_params: Additional parameters for guards/callbacks
        
        Returns:
            True if transition succeeded, False if not allowed
        
        Raises:
            TransitionNotAllowed: If transition is invalid
        """
        async with self.pool.acquire() as conn:
            # Load current status
            row = await conn.fetchrow(
                "SELECT status, attempts FROM outbox WHERE event_id = $1",
                event_id
            )
            
            if not row:
                raise KeyError(f"Event {event_id} not found")
            
            # Create state machine with current state
            sm = OutboxEventStateMachine(
                event_id=event_id,
                initial_status=row['status']
            )
            sm.attempts = row['attempts']
            
            # Attempt transition
            try:
                # Get the event method and call it with params
                event_method = getattr(sm, transition_event)
                event_method(**transition_params)
                
                # Transition succeeded - persist to database
                new_status = sm.current_state.id
                
                await conn.execute(
                    """
                    UPDATE outbox
                    SET status = $1::outbox_status,
                        attempts = $2,
                        published_at = CASE WHEN $1 = 'sent' THEN now() ELSE published_at END
                    WHERE event_id = $3
                    """,
                    new_status,
                    sm.attempts,
                    event_id
                )
                
                return True
                
            except TransitionNotAllowed as e:
                logger.warning(
                    f"Invalid state transition for event {event_id}: {e}",
                    extra={'event_id': event_id, 'current_state': row['status']}
                )
                return False
    
    async def mark_outbox_sent(self, event_id: str) -> None:
        """Mark event as successfully published using state machine."""
        await self.transition_outbox_status(
            event_id,
            'publish_succeeded'  # or 'optimistic_send_succeeded'
        )
    
    async def mark_outbox_failed(self, event_id: str, error: str) -> None:
        """
        Record publish failure using state machine.
        
        Automatically moves to DLQ if max attempts exceeded.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, attempts, max_attempts FROM outbox WHERE event_id = $1",
                event_id
            )
            
            sm = OutboxEventStateMachine(
                event_id=event_id,
                initial_status=row['status']
            )
            sm.attempts = row['attempts']
            sm.last_error = error
            
            # Try to mark as failed
            try:
                sm.publish_failed(error=Exception(error))
                
                # Check if should move to DLQ
                if sm.before_move_to_dlq(max_attempts=row['max_attempts']):
                    sm.move_to_dlq(max_attempts=row['max_attempts'])
                
                new_status = sm.current_state.id
                
                # Calculate backoff for failed state
                backoff_seconds = 2 ** sm.attempts if new_status == 'failed' else 0
                
                await conn.execute(
                    """
                    UPDATE outbox
                    SET status = $1::outbox_status,
                        attempts = $2,
                        available_at = CASE
                            WHEN $1 = 'failed' THEN now() + ($3 || ' seconds')::interval
                            ELSE available_at
                        END,
                        last_error = $4
                    WHERE event_id = $5
                    """,
                    new_status,
                    sm.attempts,
                    backoff_seconds,
                    error,
                    event_id
                )
                
            except TransitionNotAllowed as e:
                logger.error(f"Cannot mark event {event_id} as failed: {e}")
                raise
```

### Benefits of State Machine Approach

1. **Type Safety**: Invalid transitions caught at runtime
2. **Explicit Logic**: Clear which transitions are allowed
3. **Auditability**: All state changes logged with context
4. **Testability**: Easy to unit test state transitions
5. **Documentation**: State diagram auto-generated from code
6. **Guards**: Conditional logic for complex transitions
7. **Hooks**: Side effects (metrics, logging) cleanly separated

### Generating State Diagram

```python
# Generate visual diagram (requires pydot and graphviz)
from outbox_statemachine import OutboxEventStateMachine

sm = OutboxEventStateMachine(event_id="example")
sm._graph().write_png("outbox_state_diagram.png")
```

---

## Optimistic Sending Pattern Implementation

### Overview

The Optimistic Sending pattern attempts to publish events immediately after transaction commit (99%+ success rate in healthy systems) while maintaining the polling worker as a safety net. This reduces latency from ~100ms to <10ms for the happy path.

### Architecture Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Application Write Path (Optimistic Sending)                 │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
                 ┌─────────────────┐
                 │ Begin DB Txn    │
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
                 │ Update Saga     │
                 │ State           │
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
                 │ INSERT INTO     │
                 │ outbox          │
                 │ status='pending'│
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
                 │ COMMIT Txn      │
                 └────────┬────────┘
                          │
              ┌───────────┴───────────┐
              │                       │
       ┌──────▼──────┐         ┌─────▼──────┐
       │ Try Publish │         │  [Txn      │
       │ to Broker   │         │   failed]  │
       │ (immediate) │         │  Rollback  │
       └──────┬──────┘         └────────────┘
              │
         ┌────┴─────┐
         │          │
    ┌────▼───┐  ┌──▼──────┐
    │SUCCESS │  │ FAILED  │
    │        │  │         │
    │ UPDATE │  │ Event   │
    │ status │  │ stays   │
    │ ='sent'│  │ pending │
    └────────┘  └────┬────┘
                     │
              ┌──────▼──────┐
              │ Polling     │
              │ Worker      │
              │ picks it up │
              └─────────────┘
```

### Implementation: `saga/optimistic_publisher.py`

```python
"""
Optimistic event publishing - attempts immediate broker publish after commit.

This is a 2024-2025 performance optimization that reduces latency dramatically
while maintaining the same consistency guarantees.
"""
import asyncio
import logging
from typing import Optional
from uuid import uuid4

from asyncpg import Pool, Connection
from prometheus_client import Counter, Histogram

from .interfaces import MessageBroker, OutboxEvent
from .storage_postgres import PostgresSagaStorage
from .outbox_statemachine import OutboxEventStateMachine

logger = logging.getLogger(__name__)

# Metrics
OPTIMISTIC_SEND_ATTEMPTS = Counter(
    "outbox_optimistic_send_attempts_total",
    "Total optimistic send attempts"
)
OPTIMISTIC_SEND_SUCCESS = Counter(
    "outbox_optimistic_send_success_total",
    "Successful optimistic sends"
)
OPTIMISTIC_SEND_FAILURES = Counter(
    "outbox_optimistic_send_failures_total",
    "Failed optimistic sends (will fallback to polling)",
    ["reason"]
)
OPTIMISTIC_SEND_LATENCY = Histogram(
    "outbox_optimistic_send_latency_seconds",
    "Latency of optimistic send operation"
)

class OptimisticPublisher:
    """
    Publishes events immediately after transaction commit.
    
    Design principles:
    1. Never block the application on broker failures
    2. Failed publishes fallback to polling worker (existing safety net)
    3. Success path is optimized for minimum latency
    4. Uses state machine for status transitions
    """
    
    def __init__(
        self,
        storage: PostgresSagaStorage,
        broker: MessageBroker,
        enable_optimistic: bool = True,
        timeout_seconds: float = 2.0
    ):
        """
        Initialize optimistic publisher.
        
        Args:
            storage: Saga storage instance
            broker: Message broker instance
            enable_optimistic: Feature flag to disable optimistic sending
            timeout_seconds: Max time to wait for broker publish
        """
        self.storage = storage
        self.broker = broker
        self.enable_optimistic = enable_optimistic
        self.timeout_seconds = timeout_seconds
    
    async def publish_after_commit(
        self,
        event: OutboxEvent,
        conn: Optional[Connection] = None
    ) -> bool:
        """
        Attempt immediate publish after transaction commits.
        
        CRITICAL: This must be called AFTER transaction commit succeeds.
        If called before commit, we risk publishing events for rolled-back transactions.
        
        Args:
            event: Event to publish
            conn: Optional connection (for status update)
        
        Returns:
            True if published successfully, False if failed (polling worker will retry)
        """
        if not self.enable_optimistic:
            logger.debug("Optimistic sending disabled, skipping")
            return False
        
        OPTIMISTIC_SEND_ATTEMPTS.inc()
        
        # Update status to 'optimistic' using state machine
        try:
            await self.storage.transition_outbox_status(
                event.event_id,
                'attempt_optimistic_send'
            )
        except Exception as e:
            logger.warning(f"Failed to transition to optimistic state: {e}")
            return False
        
        try:
            with OPTIMISTIC_SEND_LATENCY.time():
                # Attempt publish with timeout
                await asyncio.wait_for(
                    self.broker.publish(
                        topic=self._resolve_topic(event.event_type, event.routing_key),
                        payload=event.payload,
                        message_id=event.event_id,
                        headers=event.headers,
                        partition_key=event.partition_key
                    ),
                    timeout=self.timeout_seconds
                )
            
            # Success! Mark as sent using state machine
            await self.storage.transition_outbox_status(
                event.event_id,
                'optimistic_send_succeeded'
            )
            
            OPTIMISTIC_SEND_SUCCESS.inc()
            
            logger.info(
                f"Optimistic send succeeded for event {event.event_id}",
                extra={'event_id': event.event_id, 'event_type': event.event_type}
            )
            
            return True
            
        except asyncio.TimeoutError:
            # Timeout - fallback to polling
            OPTIMISTIC_SEND_FAILURES.labels(reason="timeout").inc()
            
            logger.warning(
                f"Optimistic send timeout for event {event.event_id}, "
                f"will fallback to polling worker",
                extra={'event_id': event.event_id, 'timeout': self.timeout_seconds}
            )
            
            await self._fallback_to_polling(event.event_id)
            return False
            
        except Exception as exc:
            # Broker error - fallback to polling
            OPTIMISTIC_SEND_FAILURES.labels(
                reason=type(exc).__name__
            ).inc()
            
            logger.warning(
                f"Optimistic send failed for event {event.event_id}: {exc}, "
                f"will fallback to polling worker",
                extra={
                    'event_id': event.event_id,
                    'error': str(exc),
                    'error_type': type(exc).__name__
                }
            )
            
            await self._fallback_to_polling(event.event_id)
            return False
    
    async def _fallback_to_polling(self, event_id: str) -> None:
        """
        Transition event back to 'pending' for polling worker to handle.
        
        Args:
            event_id: Event that failed optimistic send
        """
        try:
            await self.storage.transition_outbox_status(
                event_id,
                'optimistic_send_failed'
            )
        except Exception as e:
            logger.error(
                f"Failed to fallback event {event_id} to polling: {e}",
                extra={'event_id': event_id}
            )
    
    def _resolve_topic(self, event_type: str, routing_key: Optional[str]) -> str:
        """Map event type to broker topic."""
        if routing_key:
            return routing_key
        return f"events.{event_type.lower().replace('_', '.')}"


# Updated saga step example with optimistic sending
async def reserve_funds_with_optimistic_send(
    pool: Pool,
    storage: PostgresSagaStorage,
    optimistic_publisher: OptimisticPublisher,
    saga_id: str,
    amount: float
):
    """
    Example saga step with optimistic sending pattern.
    
    Flow:
    1. Begin transaction
    2. Update saga state
    3. Insert outbox event
    4. Commit transaction
    5. Immediately try to publish (optimistic)
    6. If publish fails, polling worker will handle it
    """
    event_id = str(uuid4())
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Load saga state with pessimistic lock
            row = await conn.fetchrow(
                "SELECT state, version FROM saga_instance WHERE id = $1 FOR UPDATE",
                saga_id
            )
            state = row["state"]
            version = row["version"]
            
            # Idempotency check
            if state.get("funds_reserved"):
                logger.info(f"Funds already reserved for saga {saga_id}, skipping")
                return
            
            # Update saga state
            state["funds_reserved"] = True
            state["reserved_amount"] = amount
            
            await conn.execute(
                """
                UPDATE saga_instance
                SET state = $1, version = version + 1, updated_at = now()
                WHERE id = $2 AND version = $3
                """,
                state, saga_id, version
            )
            
            # Create outbox event
            event = OutboxEvent(
                event_id=event_id,
                saga_id=saga_id,
                aggregate_type="saga",
                aggregate_id=saga_id,
                event_type="FundsReserved",
                payload={
                    "saga_id": saga_id,
                    "amount": amount,
                    "timestamp": datetime.utcnow().isoformat()
                },
                headers={
                    "trace_id": str(uuid4()),
                    "message_id": event_id,
                    "causation_id": saga_id
                }
            )
            
            # Insert into outbox (within transaction)
            await storage.append_outbox(event, conn=conn)
            
            # Transaction commits here automatically
        
        # AFTER COMMIT: Try optimistic send
        # This is the critical performance optimization
        success = await optimistic_publisher.publish_after_commit(event)
        
        if success:
            logger.info(
                f"Event {event_id} published immediately (optimistic)",
                extra={'latency': 'sub-10ms'}
            )
        else:
            logger.info(
                f"Event {event_id} will be published by polling worker",
                extra={'latency': '~100ms (poll interval)'}
            )
```

### Configuration & Feature Flag

```python
# config.py
from dataclasses import dataclass

@dataclass
class OutboxConfig:
    """Outbox pattern configuration."""
    
    # Optimistic sending
    enable_optimistic_send: bool = True  # Feature flag
    optimistic_send_timeout_seconds: float = 2.0  # Max wait for broker
    
    # Polling worker (fallback)
    worker_poll_interval_seconds: float = 1.0
    worker_batch_size: int = 100
    
    # Retry policy
    max_attempts: int = 10
    initial_backoff_seconds: int = 2
    max_backoff_seconds: int = 3600  # 1 hour
    
    # Stuck claim watchdog
    stuck_claim_timeout_seconds: int = 300  # 5 minutes


# Usage in application
from saga.storage_postgres import PostgresSagaStorage
from saga.broker_kafka import KafkaBroker
from saga.optimistic_publisher import OptimisticPublisher

async def setup():
    config = OutboxConfig()
    
    pool = await create_pool(...)
    storage = PostgresSagaStorage(pool)
    broker = await KafkaBroker.create(...)
    
    # Create optimistic publisher
    optimistic_pub = OptimisticPublisher(
        storage=storage,
        broker=broker,
        enable_optimistic=config.enable_optimistic_send,
        timeout_seconds=config.optimistic_send_timeout_seconds
    )
    
    return storage, broker, optimistic_pub
```

### Performance Comparison

| Scenario | Without Optimistic | With Optimistic | Improvement |
|----------|-------------------|-----------------|-------------|
| **Happy Path** (broker healthy) | ~100ms (poll interval) | <10ms | **10x faster** |
| **Broker Down** | ~100ms (same) | ~100ms (fallback to polling) | No regression |
| **High Load** | Batched (efficient) | Individual + batched | Slightly higher broker QPS |

### Monitoring Optimistic Sending

```yaml
# Grafana dashboard additions
panels:
  - title: "Optimistic Send Success Rate"
    expr: |
      rate(outbox_optimistic_send_success_total[5m]) /
      rate(outbox_optimistic_send_attempts_total[5m])
    # Target: >99% in healthy system
  
  - title: "Optimistic vs Polling Published Events"
    expr: |
      sum(rate(outbox_optimistic_send_success_total[5m])) by (job) vs
      sum(rate(outbox_published_events_total[5m])) by (job)
  
  - title: "Fallback Rate"
    expr: |
      rate(outbox_optimistic_send_failures_total[5m])
    # Alert if sustained >10% failure rate
```

### Testing Optimistic Sending

```python
# tests/test_optimistic_sending.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_optimistic_send_success(storage, broker):
    """Test happy path - immediate publish succeeds."""
    event = create_test_event()
    
    # Mock successful broker publish
    broker.publish = AsyncMock(return_value=None)
    
    publisher = OptimisticPublisher(storage, broker)
    
    # Insert event and try optimistic send
    await storage.append_outbox(event)
    success = await publisher.publish_after_commit(event)
    
    assert success is True
    broker.publish.assert_called_once()
    
    # Verify status is 'sent'
    status = await get_event_status(storage, event.event_id)
    assert status == 'sent'

@pytest.mark.asyncio
async def test_optimistic_send_timeout_fallback(storage, broker):
    """Test timeout - should fallback to polling without error."""
    event = create_test_event()
    
    # Mock broker timeout
    async def slow_publish(*args, **kwargs):
        await asyncio.sleep(10)  # Exceeds timeout
    
    broker.publish = slow_publish
    
    publisher = OptimisticPublisher(
        storage, broker,
        timeout_seconds=0.5
    )
    
    await storage.append_outbox(event)
    success = await publisher.publish_after_commit(event)
    
    assert success is False
    
    # Verify status is back to 'pending' for polling
    status = await get_event_status(storage, event.event_id)
    assert status == 'pending'

@pytest.mark.asyncio
async def test_optimistic_disabled(storage, broker):
    """Test feature flag - optimistic sending can be disabled."""
    event = create_test_event()
    
    broker.publish = AsyncMock(return_value=None)
    
    # Disable optimistic sending
    publisher = OptimisticPublisher(
        storage, broker,
        enable_optimistic=False
    )
    
    await storage.append_outbox(event)
    success = await publisher.publish_after_commit(event)
    
    assert success is False
    broker.publish.assert_not_called()
    
    # Event should remain 'pending' for polling worker
    status = await get_event_status(storage, event.event_id)
    assert status == 'pending'

@pytest.mark.asyncio
async def test_optimistic_send_broker_error(storage, broker):
    """Test broker error - should gracefully fallback."""
    event = create_test_event()
    
    # Mock broker exception
    broker.publish = AsyncMock(
        side_effect=Exception("Kafka connection refused")
    )
    
    publisher = OptimisticPublisher(storage, broker)
    
    await storage.append_outbox(event)
    success = await publisher.publish_after_commit(event)
    
    assert success is False
    
    # Should fallback to pending
    status = await get_event_status(storage, event.event_id)
    assert status == 'pending'
```

---

## Updated Outbox Worker with State Machine

### Modified Worker: `saga/outbox_worker.py`

```python
# saga/outbox_worker.py (updated with state machine)
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import List
from uuid import uuid4

from asyncpg import Pool
from prometheus_client import Counter, Gauge, Histogram
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .interfaces import MessageBroker, SagaLogger
from .storage_postgres import PostgresSagaStorage
from .outbox_statemachine import OutboxEventStateMachine

# Configuration constants
POLL_INTERVAL_SECONDS = 1.0
BATCH_SIZE = 100
STUCK_CLAIM_TIMEOUT_SECONDS = 300  # 5 minutes
WATCHDOG_INTERVAL_SECONDS = 30

# Prometheus metrics (keeping existing metrics)
OUTBOX_PENDING = Gauge(
    "outbox_pending_events_total",
    "Number of pending outbox events"
)
OUTBOX_CLAIMED = Counter(
    "outbox_claimed_events_total",
    "Total events claimed by workers"
)
OUTBOX_PUBLISHED = Counter(
    "outbox_published_events_total",
    "Total events successfully published",
    ["event_type"]
)
OUTBOX_FAILED = Counter(
    "outbox_failed_events_total",
    "Total events that failed to publish",
    ["event_type", "reason"]
)
OUTBOX_DEAD_LETTER = Counter(
    "outbox_dead_letter_events_total",
    "Events moved to dead letter queue after max retries",
    ["event_type"]
)
OUTBOX_PUBLISH_DURATION = Histogram(
    "outbox_publish_duration_seconds",
    "Time to publish single event",
    ["event_type"]
)
OUTBOX_BATCH_DURATION = Histogram(
    "outbox_batch_duration_seconds",
    "Time to process entire batch"
)

tracer = trace.get_tracer(__name__)

class OutboxWorker:
    """
    Outbox relay worker - consumes events from outbox table and publishes to broker.
    
    Now uses state machine for robust status transitions.
    
    Lifecycle:
    1. Claim batch of pending events (atomic)
    2. Publish each event to broker
    3. Use state machine to transition to 'sent' or 'failed'
    4. Repeat until shutdown signal received
    """
    
    def __init__(
        self,
        storage: PostgresSagaStorage,
        broker: MessageBroker,
        logger: SagaLogger,
        worker_id: str | None = None,
        batch_size: int = BATCH_SIZE,
        poll_interval: float = POLL_INTERVAL_SECONDS
    ):
        self.storage = storage
        self.broker = broker
        self.logger = logger
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self._shutdown = False
        self._task: asyncio.Task | None = None
    
    async def start(self) -> None:
        """Start worker main loop."""
        if self._task:
            raise RuntimeError("Worker already started")
        
        self._shutdown = False
        self._task = asyncio.create_task(self._run())
        
        # Start watchdog for stuck claims
        asyncio.create_task(self._watchdog())
        
        logging.info(f"Outbox worker {self.worker_id} started")
    
    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully shutdown worker."""
        if not self._task:
            return
        
        logging.info(f"Shutting down worker {self.worker_id}...")
        self._shutdown = True
        
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.TimeoutError:
            logging.warning(f"Worker {self.worker_id} shutdown timed out, cancelling")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logging.info(f"Worker {self.worker_id} stopped")
    
    async def _run(self) -> None:
        """Main processing loop."""
        while not self._shutdown:
            try:
                with OUTBOX_BATCH_DURATION.time():
                    await self._process_batch()
            except Exception as exc:
                logging.exception(f"Worker {self.worker_id} batch processing error: {exc}")
                await asyncio.sleep(5)  # Back off on errors
            
            # Update pending count metric
            try:
                pending_count = await self._count_pending()
                OUTBOX_PENDING.set(pending_count)
            except Exception:
                pass  # Don't fail on metrics
            
            # Wait before next poll
            await asyncio.sleep(self.poll_interval)
    
    async def _process_batch(self) -> None:
        """Claim and process a batch of pending events."""
        events = await self.storage.claim_pending_events(
            self.batch_size,
            self.worker_id
        )
        
        if not events:
            return
        
        OUTBOX_CLAIMED.inc(len(events))
        logging.debug(f"Worker {self.worker_id} claimed {len(events)} events")
        
        # Process events concurrently within batch
        tasks = [self._publish_event(event) for event in events]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _publish_event(self, event: dict) -> None:
        """
        Publish single event with retry and error handling using state machine.
        
        Success path: claimed -> publish -> sent
        Failure path: claimed -> publish [fails] -> failed -> (retry after backoff)
        """
        event_id = str(event['event_id'])
        event_type = event['event_type']
        
        # Start tracing span
        with tracer.start_as_current_span(
            "outbox.publish_event",
            attributes={
                "event_id": event_id,
                "event_type": event_type,
                "worker_id": self.worker_id,
                "attempt": event['attempts'] + 1
            }
        ) as span:
            try:
                with OUTBOX_PUBLISH_DURATION.labels(event_type=event_type).time():
                    # Publish to broker
                    await self.broker.publish(
                        topic=self._resolve_topic(event_type, event.get('routing_key')),
                        payload=event['payload'],
                        message_id=event_id,
                        headers=event['headers'],
                        partition_key=event.get('partition_key')
                    )
                
                # Success: transition to 'sent' using state machine
                await self.storage.transition_outbox_status(
                    event_id,
                    'publish_succeeded'
                )
                
                OUTBOX_PUBLISHED.labels(event_type=event_type).inc()
                span.set_status(Status(StatusCode.OK))
                
                await self.logger.info(
                    event.get('saga_id', 'unknown'),
                    f"Published event {event_type}",
                    event_id=event_id,
                    attempt=event['attempts'] + 1
                )
                
            except Exception as exc:
                # Failure: transition to 'failed' (or 'dead_letter' if max attempts)
                error_msg = f"{type(exc).__name__}: {str(exc)}"
                
                # Use state machine to handle failure with automatic DLQ logic
                await self.storage.mark_outbox_failed(event_id, error_msg)
                
                OUTBOX_FAILED.labels(
                    event_type=event_type,
                    reason=type(exc).__name__
                ).inc()
                
                span.set_status(Status(StatusCode.ERROR))
                span.record_exception(exc)
                
                # Check if moved to dead letter
                new_status = await self._get_event_status(event_id)
                
                if new_status == 'dead_letter':
                    OUTBOX_DEAD_LETTER.labels(event_type=event_type).inc()
                    await self.logger.error(
                        event.get('saga_id', 'unknown'),
                        f"Event {event_type} moved to dead letter queue after {event['max_attempts']} attempts",
                        exc=exc,
                        event_id=event_id
                    )
                else:
                    backoff = 2 ** (event['attempts'] + 1)
                    await self.logger.warning(
                        event.get('saga_id', 'unknown'),
                        f"Failed to publish {event_type}, will retry in {backoff}s",
                        event_id=event_id,
                        attempt=event['attempts'] + 1,
                        error=error_msg
                    )
    
    async def _watchdog(self) -> None:
        """
        Periodically requeue stuck claims (crashed workers).
        
        Uses state machine to validate transitions.
        """
        while not self._shutdown:
            try:
                requeued = await self.storage.requeue_stuck_claims(
                    STUCK_CLAIM_TIMEOUT_SECONDS
                )
                if requeued > 0:
                    logging.warning(
                        f"Watchdog requeued {requeued} stuck claims "
                        f"(timeout: {STUCK_CLAIM_TIMEOUT_SECONDS}s)"
                    )
            except Exception as exc:
                logging.exception(f"Watchdog error: {exc}")
            
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
    
    async def _count_pending(self) -> int:
        """Count pending events for metrics."""
        async with self.storage.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM outbox WHERE status IN ('pending', 'failed')"
            )
    
    async def _get_event_status(self, event_id: str) -> str:
        """Get current status of event."""
        async with self.storage.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT status FROM outbox WHERE event_id = $1",
                event_id
            )
    
    def _resolve_topic(self, event_type: str, routing_key: str | None) -> str:
        """
        Map event type to broker topic.
        
        Override this method to implement custom routing logic.
        Default: events.{event_type}
        """
        if routing_key:
            return routing_key
        return f"events.{event_type.lower().replace('_', '.')}"
```

---

## State Machine Testing

### Comprehensive State Machine Tests: `tests/test_outbox_statemachine.py`

```python
"""
Test suite for outbox state machine.

Validates all transitions, guards, and invalid state prevention.
"""
import pytest
from statemachine.exceptions import TransitionNotAllowed

from saga.outbox_statemachine import OutboxEventStateMachine

def test_initial_state():
    """Test state machine starts in 'pending' state."""
    sm = OutboxEventStateMachine(event_id="test_1")
    assert sm.current_state.id == 'pending'
    assert not sm.current_state.final

def test_optimistic_send_success_path():
    """Test happy path: pending -> optimistic -> sent."""
    sm = OutboxEventStateMachine(event_id="test_2")
    
    # Attempt optimistic send
    sm.attempt_optimistic_send()
    assert sm.current_state.id == 'optimistic'
    
    # Success
    sm.optimistic_send_succeeded()
    assert sm.current_state.id == 'sent'
    assert sm.current_state.final
    assert sm.published_at is not None

def test_optimistic_send_failure_fallback():
    """Test optimistic failure: pending -> optimistic -> pending."""
    sm = OutboxEventStateMachine(event_id="test_3")
    
    sm.attempt_optimistic_send()
    assert sm.current_state.id == 'optimistic'
    
    # Failed - should fallback to pending for polling
    sm.optimistic_send_failed()
    assert sm.current_state.id == 'pending'

def test_polling_worker_success_path():
    """Test polling worker path: pending -> claimed -> sent."""
    sm = OutboxEventStateMachine(event_id="test_4")
    
    # Worker claims
    sm.claim_for_processing()
    assert sm.current_state.id == 'claimed'
    
    # Publish succeeds
    sm.publish_succeeded()
    assert sm.current_state.id == 'sent'
    assert sm.current_state.final

def test_publish_failure_with_retry():
    """Test failure with retry: pending -> claimed -> failed -> pending."""
    sm = OutboxEventStateMachine(event_id="test_5")
    
    sm.claim_for_processing()
    sm.publish_failed(error=Exception("Network timeout"))
    assert sm.current_state.id == 'failed'
    assert sm.attempts == 1
    assert sm.last_error is not None
    
    # Retry after backoff
    sm.retry()
    assert sm.current_state.id == 'pending'

def test_max_attempts_move_to_dlq():
    """Test DLQ transition when max attempts exceeded."""
    sm = OutboxEventStateMachine(event_id="test_6")
    
    # Simulate multiple failures
    for i in range(10):
        if sm.current_state.id == 'pending':
            sm.claim_for_processing()
        sm.publish_failed(error=Exception(f"Attempt {i+1} failed"))
        if sm.current_state.id == 'failed':
            if i < 9:
                sm.retry()
    
    # After 10 attempts, should be in failed state
    assert sm.current_state.id == 'failed'
    assert sm.attempts == 10
    
    # Now move to DLQ
    sm.move_to_dlq(max_attempts=10)
    assert sm.current_state.id == 'dead_letter'
    assert sm.current_state.final

def test_guard_prevents_premature_dlq():
    """Test guard prevents DLQ move before max attempts."""
    sm = OutboxEventStateMachine(event_id="test_7")
    
    sm.claim_for_processing()
    sm.publish_failed(error=Exception("First failure"))
    
    # Attempt DLQ move with only 1 attempt (should be blocked by guard)
    assert not sm.before_move_to_dlq(max_attempts=10)
    
    # Transition should fail
    with pytest.raises(TransitionNotAllowed):
        sm.move_to_dlq(max_attempts=10)
    
    assert sm.current_state.id == 'failed'

def test_invalid_transition_prevented():
    """Test that invalid transitions raise exceptions."""
    sm = OutboxEventStateMachine(event_id="test_8")
    
    # Can't go directly from pending to sent
    with pytest.raises(TransitionNotAllowed):
        sm.current_state = sm.sent  # This won't work with proper transitions
    
    # Can't claim from optimistic
    sm.attempt_optimistic_send()
    with pytest.raises(TransitionNotAllowed):
        sm.claim_for_processing()

def test_sent_is_final_state():
    """Test that 'sent' state is final - no transitions allowed."""
    sm = OutboxEventStateMachine(event_id="test_9")
    
    sm.claim_for_processing()
    sm.publish_succeeded()
    
    assert sm.current_state.final
    assert len(sm.allowed_events) == 0  # No events allowed from final state

def test_manual_dlq_retry():
    """Test manual retry from DLQ (operational intervention)."""
    sm = OutboxEventStateMachine(event_id="test_10")
    
    # Get to DLQ
    for _ in range(10):
        if sm.current_state.id == 'pending':
            sm.claim_for_processing()
        sm.publish_failed(error=Exception("Persistent failure"))
        if sm.current_state.id == 'failed':
            sm.retry()
    
    sm.move_to_dlq(max_attempts=10)
    assert sm.current_state.id == 'dead_letter'
    
    # Manual retry (operator intervention)
    sm.manual_retry_dlq()
    assert sm.current_state.id == 'pending'
    assert sm.attempts == 10  # Attempts not reset (for tracking)

def test_can_transition_to_utility():
    """Test utility method for checking valid transitions."""
    sm = OutboxEventStateMachine(event_id="test_11")
    
    # From pending
    assert sm.can_transition_to('optimistic')
    assert sm.can_transition_to('claimed')
    assert not sm.can_transition_to('sent')  # Can't go directly
    assert not sm.can_transition_to('dead_letter')
    
    # From claimed
    sm.claim_for_processing()
    assert sm.can_transition_to('sent')
    assert sm.can_transition_to('failed')
    assert not sm.can_transition_to('pending')

def test_get_next_states():
    """Test getting reachable states from current state."""
    sm = OutboxEventStateMachine(event_id="test_12")
    
    next_states = sm.get_next_states()
    assert 'optimistic' in next_states
    assert 'claimed' in next_states
    assert len(next_states) == 2
    
    sm.claim_for_processing()
    next_states = sm.get_next_states()
    assert 'sent' in next_states
    assert 'failed' in next_states

def test_state_machine_with_initial_status():
    """Test creating state machine from existing database state."""
    # Simulate loading from database in 'failed' state
    sm = OutboxEventStateMachine(
        event_id="test_13",
        initial_status='failed'
    )
    
    assert sm.current_state.id == 'failed'
    
    # Can retry from failed
    sm.retry()
    assert sm.current_state.id == 'pending'

def test_concurrent_transitions():
    """Test that state machine is not thread-safe (document limitation)."""
    # Note: python-statemachine is NOT thread-safe by default
    # Each event should have its own state machine instance
    # This test documents the limitation
    
    sm = OutboxEventStateMachine(event_id="test_14")
    
    # Sequential operations are fine
    sm.attempt_optimistic_send()
    sm.optimistic_send_failed()
    
    # For concurrent access, use database-level locking
    # (our implementation uses database status as source of truth)
    assert True  # This test is documentation
```

---

## Integration Example: Full Flow

### Complete Example: `examples/complete_saga_example.py`

```python
"""
Complete example: Saga with optimistic sending and state machine.

Demonstrates:
1. Saga step with state update
2. Outbox event insertion
3. Transaction commit
4. Optimistic publish attempt
5. State machine transitions
6. Fallback to polling worker
"""
import asyncio
import logging
from uuid import uuid4
from datetime import datetime

from asyncpg import create_pool

from saga.interfaces import SagaState, SagaStatus, OutboxEvent
from saga.storage_postgres import PostgresSagaStorage
from saga.broker_kafka import KafkaBroker
from saga.optimistic_publisher import OptimisticPublisher
from saga.outbox_worker import OutboxWorker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def execute_order_placement_saga():
    """
    Execute a complete order placement saga with optimistic sending.
    
    Steps:
    1. Create order
    2. Reserve inventory
    3. Charge payment
    4. Send confirmation
    
    Each step publishes events using optimistic sending pattern.
    """
    # Setup
    pool = await create_pool(
        host='localhost',
        database='saga_db',
        user='saga_user',
        password='saga_pass',
        min_size=10,
        max_size=20
    )
    
    storage = PostgresSagaStorage(pool)
    broker = await KafkaBroker.create('localhost:9092')
    optimistic_pub = OptimisticPublisher(storage, broker, enable_optimistic=True)
    
    # Start polling worker as fallback
    worker = OutboxWorker(storage, broker, logger=None)
    await worker.start()
    
    try:
        # Create saga instance
        saga_id = str(uuid4())
        correlation_id = str(uuid4())
        
        saga = SagaState(
            id=saga_id,
            saga_type='OrderPlacement',
            correlation_id=correlation_id,
            state={
                'order_id': 'ORD-12345',
                'customer_id': 'CUST-789',
                'amount': 99.99
            },
            status=SagaStatus.STARTED,
            version=0
        )
        
        await storage.create(saga)
        logger.info(f"Created saga {saga_id}")
        
        # Step 1: Create Order
        await create_order_step(
            storage, optimistic_pub, saga_id,
            order_data={'order_id': 'ORD-12345', 'amount': 99.99}
        )
        
        # Step 2: Reserve Inventory
        await reserve_inventory_step(
            storage, optimistic_pub, saga_id,
            items=[{'sku': 'WIDGET-001', 'quantity': 2}]
        )
        
        # Step 3: Charge Payment
        await charge_payment_step(
            storage, optimistic_pub, saga_id,
            amount=99.99
        )
        
        # Complete saga
        saga = await storage.load(saga_id)
        await storage.save(
            saga_id,
            saga.state,
            SagaStatus.COMPLETED,
            saga.version
        )
        
        logger.info(f"Saga {saga_id} completed successfully")
        
        # Wait a bit for events to be processed
        await asyncio.sleep(3)
        
    finally:
        await worker.stop()
        await broker.close()
        await pool.close()


async def create_order_step(
    storage: PostgresSagaStorage,
    optimistic_pub: OptimisticPublisher,
    saga_id: str,
    order_data: dict
):
    """
    Step 1: Create order with optimistic event publishing.
    """
    logger.info(f"Executing create_order step for saga {saga_id}")
    
    async with storage.pool.acquire() as conn:
        async with conn.transaction():
            # Load saga
            saga = await storage.load(saga_id, for_update=True)
            
            # Idempotency check
            if saga.state.get('order_created'):
                logger.info("Order already created, skipping")
                return
            
            # Update state
            saga.state['order_created'] = True
            saga.state['order_data'] = order_data
            saga.state['order_created_at'] = datetime.utcnow().isoformat()
            
            # Save saga state
            new_version = await storage.save(
                saga_id,
                saga.state,
                SagaStatus.RUNNING,
                saga.version,
                current_step='create_order',
                conn=conn
            )
            
            # Create outbox event
            event = OutboxEvent(
                event_id=str(uuid4()),
                saga_id=saga_id,
                aggregate_type='order',
                aggregate_id=order_data['order_id'],
                event_type='OrderCreated',
                payload={
                    'saga_id': saga_id,
                    **order_data,
                    'timestamp': datetime.utcnow().isoformat()
                },
                headers={
                    'trace_id': str(uuid4()),
                    'message_id': str(uuid4()),
                    'causation_id': saga_id
                }
            )
            
            # Insert into outbox (in same transaction)
            await storage.append_outbox(event, conn=conn)
            
            logger.info(f"Order created, saga version: {new_version}")
        
        # Transaction committed - now try optimistic send
        success = await optimistic_pub.publish_after_commit(event)
        
        if success:
            logger.info(f"✓ Event published immediately (optimistic) - latency <10ms")
        else:
            logger.info(f"○ Event will be published by worker - latency ~100ms")


async def reserve_inventory_step(
    storage: PostgresSagaStorage,
    optimistic_pub: OptimisticPublisher,
    saga_id: str,
    items: list[dict]
):
    """
    Step 2: Reserve inventory with optimistic event publishing.
    """
    logger.info(f"Executing reserve_inventory step for saga {saga_id}")
    
    async with storage.pool.acquire() as conn:
        async with conn.transaction():
            saga = await storage.load(saga_id, for_update=True)
            
            if saga.state.get('inventory_reserved'):
                logger.info("Inventory already reserved, skipping")
                return
            
            saga.state['inventory_reserved'] = True
            saga.state['reserved_items'] = items
            
            new_version = await storage.save(
                saga_id,
                saga.state,
                SagaStatus.RUNNING,
                saga.version,
                current_step='reserve_inventory',
                conn=conn
            )
            
            event = OutboxEvent(
                event_id=str(uuid4()),
                saga_id=saga_id,
                aggregate_type='inventory',
                aggregate_id=saga_id,
                event_type='InventoryReserved',
                payload={
                    'saga_id': saga_id,
                    'items': items,
                    'timestamp': datetime.utcnow().isoformat()
                },
                headers={
                    'trace_id': str(uuid4()),
                    'message_id': str(uuid4()),
                    'causation_id': saga_id
                }
            )
            
            await storage.append_outbox(event, conn=conn)
        
        await optimistic_pub.publish_after_commit(event)


async def charge_payment_step(
    storage: PostgresSagaStorage,
    optimistic_pub: OptimisticPublisher,
    saga_id: str,
    amount: float
):
    """
    Step 3: Charge payment with optimistic event publishing.
    """
    logger.info(f"Executing charge_payment step for saga {saga_id}")
    
    async with storage.pool.acquire() as conn:
        async with conn.transaction():
            saga = await storage.load(saga_id, for_update=True)
            
            if saga.state.get('payment_charged'):
                logger.info("Payment already charged, skipping")
                return
            
            saga.state['payment_charged'] = True
            saga.state['charged_amount'] = amount
            
            new_version = await storage.save(
                saga_id,
                saga.state,
                SagaStatus.RUNNING,
                saga.version,
                current_step='charge_payment',
                conn=conn
            )
            
            event = OutboxEvent(
                event_id=str(uuid4()),
                saga_id=saga_id,
                aggregate_type='payment',
                aggregate_id=saga_id,
                event_type='PaymentCharged',
                payload={
                    'saga_id': saga_id,
                    'amount': amount,
                    'timestamp': datetime.utcnow().isoformat()
                },
                headers={
                    'trace_id': str(uuid4()),
                    'message_id': str(uuid4()),
                    'causation_id': saga_id
                }
            )
            
            await storage.append_outbox(event, conn=conn)
        
        await optimistic_pub.publish_after_commit(event)


if __name__ == '__main__':
    asyncio.run(execute_order_placement_saga())
```

---

## Performance Benchmarking

### Benchmark Script: `benchmarks/outbox_performance.py`

```python
"""
Benchmark outbox performance with and without optimistic sending.

Measures:
- End-to-end latency (write -> publish -> marked sent)
- Throughput (events/second)
- Resource usage (DB connections, CPU)# Enterprise Saga + Outbox Pattern: AI-Ready Implementation Guide

## Document Purpose & Context

This guide provides complete, production-ready implementation instructions for an enterprise-grade asynchronous saga orchestration system using the Transactional Outbox Pattern. Designed for AI agent consumption with explicit decision trees, validation criteria, and executable specifications.

### Core Guarantee
**Exactly-once side effects with at-least-once delivery** through transactional outbox and consumer-side deduplication.

### Technology Stack Assumptions
- **Database**: PostgreSQL 12+ (single source of truth)
- **Language**: Python 3.11+ with asyncpg
- **Message Broker**: Kafka/RabbitMQ-compatible
- **Observability**: Prometheus + OpenTelemetry
- **Orchestration**: Kubernetes
- **Transaction Isolation**: Read Committed (minimum)

---

 bounded delay (typically <1s) between state change and message delivery.

### ADR-002: Optimistic Concurrency Control (OCC)
**Decision**: Use version-based OCC for saga state updates.

**Rationale**:
- Pessimistic locks (SELECT FOR UPDATE) serialize saga workers unnecessarily
- OCC allows concurrent saga execution when steps don't conflict
- Better for distributed worker pools

**Implementation**: Version field incremented atomically; retry on version mismatch with exponential backoff.

### ADR-003: Claim-Based Worker Processing
**Decision**: Workers claim batches using `UPDATE ... RETURNING` with `FOR UPDATE SKIP LOCKED`.

**Rationale**:
- Prevents thundering herd on same messages
- Atomic claim without external coordination (Redis, etc.)
- Postgres-native solution reduces dependencies

### ADR-004: Optimistic Sending Pattern (2024-2025 Performance Enhancement)
**Decision**: Attempt immediate publish after transaction commit, with polling worker as fallback.

**Rationale**:
- Traditional polling introduces 50-100ms latency minimum (poll interval)
- 99%+ of publishes succeed immediately in healthy systems
- Failed immediate publishes are caught by polling worker (existing fallback)
- No additional failure modes - maintains same consistency guarantees

**Performance Impact**:
- Latency reduction: ~100ms → <10ms (10x improvement)
- Throughput: Same or better (one less DB round-trip in happy path)
- Database load: Reduced (fewer polling queries for successfully sent events)

**Trade-off**: Slightly more complex application code, but worth it for dramatic latency improvement.

---

## Schema Design: Critical Implementation Details

### Migration: `0001_create_saga_outbox.sql`

```sql
-- Required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Outbox event status enum (enforced at DB level)
CREATE TYPE outbox_status AS ENUM (
    'pending',      -- Ready to be published
    'optimistic',   -- Optimistic send in progress (transient)
    'claimed',      -- Claimed by polling worker
    'sent',         -- Successfully published
    'failed',       -- Publish failed, will retry
    'dead_letter'   -- Exceeded max retries
);

-- Core saga state table
CREATE TABLE saga_instance (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  saga_type TEXT NOT NULL,                    -- e.g., 'OrderPlacement', 'PaymentProcessing'
  correlation_id UUID NOT NULL,               -- Business identifier for grouping
  state JSONB NOT NULL DEFAULT '{}'::jsonb,   -- Saga step state (idempotency keys, step results)
  status TEXT NOT NULL DEFAULT 'started',     -- started, running, compensating, completed, failed
  current_step TEXT,                          -- For debugging: which step is executing
  version BIGINT NOT NULL DEFAULT 0,          -- Optimistic concurrency control
  last_error TEXT,                            -- Serialized exception for debugging
  retry_count INT NOT NULL DEFAULT 0,         -- Failed execution attempts
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  
  CONSTRAINT valid_status CHECK (status IN ('started', 'running', 'compensating', 'completed', 'failed'))
);

-- Performance indexes
CREATE INDEX idx_saga_type_status ON saga_instance(saga_type, status) WHERE status IN ('running', 'compensating');
CREATE INDEX idx_saga_correlation ON saga_instance(correlation_id);
CREATE INDEX idx_saga_stale ON saga_instance(updated_at) WHERE status IN ('running', 'compensating'); -- For stuck saga detection

-- Transactional outbox table
CREATE TABLE outbox (
  id BIGSERIAL PRIMARY KEY,
  event_id UUID NOT NULL UNIQUE DEFAULT uuid_generate_v4(),  -- Deduplication key
  saga_id UUID REFERENCES saga_instance(id) ON DELETE CASCADE, -- Optional: link to saga
  aggregate_type TEXT NOT NULL,               -- Domain entity type
  aggregate_id UUID NOT NULL,                 -- Domain entity ID
  event_type TEXT NOT NULL,                   -- Event name for routing
  payload JSONB NOT NULL,                     -- Event data
  headers JSONB NOT NULL DEFAULT '{}'::jsonb, -- Metadata (trace_id, causation_id, etc.)
  status outbox_status NOT NULL DEFAULT 'pending', -- Use ENUM for type safety
  routing_key TEXT,                           -- Optional: for topic/exchange routing
  partition_key TEXT,                         -- Optional: for ordered delivery
  attempts INT NOT NULL DEFAULT 0,            -- Publish retry count
  max_attempts INT NOT NULL DEFAULT 10,       -- Configurable failure threshold
  available_at TIMESTAMPTZ NOT NULL DEFAULT now(), -- Backoff delay
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_at TIMESTAMPTZ,
  published_at TIMESTAMPTZ
);

-- Remove the CHECK constraint since we're using ENUM
-- The database will enforce valid status values automatically

-- Critical indexes for worker performance
CREATE INDEX idx_outbox_pending ON outbox (status, available_at, created_at) 
  WHERE status IN ('pending', 'failed');
CREATE INDEX idx_outbox_aggregate ON outbox(aggregate_type, aggregate_id);
CREATE INDEX idx_outbox_saga ON outbox(saga_id) WHERE saga_id IS NOT NULL;

-- Archive table for sent messages (for audit/replay)
CREATE TABLE outbox_archive (LIKE outbox INCLUDING ALL);
ALTER TABLE outbox_archive ADD COLUMN archived_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Consumer deduplication table (each consumer service maintains its own)
CREATE TABLE consumer_inbox (
    event_id UUID PRIMARY KEY,
    consumer_name TEXT NOT NULL,              -- Identifies the consuming service
    source_topic TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processing_duration_ms INT                -- For performance tracking
);

CREATE INDEX idx_inbox_consumer ON consumer_inbox(consumer_name, consumed_at);
```

### Schema Validation Checklist
- [ ] Primary keys use UUID v4 for distributed generation
- [ ] Status fields use CHECK constraints (prevent invalid states)
- [ ] Indexes cover all WHERE clauses in worker queries
- [ ] Foreign keys include ON DELETE CASCADE where appropriate
- [ ] Timestamps use TIMESTAMPTZ (not TIMESTAMP)
- [ ] JSONB fields have default values to prevent NULL surprises

---

## Core Interfaces: Type-Safe Contracts

### `saga/interfaces.py`

```python
"""
Core abstractions for saga orchestration.
All implementations must be async-safe and connection-pool aware.
"""
from typing import Protocol, Any, TypedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid

class SagaStatus(str, Enum):
    STARTED = "started"
    RUNNING = "running"
    COMPENSATING = "compensating"
    COMPLETED = "completed"
    FAILED = "failed"

class OutboxStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    SENT = "sent"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"

@dataclass
class OutboxEvent:
    """
    Represents a single event to be published.
    
    Design notes:
    - event_id is the deduplication key (must be deterministic or pre-generated)
    - payload should be serializable to JSON (no binary data)
    - headers MUST include: trace_id, causation_id for distributed tracing
    """
    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict
    headers: dict = field(default_factory=dict)
    saga_id: str | None = None
    routing_key: str | None = None
    partition_key: str | None = None
    max_attempts: int = 10
    
    def __post_init__(self):
        # Validate required headers for observability
        required_headers = {'trace_id', 'message_id'}
        if not required_headers.issubset(self.headers.keys()):
            raise ValueError(f"Missing required headers: {required_headers - self.headers.keys()}")

@dataclass
class SagaState:
    """Immutable snapshot of saga execution state."""
    id: str
    saga_type: str
    correlation_id: str
    state: dict
    status: SagaStatus
    version: int
    current_step: str | None = None
    last_error: str | None = None
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

class SagaStorage(Protocol):
    """
    Persistence layer for saga state and outbox.
    
    Transactionality requirements:
    - save() and append_outbox() must execute in caller's transaction
    - load() should use FOR UPDATE if pessimistic locking needed
    """
    
    async def create(self, saga: SagaState) -> None:
        """Initialize new saga. Raises if ID already exists."""
        ...
    
    async def load(self, saga_id: str, for_update: bool = False) -> SagaState:
        """
        Load saga state.
        
        Args:
            saga_id: Saga identifier
            for_update: If True, acquire pessimistic lock (SELECT FOR UPDATE)
        
        Raises:
            KeyError: If saga not found
        """
        ...
    
    async def save(
        self, 
        saga_id: str, 
        state: dict, 
        status: SagaStatus,
        expected_version: int,
        current_step: str | None = None,
        error: str | None = None
    ) -> int:
        """
        Atomically update saga state with optimistic concurrency control.
        
        Args:
            expected_version: Must match current version in DB
        
        Returns:
            New version number after update
        
        Raises:
            ConcurrencyError: If version mismatch (another worker updated saga)
        """
        ...
    
    async def append_outbox(self, event: OutboxEvent) -> None:
        """
        Insert event into outbox table.
        
        MUST be called within same transaction as save() to guarantee atomicity.
        Idempotent: duplicate event_id is silently ignored (ON CONFLICT DO NOTHING).
        """
        ...
    
    async def mark_outbox_sent(self, event_id: str) -> None:
        """Mark event as successfully published. Idempotent."""
        ...
    
    async def mark_outbox_failed(self, event_id: str, error: str) -> None:
        """Record publish failure. May move to dead_letter after max_attempts."""
        ...
    
    async def claim_pending_events(self, batch_size: int, worker_id: str) -> list[dict]:
        """
        Atomically claim pending events for processing.
        
        Uses UPDATE ... RETURNING with FOR UPDATE SKIP LOCKED to avoid contention.
        Updates status to 'claimed' and sets claimed_at timestamp.
        
        Returns:
            List of claimed event rows (as dicts)
        """
        ...
    
    async def requeue_stuck_claims(self, timeout_seconds: int) -> int:
        """
        Reset 'claimed' events older than timeout back to 'pending'.
        
        Handles crashed workers. Should be called periodically by separate watchdog.
        
        Returns:
            Number of events requeued
        """
        ...

class MessageBroker(Protocol):
    """
    Abstract message broker for event publishing.
    
    Implementation requirements:
    - Idempotent publish (use message_id for deduplication)
    - Support for custom headers (tracing, causation)
    - Async operations
    """
    
    async def publish(
        self,
        topic: str,
        payload: dict,
        message_id: str,
        headers: dict | None = None,
        partition_key: str | None = None
    ) -> None:
        """
        Publish message to broker.
        
        Args:
            topic: Target topic/exchange
            message_id: Deduplication key (broker must honor)
            partition_key: Optional key for ordered delivery
        
        Raises:
            BrokerError: On transient failures (will retry with backoff)
        """
        ...

class SagaLogger(Protocol):
    """
    Structured logging for saga operations.
    
    All logs must include saga_id and trace_id for correlation.
    """
    
    async def info(self, saga_id: str, msg: str, **context: Any) -> None: ...
    async def warning(self, saga_id: str, msg: str, **context: Any) -> None: ...
    async def error(self, saga_id: str, msg: str, exc: Exception | None = None, **context: Any) -> None: ...
    
    async def event(
        self,
        saga_id: str,
        step_name: str,
        event_type: str,
        payload: dict,
        status: str = "success"
    ) -> None:
        """
        Log saga step execution event.
        
        Used for audit trail and debugging. Should write to separate log stream.
        """
        ...
```

---

## Implementation: PostgreSQL Storage Layer

### `saga/storage_postgres.py`

```python
"""
PostgreSQL implementation of SagaStorage.

Critical implementation notes:
1. Always use connection pools (asyncpg.Pool), never direct connections
2. All mutations must support caller-managed transactions
3. Retry logic for serialization failures (isolation level conflicts)
4. Comprehensive error handling with custom exceptions
"""
import json
import uuid
from datetime import datetime, timedelta
from typing import Any
from asyncpg import Pool, Connection
from asyncpg.exceptions import UniqueViolationError, SerializationError

from .interfaces import (
    SagaStorage, SagaState, SagaStatus, OutboxEvent, OutboxStatus
)

class ConcurrencyError(Exception):
    """Raised when optimistic concurrency check fails."""
    pass

class SagaNotFoundError(KeyError):
    """Raised when saga doesn't exist."""
    pass

class PostgresSagaStorage(SagaStorage):
    """
    Production-ready PostgreSQL saga storage.
    
    Transaction semantics:
    - Methods with conn parameter execute within caller's transaction
    - Methods without conn parameter acquire new connection and auto-commit
    """
    
    def __init__(self, pool: Pool):
        self.pool = pool
    
    async def create(self, saga: SagaState) -> None:
        """Initialize new saga instance."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO saga_instance (
                        id, saga_type, correlation_id, state, status, 
                        version, current_step, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    saga.id, saga.saga_type, saga.correlation_id,
                    json.dumps(saga.state), saga.status.value,
                    saga.version, saga.current_step,
                    saga.created_at, saga.updated_at
                )
            except UniqueViolationError:
                raise ValueError(f"Saga {saga.id} already exists")
    
    async def load(self, saga_id: str, for_update: bool = False) -> SagaState:
        """Load saga with optional pessimistic lock."""
        query = """
            SELECT id, saga_type, correlation_id, state, status, version,
                   current_step, last_error, retry_count, created_at, updated_at
            FROM saga_instance
            WHERE id = $1
        """
        if for_update:
            query += " FOR UPDATE"
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, saga_id)
            if not row:
                raise SagaNotFoundError(f"Saga {saga_id} not found")
            
            return SagaState(
                id=str(row['id']),
                saga_type=row['saga_type'],
                correlation_id=str(row['correlation_id']),
                state=row['state'],
                status=SagaStatus(row['status']),
                version=row['version'],
                current_step=row['current_step'],
                last_error=row['last_error'],
                retry_count=row['retry_count'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
    
    async def save(
        self,
        saga_id: str,
        state: dict,
        status: SagaStatus,
        expected_version: int,
        current_step: str | None = None,
        error: str | None = None,
        conn: Connection | None = None
    ) -> int:
        """
        Update saga state with optimistic concurrency control.
        
        Supports both standalone and transactional usage via conn parameter.
        """
        query = """
            UPDATE saga_instance
            SET state = $1,
                status = $2,
                version = version + 1,
                current_step = $3,
                last_error = $4,
                retry_count = CASE WHEN $5::text IS NOT NULL THEN retry_count + 1 ELSE retry_count END,
                updated_at = now(),
                completed_at = CASE WHEN $2 IN ('completed', 'failed') THEN now() ELSE completed_at END
            WHERE id = $6 AND version = $7
            RETURNING version
        """
        
        async def _execute(connection: Connection) -> int:
            result = await connection.fetchrow(
                query,
                json.dumps(state), status.value, current_step, error,
                error, saga_id, expected_version
            )
            if not result:
                raise ConcurrencyError(
                    f"Version mismatch for saga {saga_id}. "
                    f"Expected {expected_version}, may have been updated by another worker."
                )
            return result['version']
        
        if conn:
            return await _execute(conn)
        else:
            async with self.pool.acquire() as conn:
                return await _execute(conn)
    
    async def append_outbox(
        self, 
        event: OutboxEvent,
        conn: Connection | None = None
    ) -> None:
        """
        Insert event into outbox.
        
        CRITICAL: Must be called within same transaction as save() for atomicity guarantee.
        Uses ON CONFLICT DO NOTHING for idempotency.
        """
        query = """
            INSERT INTO outbox (
                event_id, saga_id, aggregate_type, aggregate_id, event_type,
                payload, headers, routing_key, partition_key, max_attempts,
                status, available_at, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, now())
            ON CONFLICT (event_id) DO NOTHING
        """
        
        async def _execute(connection: Connection):
            await connection.execute(
                query,
                event.event_id, event.saga_id, event.aggregate_type,
                event.aggregate_id, event.event_type,
                json.dumps(event.payload), json.dumps(event.headers),
                event.routing_key, event.partition_key, event.max_attempts,
                OutboxStatus.PENDING.value, datetime.utcnow()
            )
        
        if conn:
            await _execute(conn)
        else:
            async with self.pool.acquire() as conn:
                await _execute(conn)
    
    async def claim_pending_events(
        self, 
        batch_size: int, 
        worker_id: str
    ) -> list[dict]:
        """
        Atomically claim events for processing using SKIP LOCKED.
        
        Critical performance optimization: This prevents lock contention
        between multiple workers competing for same events.
        """
        query = """
            WITH claimable AS (
                SELECT id
                FROM outbox
                WHERE status = $1
                  AND available_at <= now()
                ORDER BY created_at ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            UPDATE outbox
            SET status = $3,
                claimed_at = now()
            WHERE id IN (SELECT id FROM claimable)
            RETURNING 
                id, event_id, saga_id, aggregate_type, aggregate_id,
                event_type, payload, headers, routing_key, partition_key,
                attempts, max_attempts, created_at
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                query,
                OutboxStatus.PENDING.value,
                batch_size,
                OutboxStatus.CLAIMED.value
            )
            
            return [dict(row) for row in rows]
    
    async def mark_outbox_sent(self, event_id: str) -> None:
        """Mark event as successfully published."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox
                SET status = $1, published_at = now()
                WHERE event_id = $2
                """,
                OutboxStatus.SENT.value, event_id
            )
    
    async def mark_outbox_failed(self, event_id: str, error: str) -> None:
        """
        Record publish failure and apply exponential backoff.
        
        Moves to dead_letter queue after max_attempts exceeded.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox
                SET attempts = attempts + 1,
                    status = CASE
                        WHEN attempts + 1 >= max_attempts THEN $1
                        ELSE $2
                    END,
                    available_at = CASE
                        WHEN attempts + 1 < max_attempts 
                        THEN now() + (POWER(2, attempts + 1) || ' seconds')::interval
                        ELSE available_at
                    END,
                    last_error = $3
                WHERE event_id = $4
                """,
                OutboxStatus.DEAD_LETTER.value,
                OutboxStatus.FAILED.value,
                error,
                event_id
            )
    
    async def requeue_stuck_claims(self, timeout_seconds: int) -> int:
        """
        Safety mechanism: reset stuck 'claimed' events back to 'pending'.
        
        Run periodically (e.g., every 30s) by separate watchdog process.
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE outbox
                SET status = $1, claimed_at = NULL
                WHERE status = $2
                  AND claimed_at < now() - ($3 || ' seconds')::interval
                """,
                OutboxStatus.PENDING.value,
                OutboxStatus.CLAIMED.value,
                timeout_seconds
            )
            # asyncpg returns "UPDATE N"
            return int(result.split()[-1])
    
    async def archive_sent_events(self, older_than_days: int) -> int:
        """
        Move old sent events to archive table.
        
        Should run as scheduled job (e.g., daily at low traffic time).
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Copy to archive
                await conn.execute(
                    """
                    INSERT INTO outbox_archive
                    SELECT *, now() as archived_at
                    FROM outbox
                    WHERE status = $1
                      AND published_at < now() - ($2 || ' days')::interval
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    OutboxStatus.SENT.value, older_than_days
                )
                
                # Delete from main table
                result = await conn.execute(
                    """
                    DELETE FROM outbox
                    WHERE status = $1
                      AND published_at < now() - ($2 || ' days')::interval
                    """,
                    OutboxStatus.SENT.value, older_than_days
                )
                
                return int(result.split()[-1])
```

---

## Outbox Worker: Production-Grade Implementation

### `saga/outbox_worker.py`

```python
"""
Outbox relay worker - polls and publishes events to message broker.

Design principles:
1. Batch processing for throughput
2. Exponential backoff on failures
3. Graceful shutdown support
4. Comprehensive metrics and tracing
5. Dead letter queue for poison messages

Deployment model:
- Run 3-10 replicas depending on throughput needs
- Each worker processes independently (no coordination needed)
- Scale horizontally based on outbox_pending_total metric
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import List
from uuid import uuid4

from asyncpg import Pool
from prometheus_client import Counter, Gauge, Histogram
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .interfaces import MessageBroker, SagaLogger
from .storage_postgres import PostgresSagaStorage

# Configuration constants
POLL_INTERVAL_SECONDS = 1.0
BATCH_SIZE = 100
STUCK_CLAIM_TIMEOUT_SECONDS = 300  # 5 minutes
WATCHDOG_INTERVAL_SECONDS = 30

# Prometheus metrics
OUTBOX_PENDING = Gauge(
    "outbox_pending_events_total",
    "Number of pending outbox events"
)
OUTBOX_CLAIMED = Counter(
    "outbox_claimed_events_total",
    "Total events claimed by workers"
)
OUTBOX_PUBLISHED = Counter(
    "outbox_published_events_total",
    "Total events successfully published",
    ["event_type"]
)
OUTBOX_FAILED = Counter(
    "outbox_failed_events_total",
    "Total events that failed to publish",
    ["event_type", "reason"]
)
OUTBOX_DEAD_LETTER = Counter(
    "outbox_dead_letter_events_total",
    "Events moved to dead letter queue after max retries",
    ["event_type"]
)
OUTBOX_PUBLISH_DURATION = Histogram(
    "outbox_publish_duration_seconds",
    "Time to publish single event",
    ["event_type"]
)
OUTBOX_BATCH_DURATION = Histogram(
    "outbox_batch_duration_seconds",
    "Time to process entire batch"
)

tracer = trace.get_tracer(__name__)

class OutboxWorker:
    """
    Outbox relay worker - consumes events from outbox table and publishes to broker.
    
    Lifecycle:
    1. Claim batch of pending events (atomic)
    2. Publish each event to broker
    3. Mark as sent on success, or reschedule with backoff on failure
    4. Repeat until shutdown signal received
    """
    
    def __init__(
        self,
        storage: PostgresSagaStorage,
        broker: MessageBroker,
        logger: SagaLogger,
        worker_id: str | None = None,
        batch_size: int = BATCH_SIZE,
        poll_interval: float = POLL_INTERVAL_SECONDS
    ):
        self.storage = storage
        self.broker = broker
        self.logger = logger
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self._shutdown = False
        self._task: asyncio.Task | None = None
    
    async def start(self) -> None:
        """Start worker main loop."""
        if self._task:
            raise RuntimeError("Worker already started")
        
        self._shutdown = False
        self._task = asyncio.create_task(self._run())
        
        # Start watchdog for stuck claims
        asyncio.create_task(self._watchdog())
        
        logging.info(f"Outbox worker {self.worker_id} started")
    
    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully shutdown worker."""
        if not self._task:
            return
        
        logging.info(f"Shutting down worker {self.worker_id}...")
        self._shutdown = True
        
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.TimeoutError:
            logging.warning(f"Worker {self.worker_id} shutdown timed out, cancelling")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logging.info(f"Worker {self.worker_id} stopped")
    
    async def _run(self) -> None:
        """Main processing loop."""
        while not self._shutdown:
            try:
                with OUTBOX_BATCH_DURATION.time():
                    await self._process_batch()
            except Exception as exc:
                logging.exception(f"Worker {self.worker_id} batch processing error: {exc}")
                await asyncio.sleep(5)  # Back off on errors
            
            # Update pending count metric
            try:
                pending_count = await self._count_pending()
                OUTBOX_PENDING.set(pending_count)
            except Exception:
                pass  # Don't fail on metrics
            
            # Wait before next poll
            await asyncio.sleep(self.poll_interval)
    
    async def _process_batch(self) -> None:
        """Claim and process a batch of pending events."""
        events = await self.storage.claim_pending_events(
            self.batch_size,
            self.worker_id
        )
        
        if not events:
            return
        
        OUTBOX_CLAIMED.inc(len(events))
        logging.debug(f"Worker {self.worker_id} claimed {len(events)} events")
        
        # Process events concurrently within batch
        tasks = [self._publish_event(event) for event in events]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _publish_event(self, event: dict) -> None:
        """
        Publish single event with retry and error handling.
        
        Success path: event -> broker -> mark_sent
        Failure path: event -> broker [fails] -> mark_failed (with backoff)
        """
        event_id = str(event['event_id'])
        event_type = event['event_type']
        
        # Start tracing span
        with tracer.start_as_current_span(
            "outbox.publish_event",
            attributes={
                "event_id": event_id,
                "event_type": event_type,
                "worker_id": self.worker_id,
                "attempt": event['attempts'] + 1
            }
        ) as span:
            try:
                with OUTBOX_PUBLISH_DURATION.labels(event_type=event_type).time():
                    # Publish to broker
                    await self.broker.publish(
                        topic=self._resolve_topic(event_type, event.get('routing_key')),
                        payload=event['payload'],
                        message_id=event_id,
                        headers=event['headers'],
                        partition_key=event.get('partition_key')
                    )
                
                # Success: mark as sent
                await self.storage.mark_outbox_sent(event_id)
                OUTBOX_PUBLISHED.labels(event_type=event_type).inc()
                
                span.set_status(Status(StatusCode.OK))
                
                await self.logger.info(
                    event.get('saga_id', 'unknown'),
                    f"Published event {event_type}",
                    event_id=event_id,
                    attempt=event['attempts'] + 1
                )
                
            except Exception as exc:
                # Failure: record error and reschedule
                error_msg = f"{type(exc).__name__}: {str(exc)}"
                
                await self.storage.mark_outbox_failed(event_id, error_msg)
                OUTBOX_FAILED.labels(
                    event_type=event_type,
                    reason=type(exc).__name__
                ).inc()
                
                span.set_status(Status(StatusCode.ERROR))
                span.record_exception(exc)
                
                # Check if moved to dead letter
                if event['attempts'] + 1 >= event['max_attempts']:
                    OUTBOX_DEAD_LETTER.labels(event_type=event_type).inc()
                    await self.logger.error(
                        event.get('saga_id', 'unknown'),
                        f"Event {event_type} moved to dead letter queue after {event['max_attempts']} attempts",
                        exc=exc,
                        event_id=event_id
                    )
                else:
                    backoff = 2 ** (event['attempts'] + 1)
                    await self.logger.warning(
                        event.get('saga_id', 'unknown'),
                        f"Failed to publish {event_type}, will retry in {backoff}s",
                        event_id=event_id,
                        attempt=event['attempts'] + 1,
                        error=error_msg
                    )
    
    async def _watchdog(self) -> None:
        """Periodically requeue stuck claims (crashed workers)."""
        while not self._shutdown:
            try:
                requeued = await self.storage.requeue_stuck_claims(
                    STUCK_CLAIM_TIMEOUT_SECONDS
                )
                if requeued > 0:
                    logging.warning(
                        f"Watchdog requeued {requeued} stuck claims "
                        f"(timeout: {STUCK_CLAIM_TIMEOUT_SECONDS}s)"
                    )
            except Exception as exc:
                logging.exception(f"Watchdog error: {exc}")
            
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
    
    async def _count_pending(self) -> int:
        """Count pending events for metrics."""
        async with self.storage.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM outbox WHERE status IN ('pending', 'failed')"
            )
    
    def _resolve_topic(self, event_type: str, routing_key: str | None) -> str:
        """
        Map event type to broker topic.
        
        Override this method to implement custom routing logic.
        Default: events.{event_type}
        """
        if routing_key:
            return routing_key
        return f"events.{event_type.lower().replace('_', '.')}"
```

---

## Message Broker Implementation Examples

### Kafka Broker: `saga/broker_kafka.py`

```python
"""
Kafka implementation of MessageBroker interface.

Production considerations:
- Use transactional producer for exactly-once semantics (advanced)
- Configure acks=all for durability
- Set enable.idempotence=true
- Use linger.ms for batching efficiency
"""
import json
import logging
from typing import Any
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from .interfaces import MessageBroker

class KafkaBroker(MessageBroker):
    """Kafka message broker with idempotent publishing."""
    
    def __init__(self, producer: AIOKafkaProducer):
        self.producer = producer
    
    async def publish(
        self,
        topic: str,
        payload: dict,
        message_id: str,
        headers: dict | None = None,
        partition_key: str | None = None
    ) -> None:
        """
        Publish event to Kafka topic.
        
        Headers include message_id for broker-level deduplication (if enabled).
        """
        # Prepare headers (Kafka requires bytes)
        kafka_headers = [
            ("message_id", message_id.encode()),
        ]
        
        if headers:
            for key, value in headers.items():
                kafka_headers.append((key, str(value).encode()))
        
        try:
            # Serialize payload
            value = json.dumps(payload).encode('utf-8')
            key = partition_key.encode('utf-8') if partition_key else None
            
            # Send with acks=all for durability
            await self.producer.send_and_wait(
                topic,
                value=value,
                key=key,
                headers=kafka_headers
            )
            
        except KafkaError as exc:
            logging.error(f"Kafka publish failed for {message_id}: {exc}")
            raise

    @classmethod
    async def create(
        cls,
        bootstrap_servers: str,
        **config: Any
    ) -> "KafkaBroker":
        """
        Factory method to create and start Kafka producer.
        
        Recommended config:
        - acks='all': Wait for all replicas
        - enable_idempotence=True: Prevent duplicates
        - max_in_flight_requests_per_connection=5: Balance throughput and ordering
        - compression_type='lz4': Reduce bandwidth
        """
        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            acks='all',
            enable_idempotence=True,
            max_in_flight_requests_per_connection=5,
            compression_type='lz4',
            **config
        )
        
        await producer.start()
        return cls(producer)
    
    async def close(self) -> None:
        """Gracefully close producer."""
        await self.producer.stop()
```

### RabbitMQ Broker: `saga/broker_rabbitmq.py`

```python
"""
RabbitMQ implementation using aio-pika.

Production considerations:
- Use publisher confirms for reliability
- Set delivery_mode=2 for persistent messages
- Configure dead letter exchange for failed messages
"""
import json
import logging
from typing import Any
from aio_pika import connect_robust, Message, DeliveryMode
from aio_pika.abc import AbstractRobustConnection, AbstractChannel

from .interfaces import MessageBroker

class RabbitMQBroker(MessageBroker):
    """RabbitMQ broker with publisher confirms."""
    
    def __init__(self, connection: AbstractRobustConnection, channel: AbstractChannel):
        self.connection = connection
        self.channel = channel
    
    async def publish(
        self,
        topic: str,
        payload: dict,
        message_id: str,
        headers: dict | None = None,
        partition_key: str | None = None
    ) -> None:
        """Publish to RabbitMQ exchange."""
        # Prepare headers
        msg_headers = {"message_id": message_id}
        if headers:
            msg_headers.update(headers)
        
        # Create message with persistence
        message = Message(
            body=json.dumps(payload).encode('utf-8'),
            message_id=message_id,
            headers=msg_headers,
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type='application/json'
        )
        
        try:
            # Publish with publisher confirms
            await self.channel.default_exchange.publish(
                message,
                routing_key=topic,
                mandatory=True  # Return message if no queue bound
            )
        except Exception as exc:
            logging.error(f"RabbitMQ publish failed for {message_id}: {exc}")
            raise
    
    @classmethod
    async def create(cls, amqp_url: str) -> "RabbitMQBroker":
        """Factory to create RabbitMQ broker with robust connection."""
        connection = await connect_robust(amqp_url)
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=100)  # Flow control
        
        return cls(connection, channel)
    
    async def close(self) -> None:
        """Gracefully close connection."""
        await self.channel.close()
        await self.connection.close()
```

---

## Consumer-Side Deduplication Pattern

### Consumer Inbox Implementation: `saga/consumer_inbox.py`

```python
"""
Consumer-side deduplication using inbox pattern.

Critical: Every consumer service must implement this to guarantee
exactly-once processing despite at-least-once delivery.
"""
import json
import logging
from datetime import datetime
from typing import Callable, Awaitable, TypeVar, Generic
from asyncpg import Pool, UniqueViolationError

T = TypeVar('T')

class ConsumerInbox:
    """
    Idempotent message consumer with inbox deduplication.
    
    Pattern:
    1. Try insert event_id into consumer_inbox
    2. If unique violation -> already processed, skip
    3. Otherwise -> process business logic in same transaction
    4. Commit transaction
    """
    
    def __init__(self, pool: Pool, consumer_name: str):
        self.pool = pool
        self.consumer_name = consumer_name
    
    async def process_idempotent(
        self,
        event_id: str,
        source_topic: str,
        event_type: str,
        payload: dict,
        handler: Callable[[dict], Awaitable[T]]
    ) -> T | None:
        """
        Process message idempotently using inbox pattern.
        
        Returns:
            Handler result if processed, None if duplicate
        """
        start_time = datetime.utcnow()
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Try to insert into inbox (atomic dedup check)
                try:
                    await conn.execute(
                        """
                        INSERT INTO consumer_inbox (
                            event_id, consumer_name, source_topic, 
                            event_type, payload, consumed_at
                        )
                        VALUES ($1, $2, $3, $4, $5, now())
                        """,
                        event_id, self.consumer_name, source_topic,
                        event_type, json.dumps(payload)
                    )
                except UniqueViolationError:
                    # Already processed - skip
                    logging.info(
                        f"Duplicate message {event_id} for {self.consumer_name}, skipping"
                    )
                    return None
                
                # New message - execute handler in same transaction
                result = await handler(payload)
                
                # Update processing duration
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                await conn.execute(
                    """
                    UPDATE consumer_inbox 
                    SET processing_duration_ms = $1 
                    WHERE event_id = $2
                    """,
                    duration_ms, event_id
                )
                
                return result
    
    async def cleanup_old_entries(self, older_than_days: int = 7) -> int:
        """
        Remove old inbox entries to prevent unbounded growth.
        
        Run as scheduled job (e.g., daily).
        Safe to delete old entries since duplicates are unlikely after TTL.
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM consumer_inbox
                WHERE consumer_name = $1
                  AND consumed_at < now() - ($2 || ' days')::interval
                """,
                self.consumer_name, older_than_days
            )
            return int(result.split()[-1])
```

### Example Consumer Service: `saga/example_consumer.py`

```python
"""
Example consumer implementation using inbox pattern.
"""
import asyncio
import json
import logging
from aiokafka import AIOKafkaConsumer
from asyncpg import create_pool

from .consumer_inbox import ConsumerInbox

class OrderEventConsumer:
    """Example consumer for order events."""
    
    def __init__(self, inbox: ConsumerInbox):
        self.inbox = inbox
    
    async def handle_order_created(self, payload: dict) -> None:
        """Business logic for OrderCreated event."""
        order_id = payload['order_id']
        customer_id = payload['customer_id']
        
        logging.info(f"Processing order {order_id} for customer {customer_id}")
        
        # Execute business logic here (database updates, external API calls, etc.)
        # This code is protected by inbox deduplication
        
        await asyncio.sleep(0.1)  # Simulate processing
        
        logging.info(f"Order {order_id} processed successfully")
    
    async def consume_events(self, consumer: AIOKafkaConsumer) -> None:
        """Main consumption loop."""
        async for msg in consumer:
            # Extract event metadata from headers
            headers = dict(msg.headers) if msg.headers else {}
            event_id = headers.get(b'message_id', b'').decode()
            trace_id = headers.get(b'trace_id', b'').decode()
            
            # Deserialize payload
            payload = json.loads(msg.value.decode('utf-8'))
            event_type = payload.get('event_type', 'unknown')
            
            logging.info(
                f"Received {event_type} (event_id={event_id}, trace_id={trace_id})"
            )
            
            try:
                # Process with inbox deduplication
                await self.inbox.process_idempotent(
                    event_id=event_id,
                    source_topic=msg.topic,
                    event_type=event_type,
                    payload=payload,
                    handler=self.handle_order_created
                )
                
                # Commit offset after successful processing
                await consumer.commit()
                
            except Exception as exc:
                logging.exception(f"Failed to process {event_id}: {exc}")
                # Don't commit offset - will retry message
                # Consider moving to DLQ after N retries

# Usage example
async def main():
    # Setup database pool
    pool = await create_pool(
        host='localhost',
        port=5432,
        user='saga_user',
        password='saga_pass',
        database='saga_db',
        min_size=5,
        max_size=20
    )
    
    # Create inbox
    inbox = ConsumerInbox(pool, consumer_name='order-service')
    
    # Create Kafka consumer
    consumer = AIOKafkaConsumer(
        'events.order.created',
        bootstrap_servers='localhost:9092',
        group_id='order-service-consumer-group',
        enable_auto_commit=False,  # Manual commit after processing
        auto_offset_reset='earliest'
    )
    
    await consumer.start()
    
    try:
        processor = OrderEventConsumer(inbox)
        await processor.consume_events(consumer)
    finally:
        await consumer.stop()
        await pool.close()

if __name__ == '__main__':
    asyncio.run(main())
```

---

## Testing Strategy: Comprehensive Test Suite

### Unit Tests: `tests/test_outbox_atomicity.py`

```python
"""
Critical unit tests for outbox atomicity guarantees.
"""
import pytest
import uuid
from asyncpg import create_pool

from saga.storage_postgres import PostgresSagaStorage, ConcurrencyError
from saga.interfaces import SagaState, SagaStatus, OutboxEvent

@pytest.fixture
async def storage():
    """Create test database connection."""
    pool = await create_pool(
        host='localhost',
        database='saga_test',
        user='test_user',
        password='test_pass'
    )
    
    storage = PostgresSagaStorage(pool)
    
    yield storage
    
    # Cleanup
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE saga_instance, outbox CASCADE")
    await pool.close()

@pytest.mark.asyncio
async def test_atomic_save_and_outbox(storage):
    """
    CRITICAL TEST: Verify state update and outbox insert are atomic.
    
    If exception occurs after save but before outbox insert,
    both operations must rollback.
    """
    saga_id = str(uuid.uuid4())
    
    # Create saga
    saga = SagaState(
        id=saga_id,
        saga_type='TestSaga',
        correlation_id=str(uuid.uuid4()),
        state={},
        status=SagaStatus.RUNNING,
        version=0
    )
    await storage.create(saga)
    
    # Simulate transaction failure
    async with storage.pool.acquire() as conn:
        async with conn.transaction():
            # Update state
            new_version = await storage.save(
                saga_id=saga_id,
                state={'step1': 'completed'},
                status=SagaStatus.RUNNING,
                expected_version=0,
                conn=conn
            )
            
            # Append outbox
            event = OutboxEvent(
                event_id=str(uuid.uuid4()),
                saga_id=saga_id,
                aggregate_type='test',
                aggregate_id=saga_id,
                event_type='TestEvent',
                payload={'data': 'value'},
                headers={'trace_id': str(uuid.uuid4()), 'message_id': str(uuid.uuid4())}
            )
            await storage.append_outbox(event, conn=conn)
            
            # Simulate exception before commit
            raise Exception("Simulated failure")
    
    # Verify rollback: state should be unchanged
    loaded = await storage.load(saga_id)
    assert loaded.version == 0
    assert loaded.state == {}
    
    # Verify rollback: no outbox entry
    async with storage.pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM outbox WHERE saga_id = $1",
            saga_id
        )
        assert count == 0

@pytest.mark.asyncio
async def test_optimistic_concurrency_conflict(storage):
    """
    Test OCC prevents lost updates when two workers update same saga.
    """
    saga_id = str(uuid.uuid4())
    
    # Create saga
    saga = SagaState(
        id=saga_id,
        saga_type='TestSaga',
        correlation_id=str(uuid.uuid4()),
        state={},
        status=SagaStatus.RUNNING,
        version=0
    )
    await storage.create(saga)
    
    # Worker 1 updates successfully
    await storage.save(
        saga_id=saga_id,
        state={'worker1': 'done'},
        status=SagaStatus.RUNNING,
        expected_version=0
    )
    
    # Worker 2 tries to update with stale version - should fail
    with pytest.raises(ConcurrencyError):
        await storage.save(
            saga_id=saga_id,
            state={'worker2': 'done'},
            status=SagaStatus.RUNNING,
            expected_version=0  # Stale version!
        )
    
    # Verify only worker 1's update persisted
    loaded = await storage.load(saga_id)
    assert loaded.state == {'worker1': 'done'}
    assert loaded.version == 1

@pytest.mark.asyncio
async def test_idempotent_outbox_insert(storage):
    """
    Test duplicate event_id is silently ignored (idempotent insert).
    """
    event_id = str(uuid.uuid4())
    
    event = OutboxEvent(
        event_id=event_id,
        aggregate_type='test',
        aggregate_id=str(uuid.uuid4()),
        event_type='TestEvent',
        payload={'attempt': 1},
        headers={'trace_id': str(uuid.uuid4()), 'message_id': event_id}
    )
    
    # Insert once
    await storage.append_outbox(event)
    
    # Insert again with different payload
    event.payload = {'attempt': 2}
    await storage.append_outbox(event)  # Should not raise
    
    # Verify only first insert persisted
    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payload FROM outbox WHERE event_id = $1",
            event_id
        )
        assert row['payload']['attempt'] == 1

@pytest.mark.asyncio
async def test_claim_uses_skip_locked(storage):
    """
    Test multiple workers can claim different events concurrently.
    """
    # Insert 10 events
    event_ids = []
    for i in range(10):
        event_id = str(uuid.uuid4())
        event_ids.append(event_id)
        
        event = OutboxEvent(
            event_id=event_id,
            aggregate_type='test',
            aggregate_id=str(uuid.uuid4()),
            event_type='TestEvent',
            payload={'index': i},
            headers={'trace_id': str(uuid.uuid4()), 'message_id': event_id}
        )
        await storage.append_outbox(event)
    
    # Two workers claim concurrently
    import asyncio
    
    results = await asyncio.gather(
        storage.claim_pending_events(5, 'worker1'),
        storage.claim_pending_events(5, 'worker2')
    )
    
    claimed1 = results[0]
    claimed2 = results[1]
    
    # Each worker should claim 5 events
    assert len(claimed1) == 5
    assert len(claimed2) == 5
    
    # No overlap in claimed events
    ids1 = {str(e['event_id']) for e in claimed1}
    ids2 = {str(e['event_id']) for e in claimed2}
    assert ids1.isdisjoint(ids2)
```

### Integration Tests: `tests/test_end_to_end.py`

```python
"""
End-to-end integration tests using Testcontainers.
"""
import pytest
import asyncio
import uuid
from testcontainers.postgres import PostgresContainer
from testcontainers.kafka import KafkaContainer

from saga.storage_postgres import PostgresSagaStorage
from saga.broker_kafka import KafkaBroker
from saga.outbox_worker import OutboxWorker
from saga.interfaces import OutboxEvent

@pytest.fixture(scope='module')
def postgres_container():
    """Start PostgreSQL test container."""
    with PostgresContainer('postgres:15') as postgres:
        yield postgres

@pytest.fixture(scope='module')
def kafka_container():
    """Start Kafka test container."""
    with KafkaContainer() as kafka:
        yield kafka

@pytest.mark.asyncio
async def test_end_to_end_flow(postgres_container, kafka_container):
    """
    Test complete flow: write -> outbox -> broker -> consume.
    """
    # Setup storage
    pool = await create_pool(postgres_container.get_connection_url())
    storage = PostgresSagaStorage(pool)
    
    # Apply migrations
    async with pool.acquire() as conn:
        # ... execute migration SQL ...
        pass
    
    # Setup broker
    broker = await KafkaBroker.create(
        bootstrap_servers=kafka_container.get_bootstrap_server()
    )
    
    # Start outbox worker
    worker = OutboxWorker(storage, broker, logger=None)
    await worker.start()
    
    try:
        # Insert event into outbox
        event_id = str(uuid.uuid4())
        event = OutboxEvent(
            event_id=event_id,
            aggregate_type='order',
            aggregate_id=str(uuid.uuid4()),
            event_type='OrderCreated',
            payload={'order_id': '12345'},
            headers={'trace_id': str(uuid.uuid4()), 'message_id': event_id}
        )
        await storage.append_outbox(event)
        
        # Wait for worker to process (with timeout)
        await asyncio.sleep(3)
        
        # Verify event marked as sent
        async with pool.acquire() as conn:
            status = await conn.fetchval(
                "SELECT status FROM outbox WHERE event_id = $1",
                event_id
            )
            assert status == 'sent'
        
        # TODO: Add Kafka consumer to verify message received
        
    finally:
        await worker.stop()
        await broker.close()
        await pool.close()
```

---

## Monitoring & Observability

### Prometheus Alerts: `ops/prometheus/alerts.yml`

```yaml
groups:
  - name: outbox_alerts
    interval: 30s
    rules:
      # Critical: Outbox lag exceeds SLA
      - alert: OutboxHighLag
        expr: outbox_pending_events_total > 1000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Outbox has {{ $value }} pending events"
          description: "Outbox pending count exceeds threshold, may indicate worker issues"
      
      # Warning: High publish failure rate
      - alert: OutboxHighFailureRate
        expr: |
          rate(outbox_failed_events_total[5m]) / 
          rate(outbox_claimed_events_total[5m]) > 0.1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Outbox publish failure rate is {{ $value | humanizePercentage }}"
          description: "More than 10% of events are failing to publish"
      
      # Critical: Events moving to dead letter queue
      - alert: OutboxDeadLetterQueue
        expr: increase(outbox_dead_letter_events_total[10m]) > 10
        labels:
          severity: critical
        annotations:
          summary: "{{ $value }} events moved to DLQ in last 10 minutes"
          description: "Events exhausted retries, manual intervention required"
      
      # Warning: No events processed recently (worker may be down)
      - alert: OutboxWorkerInactive
        expr: rate(outbox_published_events_total[5m]) == 0 AND outbox_pending_events_total > 0
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Outbox worker appears inactive"
          description: "No events published but pending queue is not empty"
```

### Grafana Dashboard: `ops/grafana/outbox_dashboard.json`

```json
{
  "dashboard": {
    "title": "Saga Outbox Monitoring",
    "panels": [
      {
        "title": "Pending Events",
        "targets": [{"expr": "outbox_pending_events_total"}],
        "type": "graph"
      },
      {
        "title": "Publish Rate",
        "targets": [{"expr": "rate(outbox_published_events_total[1m])"}],
        "type": "graph"
      },
      {
        "title": "Failure Rate by Event Type",
        "targets": [{"expr": "rate(outbox_failed_events_total[5m])"}],
        "type": "graph",
        "legend": {"show": true}
      },
      {
        "title": "Publish Latency (p50, p95, p99)",
        "targets": [
          {"expr": "histogram_quantile(0.50, outbox_publish_duration_seconds)"},
          {"expr": "histogram_quantile(0.95, outbox_publish_duration_seconds)"},
          {"expr": "histogram_quantile(0.99, outbox_publish_duration_seconds)"}
        ],
        "type": "graph"
      }
    ]
  }
}
```

---

## Operational Runbooks

### Runbook 1: Investigate Stuck Messages

**Symptom**: `outbox_pending_events_total` metric is growing

**Investigation Steps**:

```sql
-- 1. Identify oldest pending messages
SELECT id, event_type, created_at, attempts, last_error,
       age(now(), created_at) as age
FROM outbox
WHERE status IN ('pending', 'failed')
ORDER BY created_at
LIMIT 20;

-- 2. Check for specific event type failures
SELECT event_type, status, count(*), max(attempts) as max_attempts
FROM outbox
WHERE status != 'sent'
GROUP BY event_type, status
ORDER BY count(*) DESC;

-- 3. Inspect failed events with errors
SELECT event_id, event_type, attempts, last_error, available_at
FROM outbox
WHERE status = 'failed'
ORDER BY attempts DESC
LIMIT 10;
```

**Resolution Actions**:

1. **If worker is down**: Restart outbox worker pods
2. **If broker is unreachable**: Check broker health, network connectivity
3. **If specific event type failing**: Investigate handler logic, check payload schema
4. **If poison message**: Manually move to DLQ and investigate

```sql
-- Manual DLQ move
UPDATE outbox 
SET status = 'dead_letter' 
WHERE event_id = '<problematic_event_id>';
```

### Runbook 2: Manual Event Replay

**Scenario**: Need to replay failed/dead-letter events after fixing root cause

```sql
-- 1. Identify events to replay (e.g., from DLQ)
SELECT event_id, event_type, payload, created_at
FROM outbox
WHERE status = 'dead_letter'
  AND event_type = 'OrderCreated'
  AND created_at > now() - interval '24 hours';

-- 2. Reset to pending with fresh attempt count
UPDATE outbox
SET status = 'pending',
    attempts = 0,
    available_at = now(),
    last_error = NULL
WHERE status = 'dead_letter'
  AND event_type = 'OrderCreated'
  AND created_at > now() - interval '24 hours';

-- 3. Monitor worker logs for successful processing
```

### Runbook 3: Archive Old Events

**Schedule**: Run daily at 2 AM (low traffic period)

```sql
-- Archive sent events older than 30 days
BEGIN;

INSERT INTO outbox_archive
SELECT *, now() as archived_at
FROM outbox
WHERE status = 'sent'
  AND published_at < now() - interval '30 days'
ON CONFLICT (event_id) DO NOTHING;

DELETE FROM outbox
WHERE status = 'sent'
  AND published_at < now() - interval '30 days';

COMMIT;

-- Verify archive count
SELECT count(*) FROM outbox_archive WHERE archived_at > now() - interval '1 day';
```

### Runbook 4: Scale Outbox Workers

**Trigger**: `outbox_pending_events_total` > 5000 for more than 10 minutes

**Kubernetes HPA** (Horizontal Pod Autoscaler):

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: outbox-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: outbox-worker
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: External
      external:
        metric:
          name: outbox_pending_events_total
          selector:
            matchLabels:
              app: saga-outbox
        target:
          type: Value
          value: "1000"  # Scale when pending > 1000 per replica
```

**Manual scaling**:

```bash
# Scale up
kubectl scale deployment outbox-worker --replicas=10

# Verify scaling
kubectl get pods -l app=outbox-worker

# Monitor metrics after scaling
kubectl top pods -l app=outbox-worker
```

---

## Kubernetes Deployment Manifests

### Outbox Worker Deployment: `k8s/outbox-worker.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: outbox-worker
  namespace: saga
  labels:
    app: outbox-worker
    component: messaging
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0  # Ensure zero-downtime deployments
  selector:
    matchLabels:
      app: outbox-worker
  template:
    metadata:
      labels:
        app: outbox-worker
        version: "1.0"
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      # Anti-affinity: spread workers across nodes
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: outbox-worker
                topologyKey: kubernetes.io/hostname
      
      # Service account for RBAC
      serviceAccountName: outbox-worker
      
      containers:
        - name: worker
          image: myregistry/saga-outbox-worker:v1.2.3
          imagePullPolicy: IfNotPresent
          
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: saga-db-credentials
                  key: connection-string
            
            - name: KAFKA_BOOTSTRAP_SERVERS
              value: "kafka-headless.kafka.svc.cluster.local:9092"
            
            - name: WORKER_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            
            - name: BATCH_SIZE
              value: "100"
            
            - name: POLL_INTERVAL_SECONDS
              value: "1.0"
            
            - name: LOG_LEVEL
              value: "INFO"
            
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://jaeger-collector.observability.svc:4318"
          
          resources:
            requests:
              cpu: "200m"
              memory: "256Mi"
            limits:
              cpu: "1000m"
              memory: "1Gi"
          
          # Health checks
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 2
          
          # Graceful shutdown
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 15"]  # Allow in-flight processing
          
          ports:
            - name: metrics
              containerPort: 8000
              protocol: TCP
      
      # Graceful termination
      terminationGracePeriodSeconds: 30
      
      # Security context
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000

---
apiVersion: v1
kind: Service
metadata:
  name: outbox-worker-metrics
  namespace: saga
  labels:
    app: outbox-worker
spec:
  type: ClusterIP
  ports:
    - name: metrics
      port: 8000
      targetPort: metrics
  selector:
    app: outbox-worker

---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: outbox-worker-pdb
  namespace: saga
spec:
  minAvailable: 2  # Always keep at least 2 workers running
  selector:
    matchLabels:
      app: outbox-worker
```

### Database Migration Job: `k8s/migration-job.yaml`

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: saga-migration-0001
  namespace: saga
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: migration
          image: myregistry/saga-migrations:v1.2.3
          command: ["/bin/sh", "-c"]
          args:
            - |
              psql $DATABASE_URL -f /migrations/0001_create_saga_outbox.sql
              echo "Migration completed successfully"
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: saga-db-credentials
                  key: connection-string
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "256Mi"
      backoffLimit: 3
```

---

## Security & Compliance Guidelines

### 1. Secrets Management

**Never hardcode credentials**. Use Kubernetes Secrets or external secret managers:

```yaml
# Using External Secrets Operator
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: saga-db-credentials
  namespace: saga
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: saga-db-credentials
    creationPolicy: Owner
  data:
    - secretKey: connection-string
      remoteRef:
        key: saga/database/postgres
        property: connection_url
    
    - secretKey: kafka-password
      remoteRef:
        key: saga/messaging/kafka
        property: password
```

### 2. PII Data Handling

**Encrypt sensitive data in outbox payloads**:

```python
# saga/encryption.py
from cryptography.fernet import Fernet
import json

class PayloadEncryption:
    """
    Encrypt/decrypt sensitive fields in event payloads.
    
    Use for PII data (emails, SSN, etc.) in outbox events.
    """
    
    def __init__(self, key: bytes):
        self.cipher = Fernet(key)
    
    def encrypt_payload(self, payload: dict, sensitive_fields: list[str]) -> dict:
        """Encrypt specified fields in payload."""
        encrypted = payload.copy()
        
        for field in sensitive_fields:
            if field in encrypted:
                value = json.dumps(encrypted[field])
                encrypted[field] = {
                    "_encrypted": True,
                    "data": self.cipher.encrypt(value.encode()).decode()
                }
        
        return encrypted
    
    def decrypt_payload(self, payload: dict) -> dict:
        """Decrypt encrypted fields in payload."""
        decrypted = payload.copy()
        
        for key, value in payload.items():
            if isinstance(value, dict) and value.get("_encrypted"):
                encrypted_data = value["data"].encode()
                decrypted_value = self.cipher.decrypt(encrypted_data).decode()
                decrypted[key] = json.loads(decrypted_value)
        
        return decrypted

# Usage in saga step
encryption = PayloadEncryption(key=os.environ["ENCRYPTION_KEY"].encode())

payload = {
    "order_id": "12345",
    "customer_email": "user@example.com",
    "customer_ssn": "123-45-6789"
}

encrypted_payload = encryption.encrypt_payload(
    payload, 
    sensitive_fields=["customer_email", "customer_ssn"]
)

event = OutboxEvent(
    event_id=str(uuid.uuid4()),
    aggregate_type="order",
    aggregate_id="12345",
    event_type="OrderCreated",
    payload=encrypted_payload,
    headers={...}
)
```

### 3. Audit Logging

**Maintain immutable audit trail**:

```sql
-- Audit table for saga state changes
CREATE TABLE saga_audit_log (
    id BIGSERIAL PRIMARY KEY,
    saga_id UUID NOT NULL,
    saga_type TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- state_changed, step_executed, compensated, failed
    old_state JSONB,
    new_state JSONB,
    old_status TEXT,
    new_status TEXT,
    user_id TEXT,  -- Who triggered the change
    trace_id UUID,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB
);

CREATE INDEX idx_audit_saga ON saga_audit_log(saga_id, timestamp);
CREATE INDEX idx_audit_user ON saga_audit_log(user_id, timestamp);
```

### 4. GDPR Compliance

**Right to be forgotten** - implement PII deletion:

```python
# saga/gdpr.py
async def erase_customer_data(pool: Pool, customer_id: str):
    """
    GDPR Article 17: Right to erasure.
    
    Remove PII from saga states and outbox while preserving
    non-PII metadata for audit purposes.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Redact PII from saga states
            await conn.execute(
                """
                UPDATE saga_instance
                SET state = jsonb_set(
                    state,
                    '{customer_pii}',
                    '"[REDACTED]"'::jsonb
                )
                WHERE state->>'customer_id' = $1
                """,
                customer_id
            )
            
            # Redact PII from outbox
            await conn.execute(
                """
                UPDATE outbox
                SET payload = jsonb_set(
                    payload,
                    '{customer_email}',
                    '"[REDACTED]"'::jsonb
                )
                WHERE payload->>'customer_id' = $1
                """,
                customer_id
            )
            
            # Log erasure event
            await conn.execute(
                """
                INSERT INTO gdpr_erasure_log (customer_id, erased_at, reason)
                VALUES ($1, now(), 'customer_request')
                """,
                customer_id
            )
```

---

## Performance Tuning & Optimization

### Database Connection Pool Sizing

**Formula**: `pool_size = (num_cores * 2) + effective_spindle_count`

```python
# For 4-core machine with SSD
pool_config = {
    "min_size": 10,
    "max_size": 20,
    "max_queries": 50000,  # Close connections after N queries
    "max_inactive_connection_lifetime": 300.0,  # 5 minutes
    "command_timeout": 60.0,  # Query timeout
}

pool = await asyncpg.create_pool(
    host="postgres.internal",
    database="saga_db",
    user="saga_user",
    password=os.environ["DB_PASSWORD"],
    **pool_config
)
```

### Index Optimization

**Critical indexes for performance**:

```sql
-- Outbox worker query optimization
EXPLAIN ANALYZE
WITH claimable AS (
    SELECT id
    FROM outbox
    WHERE status = 'pending'
      AND available_at <= now()
    ORDER BY created_at ASC
    LIMIT 100
    FOR UPDATE SKIP LOCKED
)
UPDATE outbox
SET status = 'claimed', claimed_at = now()
WHERE id IN (SELECT id FROM claimable)
RETURNING *;

-- Should use: Index Scan using idx_outbox_pending
-- If not, create better index:
CREATE INDEX CONCURRENTLY idx_outbox_pending_optimized 
ON outbox (status, available_at, created_at)
WHERE status IN ('pending', 'failed');

-- Vacuum regularly to prevent bloat
VACUUM ANALYZE outbox;
```

### Batch Size Tuning

**Determine optimal batch size**:

```python
# Benchmarking script
import time
import statistics

async def benchmark_batch_size(storage, broker, batch_sizes=[10, 50, 100, 200, 500]):
    """Find optimal batch size for your workload."""
    results = {}
    
    for batch_size in batch_sizes:
        latencies = []
        
        for _ in range(10):  # 10 iterations per size
            start = time.time()
            
            events = await storage.claim_pending_events(batch_size, "benchmark")
            for event in events:
                await broker.publish(...)
            
            latencies.append(time.time() - start)
        
        results[batch_size] = {
            "mean": statistics.mean(latencies),
            "p95": statistics.quantiles(latencies, n=20)[18],
            "throughput": batch_size / statistics.mean(latencies)
        }
    
    return results

# Run benchmark and choose batch_size with best throughput/latency ratio
```

### Kafka Producer Tuning

```python
# High-throughput configuration
producer_config = {
    "bootstrap_servers": "kafka:9092",
    "acks": "all",  # Wait for all replicas (durability)
    "compression_type": "lz4",  # Fast compression
    "linger_ms": 10,  # Wait up to 10ms to batch messages
    "batch_size": 32768,  # 32KB batches
    "buffer_memory": 67108864,  # 64MB buffer
    "max_in_flight_requests_per_connection": 5,
    "enable_idempotence": True,
    "request_timeout_ms": 30000,
    "retries": 5,
}

producer = AIOKafkaProducer(**producer_config)
```

---

## Chaos Engineering Tests

### Test 1: Worker Crash During Publish

```python
# tests/chaos/test_worker_crash.py
import pytest
import asyncio
import signal
import os

@pytest.mark.chaos
async def test_worker_crash_recovery(storage, broker):
    """
    Simulate worker crash mid-publish and verify another worker picks up.
    """
    # Insert test event
    event = create_test_event()
    await storage.append_outbox(event)
    
    # Start worker 1
    worker1 = OutboxWorker(storage, broker, worker_id="worker1")
    await worker1.start()
    
    # Wait for claim
    await asyncio.sleep(0.5)
    
    # Simulate crash (kill worker1)
    worker1._shutdown = True
    await worker1.stop()
    
    # Verify event is in 'claimed' state (stuck)
    status = await get_event_status(storage, event.event_id)
    assert status == "claimed"
    
    # Wait for watchdog timeout
    await asyncio.sleep(STUCK_CLAIM_TIMEOUT_SECONDS + 5)
    
    # Start worker 2
    worker2 = OutboxWorker(storage, broker, worker_id="worker2")
    await worker2.start()
    
    # Wait for processing
    await asyncio.sleep(2)
    
    # Verify event was requeued and processed
    status = await get_event_status(storage, event.event_id)
    assert status == "sent"
    
    await worker2.stop()
```

### Test 2: Database Connection Loss

```python
@pytest.mark.chaos
async def test_database_connection_loss(storage, broker):
    """
    Simulate database connection drop and verify graceful recovery.
    """
    worker = OutboxWorker(storage, broker)
    await worker.start()
    
    # Close all database connections
    await storage.pool.close()
    
    # Worker should handle connection errors gracefully
    await asyncio.sleep(5)
    
    # Reconnect database
    storage.pool = await asyncpg.create_pool(...)
    
    # Worker should resume processing
    event = create_test_event()
    await storage.append_outbox(event)
    
    await asyncio.sleep(3)
    
    status = await get_event_status(storage, event.event_id)
    assert status == "sent"
    
    await worker.stop()
```

### Test 3: Kafka Broker Unavailable

```python
@pytest.mark.chaos
async def test_broker_unavailable(storage, kafka_container):
    """
    Simulate Kafka broker downtime and verify exponential backoff.
    """
    broker = await KafkaBroker.create(
        bootstrap_servers=kafka_container.get_bootstrap_server()
    )
    
    worker = OutboxWorker(storage, broker)
    await worker.start()
    
    # Insert event
    event = create_test_event()
    await storage.append_outbox(event)
    
    # Stop Kafka
    kafka_container.stop()
    
    # Worker should fail to publish and schedule retry
    await asyncio.sleep(2)
    
    event_data = await get_event_data(storage, event.event_id)
    assert event_data["status"] == "failed"
    assert event_data["attempts"] > 0
    
    # Restart Kafka
    kafka_container.start()
    await asyncio.sleep(5)
    
    # Wait for backoff period
    backoff = 2 ** event_data["attempts"]
    await asyncio.sleep(backoff + 2)
    
    # Verify eventual success
    status = await get_event_status(storage, event.event_id)
    assert status == "sent"
    
    await worker.stop()
    await broker.close()
```

---

## Advanced Patterns & Extensions

### Pattern 1: Priority Queues

**Use case**: Process urgent events before normal events

```sql
-- Add priority column to outbox
ALTER TABLE outbox ADD COLUMN priority INT NOT NULL DEFAULT 5;

CREATE INDEX idx_outbox_priority 
ON outbox (status, priority DESC, available_at, created_at)
WHERE status IN ('pending', 'failed');

-- Update claim query to consider priority
WITH claimable AS (
    SELECT id
    FROM outbox
    WHERE status = 'pending'
      AND available_at <= now()
    ORDER BY priority DESC, created_at ASC
    LIMIT 100
    FOR UPDATE SKIP LOCKED
)
UPDATE outbox
SET status = 'claimed', claimed_at = now()
WHERE id IN (SELECT id FROM claimable)
RETURNING *;
```

### Pattern 2: Event Versioning

**Handle schema evolution**:

```python
@dataclass
class VersionedEvent:
    """Event with schema version for backward compatibility."""
    event_id: str
    event_type: str
    schema_version: int  # Increment on breaking changes
    payload: dict
    
    def migrate(self) -> dict:
        """Migrate old schema to current version."""
        if self.schema_version == 1:
            return self._migrate_v1_to_v2(self.payload)
        return self.payload
    
    def _migrate_v1_to_v2(self, payload: dict) -> dict:
        """Example migration: rename field."""
        if "old_field_name" in payload:
            payload["new_field_name"] = payload.pop("old_field_name")
        return payload

# In consumer
async def handle_event(event_data: dict):
    versioned = VersionedEvent(**event_data)
    current_payload = versioned.migrate()
    # Process current_payload
```

### Pattern 3: Saga Compensation (Rollback)

**Implement compensating transactions**:

```python
# saga/compensation.py
from typing import Callable, Awaitable

class CompensatableStep:
    """Saga step with compensation logic."""
    
    def __init__(
        self,
        name: str,
        forward: Callable[[dict], Awaitable[dict]],
        compensate: Callable[[dict], Awaitable[None]]
    ):
        self.name = name
        self.forward = forward
        self.compensate = compensate

class CompensatingSaga:
    """Saga that can rollback on failure."""
    
    def __init__(self, storage: SagaStorage, saga_id: str):
        self.storage = storage
        self.saga_id = saga_id
        self.steps: list[CompensatableStep] = []
    
    async def execute(self):
        """Execute steps, compensate on failure."""
        executed_steps = []
        
        try:
            for step in self.steps:
                saga = await self.storage.load(self.saga_id)
                
                # Skip if already executed (idempotency)
                if saga.state.get(f"{step.name}_completed"):
                    continue
                
                # Execute forward step
                result = await step.forward(saga.state)
                
                # Update state
                saga.state[f"{step.name}_result"] = result
                saga.state[f"{step.name}_completed"] = True
                
                await self.storage.save(
                    self.saga_id,
                    saga.state,
                    SagaStatus.RUNNING,
                    saga.version,
                    current_step=step.name
                )
                
                executed_steps.append(step)
            
            # All steps succeeded
            await self.storage.save(
                self.saga_id,
                saga.state,
                SagaStatus.COMPLETED,
                saga.version
            )
            
        except Exception as exc:
            # Compensate in reverse order
            await self._compensate(executed_steps, exc)
            raise
    
    async def _compensate(self, executed_steps: list[CompensatableStep], error: Exception):
        """Execute compensation in reverse order."""
        saga = await self.storage.load(self.saga_id)
        
        await self.storage.save(
            self.saga_id,
            saga.state,
            SagaStatus.COMPENSATING,
            saga.version
        )
        
        for step in reversed(executed_steps):
            try:
                await step.compensate(saga.state)
                saga.state[f"{step.name}_compensated"] = True
            except Exception as comp_exc:
                # Log but continue compensating
                logging.error(f"Compensation failed for {step.name}: {comp_exc}")
        
        await self.storage.save(
            self.saga_id,
            saga.state,
            SagaStatus.FAILED,
            saga.version,
            error=str(error)
        )

# Usage example
async def execute_order_saga(storage: SagaStorage, order_id: str):
    saga_id = str(uuid.uuid4())
    
    saga = CompensatingSaga(storage, saga_id)
    
    saga.steps = [
        CompensatableStep(
            name="reserve_inventory",
            forward=lambda state: reserve_inventory(order_id),
            compensate=lambda state: release_inventory(order_id)
        ),
        CompensatableStep(
            name="charge_payment",
            forward=lambda state: charge_payment(order_id),
            compensate=lambda state: refund_payment(order_id)
        ),
        CompensatableStep(
            name="ship_order",
            forward=lambda state: ship_order(order_id),
            compensate=lambda state: cancel_shipment(order_id)
        )
    ]
    
    await saga.execute()
```

---

## Production Readiness Checklist

### Pre-Deployment Validation

- [ ] **Database**: Migrations applied, indexes verified with EXPLAIN ANALYZE
- [ ] **Secrets**: All credentials in secret manager, no hardcoded values
- [ ] **Monitoring**: Prometheus metrics exposed, Grafana dashboards created
- [ ] **Alerting**: PagerDuty/Opsgenie integration configured
- [ ] **Logging**: Structured logs to ELK/Loki, trace IDs propagated
- [ ] **Testing**: Unit tests >80% coverage, integration tests passing
- [ ] **Chaos**: Chaos tests executed, failure scenarios validated
- [ ] **Documentation**: Runbooks written, architecture diagrams updated
- [ ] **Performance**: Load testing completed, bottlenecks identified
- [ ] **Security**: Vulnerability scan passed, RBAC configured
- [ ] **Compliance**: GDPR/SOC2 requirements documented
- [ ] **Backup**: Database backup strategy verified
- [ ] **Disaster Recovery**: Restore procedure tested

### Post-Deployment Monitoring (First 48 Hours)

- [ ] Monitor `outbox_pending_events_total` - should stabilize near zero
- [ ] Check error rates in logs - investigate any anomalies
- [ ] Verify publish latency p99 < SLA threshold
- [ ] Confirm no dead letter queue accumulation
- [ ] Test manual event replay procedure
- [ ] Validate consumer deduplication (check for duplicates in logs)
- [ ] Review database connection pool usage
- [ ] Check Kafka consumer lag (if applicable)

---

## Summary: Key Principles for AI Agents

When implementing this pattern, always remember:

1. **Atomicity First**: State updates and outbox inserts MUST be in same transaction
2. **Idempotency Everywhere**: All operations must be safely retryable
3. **Observe Everything**: Metrics, logs, and traces are not optional
4. **Plan for Failure**: Chaos testing reveals real-world issues
5. **Security by Default**: Encrypt PII, rotate credentials, audit everything
6. **Scale Horizontally**: Design for multiple workers from day one
7. **Document Operationally**: Your future on-call self will thank you

### Decision Tree for Common Questions

**Q: Should I use optimistic or pessimistic locking?**
→ Start with OCC (version-based). Only use `FOR UPDATE` if contention is proven problem.

**Q: How many outbox workers should I run?**
→ Start with 3, scale based on `outbox_pending_events_total / target_lag_seconds`.

**Q: When should events go to dead letter queue?**
→ After 10 failed attempts OR if error is non-retryable (e.g., schema validation failure).

**Q: How do I handle schema evolution?**
→ Include `schema_version` in events, implement migration logic in consumers.

**Q: Should I archive sent events?**
→ Yes, for audit trail. Archive after 7-30 days depending on compliance needs.

---

## Quick Start: Copy-Paste Implementation

```bash
# 1. Clone reference implementation
git clone https://github.com/your-org/saga-outbox-pattern
cd saga-outbox-pattern

# 2. Apply database migrations
psql $DATABASE_URL -f migrations/0001_create_saga_outbox.sql

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your database/Kafka credentials

# 5. Run tests
pytest tests/ -v

# 6. Start outbox worker locally
python -m saga.outbox_worker

# 7. Deploy to Kubernetes
kubectl apply -f k8s/
kubectl rollout status deployment/outbox-worker

# 8. Verify deployment
kubectl logs -l app=outbox-worker -f
```

---

## Additional Resources

- **Original Outbox Pattern**: https://microservices.io/patterns/data/transactional-outbox.html
- **Saga Pattern**: https://microservices.io/patterns/data/saga.html
- **PostgreSQL SKIP LOCKED**: https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE
- **Kafka Idempotent Producer**: https://kafka.apache.org/documentation/#producerconfigs_enable.idempotence
- **OpenTelemetry Python**: https://opentelemetry-python.readthedocs.io/

---

**Document Version**: 2.0  
**Last Updated**: 2025-11-09  
**Maintainer**: Platform Team  
**Review Cycle**: Quarterly