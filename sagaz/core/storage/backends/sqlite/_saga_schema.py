"""Schema, upgrades and tenant filtering for :class:`SQLiteSagaStorage`.

Sagas are keyed by ``(tenant_id, saga_id)`` (ADR-020), so two tenants may use
the same saga id. Databases created before tenancy (``saga_id`` primary key, no
``tenant_id`` column) are rebuilt once, in a transaction, with every existing
saga assigned to the ``"default"`` tenant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sagaz.core.storage._tenancy import scoped_tenant
from sagaz.core.storage.core import serialize

if TYPE_CHECKING:
    import aiosqlite

_COLUMNS = (
    "saga_id, saga_name, status, steps, context, metadata, configuration, created_at, updated_at"
)

_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS {table} (
        tenant_id TEXT NOT NULL DEFAULT 'default',
        saga_id TEXT NOT NULL,
        saga_name TEXT NOT NULL,
        status TEXT NOT NULL,
        steps TEXT NOT NULL,
        context TEXT NOT NULL,
        metadata TEXT,
        configuration TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, saga_id)
    );
"""

_INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_sagas_status ON sagas(status);
    CREATE INDEX IF NOT EXISTS idx_sagas_name ON sagas(saga_name);
    CREATE INDEX IF NOT EXISTS idx_sagas_updated_at ON sagas(updated_at);
    CREATE INDEX IF NOT EXISTS idx_sagas_saga_id ON sagas(saga_id);
"""


def tenant_filter() -> tuple[str, list[Any]]:
    """``AND tenant_id = ?`` for the current tenant; nothing in the system scope."""
    tenant = scoped_tenant()
    if tenant is None:
        return "", []
    return " AND tenant_id = ?", [tenant]


async def _columns(conn: aiosqlite.Connection) -> set[str]:
    cursor = await conn.execute("PRAGMA table_info(sagas)")
    return {row["name"] for row in await cursor.fetchall()}


async def _add_tenant_key(conn: aiosqlite.Connection) -> None:
    """Rebuild a pre-tenancy ``sagas`` table with the ``(tenant_id, saga_id)`` key.

    SQLite cannot change a primary key in place, so the rows are copied into a
    new table inside one transaction (all or nothing).
    """
    script = (
        "BEGIN;"
        + _CREATE_TABLE.format(table="sagas_tenanted")
        + f"""
        INSERT INTO sagas_tenanted (tenant_id, {_COLUMNS})
            SELECT 'default', {_COLUMNS} FROM sagas;
        DROP TABLE sagas;
        ALTER TABLE sagas_tenanted RENAME TO sagas;
        COMMIT;
        """
    )
    try:
        await conn.executescript(script)
    except Exception:
        await conn.rollback()
        raise


async def _backfill_configuration(conn: aiosqlite.Connection) -> None:
    """Give legacy rows a configuration, without relying on SQLite JSON extensions."""
    cursor = await conn.execute(
        """
        SELECT tenant_id, saga_id, status FROM sagas
        WHERE configuration IS NULL
           OR configuration = ''
           OR configuration = '[]'
        """
    )
    for row in await cursor.fetchall():
        await conn.execute(
            "UPDATE sagas SET configuration = ? WHERE tenant_id = ? AND saga_id = ?",
            (serialize([row["status"]]), row["tenant_id"], row["saga_id"]),
        )


async def init_saga_schema(conn: aiosqlite.Connection) -> None:
    """Create the ``sagas`` table, upgrading databases from older versions."""
    await conn.executescript(_CREATE_TABLE.format(table="sagas"))
    # CREATE TABLE IF NOT EXISTS does not upgrade existing databases.
    columns = await _columns(conn)
    if "configuration" not in columns:
        await conn.execute("ALTER TABLE sagas ADD COLUMN configuration TEXT")
        await conn.commit()
    if "tenant_id" not in columns:
        await _add_tenant_key(conn)
    await conn.executescript(_INDEXES)
    await _backfill_configuration(conn)
    await conn.commit()
