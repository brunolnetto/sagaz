"""
Shared declarations for the ``SQLiteOutboxStorage`` mixins.

The mixins in this package split ``SQLiteOutboxStorage`` by responsibility.
This base only declares the connection attribute (set in
``SQLiteOutboxStorage.__init__``) and the core methods the mixins call, so each
mixin type-checks on its own. It adds no runtime behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

    from sagaz.core.outbox.types import OutboxEvent, OutboxStatus


class SQLiteOutboxMixinBase:
    """Attribute and method declarations shared by the SQLite outbox mixins."""

    _conn: aiosqlite.Connection | None

    if TYPE_CHECKING:

        async def _get_connection(self) -> aiosqlite.Connection: ...

        async def insert(self, event: OutboxEvent, connection=None) -> OutboxEvent: ...

        async def get_by_id(self, event_id: str) -> OutboxEvent | None: ...

        async def update_status(
            self,
            event_id: str,
            status: OutboxStatus,
            error_message: str | None = None,
            connection=None,
            event: OutboxEvent | None = None,
        ) -> OutboxEvent: ...
