"""
DDL for the PostgreSQL outbox tables (``saga_outbox``, its archive and the
consumer inbox), applied idempotently by ``PostgreSQLOutboxStorage.initialize``.
"""

# SQL for creating the outbox schema
OUTBOX_SCHEMA = """
-- Outbox table for pending messages
CREATE TABLE IF NOT EXISTS saga_outbox (
    event_id        UUID PRIMARY KEY,
    saga_id         VARCHAR(255) NOT NULL,
    aggregate_type  VARCHAR(255) NOT NULL DEFAULT 'saga',
    aggregate_id    VARCHAR(255) NOT NULL,
    event_type      VARCHAR(255) NOT NULL,
    payload         JSONB NOT NULL,
    headers         JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at      TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    worker_id       VARCHAR(255),
    dead_letter_at  TIMESTAMPTZ,
    dead_letter_reason TEXT,
    error_type      VARCHAR(255),
    error_classification VARCHAR(255),
    error_fingerprint VARCHAR(255),
    replay_count    INTEGER NOT NULL DEFAULT 0,
    routing_key     VARCHAR(255),
    partition_key   VARCHAR(255),

    -- Indexes for common queries
    CONSTRAINT valid_status CHECK (
        status IN ('pending', 'claimed', 'sent', 'failed', 'dead_letter')
    )
);

-- Index for claiming pending events efficiently
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON saga_outbox (created_at)
    WHERE status = 'pending';

-- Index for finding stuck events
CREATE INDEX IF NOT EXISTS idx_outbox_claimed_at
    ON saga_outbox (claimed_at)
    WHERE status = 'claimed';

-- Index for looking up events by saga
CREATE INDEX IF NOT EXISTS idx_outbox_saga_id
    ON saga_outbox (saga_id);

-- Archive table for sent events (optional partitioning)
CREATE TABLE IF NOT EXISTS saga_outbox_archive (
    LIKE saga_outbox INCLUDING ALL
);

-- Consumer inbox table for idempotent processing
CREATE TABLE IF NOT EXISTS consumer_inbox (
    event_id            UUID PRIMARY KEY,
    consumer_name       VARCHAR(255) NOT NULL,
    source_topic        VARCHAR(255) NOT NULL,
    event_type          VARCHAR(255) NOT NULL,
    payload             JSONB NOT NULL,
    consumed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_duration_ms INTEGER
);

-- Index for cleanup queries
CREATE INDEX IF NOT EXISTS idx_consumer_inbox_cleanup
    ON consumer_inbox (consumer_name, consumed_at);

ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS dead_letter_at TIMESTAMPTZ;
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT;
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS error_type VARCHAR(255);
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS error_classification VARCHAR(255);
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS error_fingerprint VARCHAR(255);
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS replay_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS routing_key VARCHAR(255);
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS partition_key VARCHAR(255);
ALTER TABLE saga_outbox_archive ADD COLUMN IF NOT EXISTS routing_key VARCHAR(255);
ALTER TABLE saga_outbox_archive ADD COLUMN IF NOT EXISTS partition_key VARCHAR(255);
"""
