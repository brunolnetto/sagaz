"""Helpers for unit tests that mock asyncpg connections."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock


@asynccontextmanager
async def _transaction():
    yield


def schema_ready(conn) -> None:
    """Let ``apply_schema`` run on a mocked connection.

    The connection gets a working ``transaction()`` and reports no applied
    schema version, so the DDL is executed as on a fresh database. Tests can
    still override ``fetchval`` afterwards.
    """
    conn.transaction = _transaction
    conn.fetchval = AsyncMock(return_value=None)
