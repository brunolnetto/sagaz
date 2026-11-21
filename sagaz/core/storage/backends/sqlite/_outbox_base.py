"""
Shared declarations for the ``SQLiteOutboxStorage`` mixins.

The mixins in this package split ``SQLiteOutboxStorage`` by responsibility.
This base only declares the connection attribute (set in
``SQLiteOutboxStorage.__init__``) and the core methods the mixins call, so each
mixin type-checks on its own. Its one function refuses a caller's connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sagaz.core.storage.interfaces.outbox import OutboxStorageError

if TYPE_CHECKING:
    import aiosqlite

    from sagaz.core.outbox.types import OutboxEvent, OutboxStatus


def own_connection_only(connection: object | None) -> None:
    """Refuse a caller's ``connection``: it would be ignored, silently (#607).

    Other backends write through the connection they are given, so the outbox row
    commits or rolls back with the caller's transaction. This storage always writes and
    commits through its own connection, so it cannot give that guarantee.
    """
    if connection is not None:
        msg = (
            "SQLiteOutboxStorage cannot join a caller's transaction: it writes and commits "
            "through its own connection, so the connection passed here would be ignored. "
            "Omit it. For outbox messages that commit together with a saga's state on "
            "SQLite, use the unified saga log (SQLiteSagaLogStore), whose outbox shares "
            "the log's connection."
        )
        raise OutboxStorageError(msg)


class SQLiteOutboxMixinBase:
    """Attribute and method declarations shared by the SQLite outbox mixins."""

    _conn: aiosqlite.Connection | None

    if TYPE_CHECKING:

        async def _get_connection(self) -> aiosqlite.Connection: ...

        async def insert(
            self, event: OutboxEvent, connection: object | None = None
        ) -> OutboxEvent: ...

        async def get_by_id(self, event_id: str) -> OutboxEvent | None: ...

        async def update_status(
            self,
            event_id: str,
            status: OutboxStatus,
            error_message: str | None = None,
            connection: object | None = None,
            event: OutboxEvent | None = None,
        ) -> OutboxEvent: ...
