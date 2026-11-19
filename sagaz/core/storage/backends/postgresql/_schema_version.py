"""Apply a component's DDL only when it changed.

Every PostgreSQL store used to run its whole schema (``CREATE ... IF NOT
EXISTS``, ``ALTER TABLE``, ``CREATE POLICY``) each time it opened a pool. Those
statements take exclusive table locks even when they change nothing, so a
process starting while others write would queue behind them and could
deadlock with them.

:func:`apply_schema` records a hash of each component's DDL in
``sagaz_schema_version`` and runs the DDL only when that hash differs, under a
per-component advisory lock. A changed DDL is detected automatically, and an
up-to-date database takes no exclusive lock.
"""

from __future__ import annotations

import hashlib
from typing import Any

VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS sagaz_schema_version (
    component   TEXT PRIMARY KEY,
    version     TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def schema_version(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()[:32]


async def _applied_version(conn: Any, component: str) -> str | None:
    # Read before creating: roles without CREATE on the schema (services sharing
    # a database) cannot even run CREATE TABLE IF NOT EXISTS.
    if await conn.fetchval("SELECT to_regclass('sagaz_schema_version')") is None:
        return None
    return await conn.fetchval(
        "SELECT version FROM sagaz_schema_version WHERE component = $1", component
    )


async def apply_schema(conn: Any, component: str, sql: str) -> bool:
    """Run *sql* for *component* unless this exact DDL was applied; return whether it ran."""
    version = schema_version(sql)
    if await _applied_version(conn, component) == version:
        return False  # fast path: no lock at all
    async with conn.transaction():
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('sagaz.schema'), hashtext($1))", component
        )
        if await _applied_version(conn, component) == version:
            return False  # another process applied it while we waited
        await conn.execute(sql)
        await conn.execute(VERSION_TABLE)
        await conn.execute(
            "INSERT INTO sagaz_schema_version (component, version) VALUES ($1, $2)"
            " ON CONFLICT (component) DO UPDATE SET version = EXCLUDED.version,"
            " applied_at = NOW()",
            component,
            version,
        )
    return True
