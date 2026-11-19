"""``apply_schema``: run a component's DDL only when it changed."""

from __future__ import annotations

from contextlib import asynccontextmanager

from sagaz.core.storage.backends.postgresql._schema_version import apply_schema, schema_version


class FakeConnection:
    """Enough of an asyncpg connection to drive apply_schema's decisions."""

    def __init__(self, applied: dict[str, str] | None = None, table: bool = True) -> None:
        self.applied = dict(applied or {})
        self.table = table
        self.executed: list[str] = []

    async def fetchval(self, sql: str, *args):
        if "to_regclass" in sql:
            return "sagaz_schema_version" if self.table else None
        return self.applied.get(args[0])

    async def execute(self, sql: str, *args):
        self.executed.append(sql)
        if sql.startswith("INSERT INTO sagaz_schema_version"):
            self.applied[args[0]] = args[1]
            self.table = True

    @asynccontextmanager
    async def transaction(self):
        yield


async def test_first_application_runs_and_records_the_version():
    conn = FakeConnection(table=False)
    assert await apply_schema(conn, "saga", "CREATE TABLE x ()")
    assert "CREATE TABLE x ()" in conn.executed
    assert conn.applied == {"saga": schema_version("CREATE TABLE x ()")}


async def test_an_applied_schema_runs_nothing():
    conn = FakeConnection({"saga": schema_version("DDL")})
    assert not await apply_schema(conn, "saga", "DDL")
    assert conn.executed == []


async def test_a_changed_schema_runs_again():
    conn = FakeConnection({"saga": schema_version("old DDL")})
    assert await apply_schema(conn, "saga", "new DDL")
    assert "new DDL" in conn.executed


async def test_applied_by_another_process_while_waiting_for_the_lock():
    conn = FakeConnection()

    async def fetchval(sql, *args, calls=[]):  # noqa: B006 - counts calls
        if "to_regclass" in sql:
            return "sagaz_schema_version"
        calls.append(1)
        return None if len(calls) == 1 else schema_version("DDL")

    conn.fetchval = fetchval  # type: ignore[method-assign]
    assert not await apply_schema(conn, "saga", "DDL")
    assert conn.executed == ["SELECT pg_advisory_xact_lock(hashtext('sagaz.schema'), hashtext($1))"]
