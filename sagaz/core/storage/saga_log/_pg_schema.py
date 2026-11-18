"""PostgreSQL DDL of the unified saga log (ADR-041).

Every table is tenant-scoped with the ADR-020 row-level security policy. On top
of it, a restrictive policy isolates writes by participant: a database role
registered as a participant's ``db_role`` in ``saga_participant`` may only
write rows of that participant (its activities, the events it publishes, its
deliveries, the deadlines it owns and the transactions it initiates). Roles not
registered as a participant (the platform: coordinators, the tracker,
migrations, operators) are not restricted. See :func:`service_role_grants` for
the matching privileges.
"""

from __future__ import annotations

from sagaz.core.storage.backends.postgresql._tenancy import tenant_isolation_sql

#: Table -> the column naming the participant that owns a row.
OWNER_COLUMN = {
    "saga_transaction": "initiator",
    "saga_activity": "participant",
    "saga_log_event": "source",
    "saga_delivery": "participant",
    "saga_deadline": "owner",
}

TABLES_SQL = """
CREATE TABLE IF NOT EXISTS saga_participant (
    tenant_id  TEXT NOT NULL DEFAULT 'default',
    name       TEXT NOT NULL,
    region     TEXT,
    owner      TEXT,
    db_role    TEXT,
    PRIMARY KEY (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS idx_saga_participant_role ON saga_participant (db_role);

CREATE TABLE IF NOT EXISTS saga_transaction (
    tenant_id       TEXT        NOT NULL DEFAULT 'default',
    transaction_id  TEXT        NOT NULL,
    flow            TEXT        NOT NULL,
    coordination    TEXT        NOT NULL CHECK (coordination IN ('orchestrated', 'choreographed')),
    status          TEXT        NOT NULL,
    initiator       TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    context         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    version         INTEGER     NOT NULL DEFAULT 1,
    updated_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, transaction_id)
);
CREATE INDEX IF NOT EXISTS idx_saga_transaction_flow
    ON saga_transaction (tenant_id, flow, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_saga_transaction_status ON saga_transaction (status);

CREATE TABLE IF NOT EXISTS saga_activity (
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    transaction_id  TEXT NOT NULL,
    activity_id     TEXT NOT NULL,
    participant     TEXT NOT NULL,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 1,
    region          TEXT,
    triggered_by    TEXT,
    result          JSONB,
    error           TEXT,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    duration_ms     DOUBLE PRECISION,
    PRIMARY KEY (tenant_id, transaction_id, activity_id)
);
CREATE INDEX IF NOT EXISTS idx_saga_activity_participant
    ON saga_activity (tenant_id, participant, status);

CREATE TABLE IF NOT EXISTS saga_log_event (
    tenant_id       TEXT        NOT NULL DEFAULT 'default',
    transaction_id  TEXT        NOT NULL,
    sequence        BIGINT      NOT NULL,
    event_id        TEXT        NOT NULL UNIQUE,
    event_type      TEXT        NOT NULL,
    kind            TEXT        NOT NULL
        CHECK (kind IN ('lifecycle', 'business', 'compensate', 'compensated')),
    source          TEXT,
    causation_id    TEXT,
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    occurred_at     TIMESTAMPTZ NOT NULL,
    event_version   INTEGER     NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, transaction_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_saga_log_event_type ON saga_log_event (event_type, occurred_at);

CREATE TABLE IF NOT EXISTS saga_snapshot (
    tenant_id       TEXT        NOT NULL DEFAULT 'default',
    transaction_id  TEXT        NOT NULL,
    kind            TEXT        NOT NULL CHECK (kind IN ('projection', 'replay')),
    sequence        BIGINT      NOT NULL,
    state           JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, transaction_id, kind, sequence)
);

CREATE TABLE IF NOT EXISTS saga_delivery (
    tenant_id    TEXT        NOT NULL DEFAULT 'default',
    participant  TEXT        NOT NULL,
    event_id     TEXT        NOT NULL,
    consumed_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, participant, event_id)
);

CREATE TABLE IF NOT EXISTS saga_deadline (
    tenant_id       TEXT        NOT NULL DEFAULT 'default',
    transaction_id  TEXT        NOT NULL,
    owner           TEXT        NOT NULL,
    due_at          TIMESTAMPTZ NOT NULL,
    claimed_until   TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, transaction_id, owner)
);
CREATE INDEX IF NOT EXISTS idx_saga_deadline_due ON saga_deadline (due_at);

DO $$ BEGIN
    IF to_regclass('saga_outbox') IS NOT NULL THEN
        ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS log_event_id TEXT;
    END IF;
END $$;

-- Whether the connected role may write rows owned by participant p: platform
-- roles (not registered as any participant's db_role) always may; a service
-- role only for its own participant(s). SECURITY DEFINER so it can read the
-- registry whatever the caller's grants; inside it current_user is the owner,
-- so the caller is session_user (the role the service logged in as).
CREATE OR REPLACE FUNCTION sagaz_may_write_as(p TEXT) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
    SELECT NOT EXISTS (SELECT 1 FROM saga_participant WHERE db_role = session_user)
        OR EXISTS (SELECT 1 FROM saga_participant WHERE db_role = session_user AND name = p)
$fn$;
"""


def _participant_policies(table: str, column: str) -> str:
    name = "sagaz_participant_writes"
    check = f"sagaz_may_write_as({column})"
    return f"""
    DROP POLICY IF EXISTS {name}_insert ON {table};
    CREATE POLICY {name}_insert ON {table} AS RESTRICTIVE FOR INSERT WITH CHECK ({check});
    DROP POLICY IF EXISTS {name}_update ON {table};
    CREATE POLICY {name}_update ON {table} AS RESTRICTIVE FOR UPDATE
        USING ({check}) WITH CHECK ({check});
    DROP POLICY IF EXISTS {name}_delete ON {table};
    CREATE POLICY {name}_delete ON {table} AS RESTRICTIVE FOR DELETE USING ({check});
    """


def _participant_registry_isolation() -> str:
    # Tenant-scoped without FORCE: the owner (the platform role that runs the
    # schema and owns sagaz_may_write_as) reads every tenant's registry.
    return tenant_isolation_sql("saga_participant").replace(
        "ALTER TABLE saga_participant FORCE ROW LEVEL SECURITY;",
        "ALTER TABLE saga_participant NO FORCE ROW LEVEL SECURITY;",
    )


SCHEMA_SQL = (
    TABLES_SQL
    + _participant_registry_isolation()
    + "".join(
        tenant_isolation_sql(table)
        for table in (
            "saga_transaction",
            "saga_activity",
            "saga_log_event",
            "saga_snapshot",
            "saga_delivery",
            "saga_deadline",
        )
    )
    + "".join(_participant_policies(t, c) for t, c in OWNER_COLUMN.items())
)


def service_role_grants(role: str) -> str:
    """Privileges for a service's database role (register it in ``saga_participant``).

    The log is append-only for services: ``INSERT`` and ``SELECT``, no
    ``UPDATE`` or ``DELETE``. The participant registry is read-only.
    """
    if not role.replace("_", "").isalnum():
        msg = f"Invalid role name {role!r}"
        raise ValueError(msg)
    return f"""
    GRANT SELECT ON saga_participant TO {role};
    GRANT SELECT, INSERT ON saga_log_event TO {role};
    GRANT SELECT, INSERT, UPDATE ON saga_transaction, saga_activity, saga_snapshot TO {role};
    GRANT SELECT, INSERT, UPDATE, DELETE ON saga_delivery, saga_deadline TO {role};
    """
