"""Storage backends for the benchmark, each opened for one benchmark session.

Every backend yields a :class:`BackendSession`: the storage, a hook that
prepares it for a mode (PostgreSQL ablations), and version information. The
benchmark never deletes data it did not create: SQLite uses a temporary file,
Redis a unique key prefix (deleted at the end), and PostgreSQL either a
database and role it provisions and drops itself (``--postgres-admin-url``) or
a database you provide (``--postgres-url``), where its rows are left behind.
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from benchmarks.tenancy.workload import Mode

BACKENDS = ("memory", "sqlite", "postgres", "redis")

#: Tables of the saga storage protected by row-level security.
SAGA_TABLES = ("sagas", "saga_steps")


async def _no_preparation(mode: Mode) -> None:
    if mode.is_ablation:
        msg = f"mode '{mode.name}' is a PostgreSQL ablation"
        raise ValueError(msg)


@dataclass
class BackendSession:
    name: str
    storage: Any
    prepare: Callable[[Mode], Awaitable[None]] = _no_preparation
    info: dict[str, Any] = field(default_factory=dict)
    supports_ablations: bool = False
    #: Count the statements each saga sends (asyncpg backends only).
    counts_statements: bool = False


@dataclass(frozen=True)
class BackendOptions:
    postgres_url: str | None = None
    postgres_admin_url: str | None = None
    postgres_pool_size: int = 20
    #: ``False`` sets ``synchronous_commit = off`` on the benchmark's connections, so
    #: commits skip the wait for the WAL flush and per-query costs are not hidden by it.
    postgres_synchronous_commit: bool = True
    redis_url: str | None = None


@asynccontextmanager
async def open_backend(name: str, options: BackendOptions) -> AsyncIterator[BackendSession]:
    """Open backend ``name`` for one benchmark session."""
    factories = {
        "memory": _memory,
        "sqlite": _sqlite,
        "postgres": _postgres,
        "redis": _redis,
    }
    if name not in factories:
        msg = f"unknown backend '{name}', expected one of {', '.join(BACKENDS)}"
        raise ValueError(msg)
    async with factories[name](options) as session:
        yield session


@asynccontextmanager
async def _memory(options: BackendOptions) -> AsyncIterator[BackendSession]:
    from sagaz.core.storage.memory import InMemorySagaStorage

    yield BackendSession("memory", InMemorySagaStorage())


@asynccontextmanager
async def _sqlite(options: BackendOptions) -> AsyncIterator[BackendSession]:
    import sqlite3

    from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage

    with tempfile.TemporaryDirectory(prefix="sagaz-bench-") as directory:
        path = Path(directory) / "bench.db"
        async with SQLiteSagaStorage(str(path)) as storage:
            yield BackendSession("sqlite", storage, info={"sqlite": sqlite3.sqlite_version})


@asynccontextmanager
async def _redis(options: BackendOptions) -> AsyncIterator[BackendSession]:
    from sagaz.core.storage.backends.redis.saga import RedisSagaStorage

    if not options.redis_url:
        msg = "the redis backend needs --redis-url"
        raise ValueError(msg)
    prefix = f"sagaz-bench-{uuid.uuid4().hex[:8]}:"
    # The TTL is a safety net in case the cleanup below never runs.
    async with RedisSagaStorage(options.redis_url, key_prefix=prefix, default_ttl=3600) as storage:
        client = await storage._get_redis()
        info = await client.info("server")
        try:
            yield BackendSession("redis", storage, info={"redis": info.get("redis_version")})
        finally:
            keys = [key async for key in client.scan_iter(match=f"*{prefix}*", count=1000)]
            for start in range(0, len(keys), 500):
                await client.delete(*keys[start : start + 500])


@asynccontextmanager
async def _postgres(options: BackendOptions) -> AsyncIterator[BackendSession]:
    if options.postgres_admin_url:
        async with provision_app_role(options.postgres_admin_url) as url:
            async with _postgres_session(url, options) as session:
                yield session
    elif options.postgres_url:
        async with _postgres_session(options.postgres_url, options) as session:
            yield session
    else:
        msg = "the postgres backend needs --postgres-admin-url or --postgres-url"
        raise ValueError(msg)


@asynccontextmanager
async def provision_app_role(admin_url: str) -> AsyncIterator[str]:
    """A scratch database and NOSUPERUSER NOBYPASSRLS role; both dropped on exit.

    The role owns the tables sagaz creates, so FORCE row-level security applies
    to it, as it does to a production application role.
    """
    import asyncpg

    suffix = uuid.uuid4().hex[:10]
    database, role, password = f"sagaz_bench_{suffix}", f"sagaz_bench_{suffix}", uuid.uuid4().hex
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        await admin.execute(
            f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS"
        )
    finally:
        await admin.close()
    parts = urlsplit(admin_url)
    database_url = urlunsplit(parts._replace(path=f"/{database}"))
    owner = await asyncpg.connect(database_url)
    try:
        await owner.execute(f"GRANT ALL ON SCHEMA public TO {role}")
    finally:
        await owner.close()
    netloc = f"{role}:{password}@{parts.hostname}:{parts.port or 5432}"
    try:
        yield urlunsplit(parts._replace(netloc=netloc, path=f"/{database}"))
    finally:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1",
                database,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
            await admin.execute(f"DROP ROLE IF EXISTS {role}")
        finally:
            await admin.close()


@asynccontextmanager
async def _postgres_session(url: str, options: BackendOptions) -> AsyncIterator[BackendSession]:
    import asyncpg

    from sagaz.core.storage.backends.postgresql import _tenancy
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    original_apply_scope = _tenancy.apply_scope

    async def skip_scope(conn: Any) -> None:
        return None

    pool_size = options.postgres_pool_size
    synchronous_commit = "on" if options.postgres_synchronous_commit else "off"
    async with PostgreSQLSagaStorage(
        url,
        pool_min_size=pool_size,
        pool_max_size=pool_size,
        server_settings={"synchronous_commit": synchronous_commit},
    ) as storage:
        control = await asyncpg.connect(url)
        role = await control.fetchrow(
            "SELECT current_user AS name, rolsuper, rolbypassrls, version() AS version, "
            "current_setting('server_version') AS server_version "
            "FROM pg_roles WHERE rolname = current_user"
        )

        rls_on = True  # sagaz creates the tables with FORCE row-level security

        async def prepare(mode: Mode) -> None:
            nonlocal rls_on
            if not mode.scope_sql and mode.rls:
                msg = f"mode '{mode.name}': skipping set_config needs RLS off"
                raise ValueError(msg)
            if mode.rls != rls_on:  # only the table owner may do this
                action, force = ("ENABLE", "FORCE") if mode.rls else ("DISABLE", "NO FORCE")
                for table in SAGA_TABLES:
                    await control.execute(f"ALTER TABLE {table} {action} ROW LEVEL SECURITY")
                    await control.execute(f"ALTER TABLE {table} {force} ROW LEVEL SECURITY")
                rls_on = mode.rls
            _tenancy.apply_scope = original_apply_scope if mode.scope_sql else skip_scope

        info = {
            "postgres": role["server_version"],
            "role": role["name"],
            "rls_enforced": not (role["rolsuper"] or role["rolbypassrls"]),
            "pool_size": pool_size,
            "synchronous_commit": synchronous_commit,
        }
        try:
            yield BackendSession(
                "postgres", storage, prepare, info, supports_ablations=True, counts_statements=True
            )
        finally:
            _tenancy.apply_scope = original_apply_scope
            await prepare(Mode("restore", tenancy=False))
            await control.close()
