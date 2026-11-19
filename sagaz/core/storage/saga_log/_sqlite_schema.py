"""SQLite DDL of the unified saga log (ADR-041): same model as PostgreSQL, no RLS."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS saga_participant (
    tenant_id TEXT NOT NULL, name TEXT NOT NULL, region TEXT, owner TEXT, db_role TEXT,
    PRIMARY KEY (tenant_id, name)
);
CREATE TABLE IF NOT EXISTS saga_transaction (
    tenant_id TEXT NOT NULL, transaction_id TEXT NOT NULL, flow TEXT NOT NULL,
    coordination TEXT NOT NULL, status TEXT NOT NULL, initiator TEXT,
    started_at TEXT NOT NULL, ended_at TEXT, context TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, transaction_id)
);
CREATE TABLE IF NOT EXISTS saga_activity (
    tenant_id TEXT NOT NULL, transaction_id TEXT NOT NULL, activity_id TEXT NOT NULL,
    participant TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1, region TEXT, triggered_by TEXT, result TEXT,
    error TEXT, started_at TEXT, ended_at TEXT, duration_ms REAL,
    PRIMARY KEY (tenant_id, transaction_id, activity_id)
);
CREATE TABLE IF NOT EXISTS saga_log_event (
    tenant_id TEXT NOT NULL, transaction_id TEXT NOT NULL, sequence INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL, kind TEXT NOT NULL,
    source TEXT, causation_id TEXT, payload TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL, event_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, transaction_id, sequence)
);
CREATE TABLE IF NOT EXISTS saga_snapshot (
    tenant_id TEXT NOT NULL, transaction_id TEXT NOT NULL, kind TEXT NOT NULL,
    sequence INTEGER NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, transaction_id, kind, sequence)
);
CREATE TABLE IF NOT EXISTS saga_delivery (
    tenant_id TEXT NOT NULL, participant TEXT NOT NULL, event_id TEXT NOT NULL,
    consumed_at TEXT NOT NULL, PRIMARY KEY (tenant_id, participant, event_id)
);
CREATE TABLE IF NOT EXISTS saga_deadline (
    tenant_id TEXT NOT NULL, transaction_id TEXT NOT NULL, owner TEXT NOT NULL,
    due_at TEXT NOT NULL, claimed_until TEXT,
    PRIMARY KEY (tenant_id, transaction_id, owner)
);
CREATE TABLE IF NOT EXISTS saga_export_cursor (
    name TEXT PRIMARY KEY, position TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""
