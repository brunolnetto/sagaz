-- ============================================================================
-- Migration: Create Partitioned Tables
-- Description: Create partitioned versions of core Sagaz tables for scalability
-- Version: 1.1.0
-- ============================================================================

BEGIN;

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- ============================================================================
-- 1. Partitioned Saga Executions Table (Monthly Partitions)
-- ============================================================================

CREATE TABLE IF NOT EXISTS saga_executions (
    saga_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    saga_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    context JSONB DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP,
    idempotency_key VARCHAR(255),
    
    -- Constraints
    CONSTRAINT saga_status_check CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'COMPENSATING', 'COMPENSATED'))
) PARTITION BY RANGE (created_at);

-- Indexes on parent table (will be inherited by partitions)
CREATE INDEX IF NOT EXISTS idx_saga_executions_status_created 
    ON saga_executions (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saga_executions_name_created 
    ON saga_executions (saga_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saga_executions_idempotency 
    ON saga_executions (idempotency_key) 
    WHERE idempotency_key IS NOT NULL;

COMMENT ON TABLE saga_executions IS 'Partitioned saga execution state (monthly partitions)';

-- ============================================================================
-- 2. Partitioned Saga Outbox Table (Daily Partitions)
-- ============================================================================

CREATE TABLE IF NOT EXISTS saga_outbox (
    id BIGSERIAL,
    event_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    saga_id UUID,
    topic VARCHAR(255) NOT NULL,
    partition_key VARCHAR(255),
    payload JSONB NOT NULL,
    headers JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    published_at TIMESTAMP,
    error TEXT,
    
    -- Primary key includes partition key
    PRIMARY KEY (id, created_at),
    
    -- Unique constraint on event_id per partition
    UNIQUE (event_id, created_at),
    
    -- Constraints
    CONSTRAINT outbox_status_check CHECK (status IN ('PENDING', 'PUBLISHED', 'FAILED', 'DEAD_LETTER'))
) PARTITION BY RANGE (created_at);

-- Indexes on parent table
CREATE INDEX IF NOT EXISTS idx_saga_outbox_status_created 
    ON saga_outbox (status, created_at) 
    WHERE status = 'PENDING';

CREATE INDEX IF NOT EXISTS idx_saga_outbox_saga_id 
    ON saga_outbox (saga_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saga_outbox_topic 
    ON saga_outbox (topic, created_at DESC);

COMMENT ON TABLE saga_outbox IS 'Partitioned transactional outbox (daily partitions)';

-- ============================================================================
-- 3. Consumer Inbox Table (NOT partitioned - needs fast PK lookups)
-- ============================================================================

CREATE TABLE IF NOT EXISTS consumer_inbox (
    event_id UUID PRIMARY KEY,
    consumer_name VARCHAR(255) NOT NULL,
    source_topic VARCHAR(255) NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    processed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    result JSONB,
    
    -- Composite unique constraint
    UNIQUE (consumer_name, event_id)
);

CREATE INDEX IF NOT EXISTS idx_consumer_inbox_consumer_processed 
    ON consumer_inbox (consumer_name, processed_at DESC);

CREATE INDEX IF NOT EXISTS idx_consumer_inbox_topic_processed 
    ON consumer_inbox (source_topic, processed_at DESC);

COMMENT ON TABLE consumer_inbox IS 'Idempotency table for exactly-once processing (NOT partitioned)';

-- ============================================================================
-- 4. Saga Steps Table (Join table for step execution history)
-- ============================================================================

CREATE TABLE IF NOT EXISTS saga_steps (
    id BIGSERIAL PRIMARY KEY,
    saga_id UUID NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    input JSONB,
    output JSONB,
    error TEXT,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP,
    retry_count INT NOT NULL DEFAULT 0,
    
    -- Foreign key to saga_executions (partition-aware)
    -- Note: Cannot enforce FK on partitioned table directly
    -- Consider using triggers or application-level integrity
    
    CONSTRAINT step_status_check CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'COMPENSATING', 'COMPENSATED'))
);

CREATE INDEX IF NOT EXISTS idx_saga_steps_saga_id 
    ON saga_steps (saga_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_saga_steps_status 
    ON saga_steps (status, started_at DESC);

COMMENT ON TABLE saga_steps IS 'Individual saga step execution history';

-- ============================================================================
-- 5. Partition Metadata Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS partition_metadata (
    table_name VARCHAR(255) NOT NULL,
    partition_name VARCHAR(255) NOT NULL,
    partition_start TIMESTAMP NOT NULL,
    partition_end TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    PRIMARY KEY (table_name, partition_name)
);

CREATE INDEX IF NOT EXISTS idx_partition_metadata_table_range 
    ON partition_metadata (table_name, partition_start DESC);

COMMENT ON TABLE partition_metadata IS 'Tracks created partitions for maintenance';

-- ============================================================================
-- 6. Audit Log Table (Analytics - for read replicas)
-- ============================================================================

CREATE TABLE IF NOT EXISTS saga_audit_log (
    id BIGSERIAL PRIMARY KEY,
    saga_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

CREATE INDEX IF NOT EXISTS idx_saga_audit_log_saga_id 
    ON saga_audit_log (saga_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saga_audit_log_event_type 
    ON saga_audit_log (event_type, created_at DESC);

COMMENT ON TABLE saga_audit_log IS 'Audit trail for saga events (monthly partitions)';

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

\echo '✅ Partitioned tables created successfully!'
\echo ''
\echo 'Tables created:'
\echo '  - saga_executions (partitioned by created_at, monthly)'
\echo '  - saga_outbox (partitioned by created_at, daily)'
\echo '  - consumer_inbox (NOT partitioned)'
\echo '  - saga_steps (regular table)'
\echo '  - partition_metadata (tracking table)'
\echo '  - saga_audit_log (partitioned by created_at, monthly)'
\echo ''
\echo 'Next: Run 002_partition_maintenance_functions.sql'
