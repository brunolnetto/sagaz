"""
Shared declarations for the ``PostgreSQLOutboxStorage`` mixins.

The mixins in this package split ``PostgreSQLOutboxStorage`` by
responsibility. This base only declares the connection pool attribute (set in
``PostgreSQLOutboxStorage.__init__``) and the core methods the mixins call, so
each mixin type-checks on its own. It adds no runtime behaviour.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.outbox.types import OutboxEvent, OutboxStatus


class PostgreSQLOutboxMixinBase:
    """Attribute and method declarations shared by the PostgreSQL outbox mixins."""

    _pool: Any

    if TYPE_CHECKING:

        async def insert(
            self,
            event: OutboxEvent,
            connection: Any | None = None,
        ) -> OutboxEvent: ...

        async def get_by_id(self, event_id: str) -> OutboxEvent | None: ...

        async def update_status(
            self,
            event_id: str,
            status: OutboxStatus,
            error_message: str | None = None,
            connection: Any | None = None,
            event: OutboxEvent | None = None,
        ) -> OutboxEvent: ...
