"""
Shared declarations for the ``RedisOutboxStorage`` mixins.

The mixins in this package split ``RedisOutboxStorage`` by responsibility.
This base only declares the instance attributes they share (set in
``RedisOutboxStorage.__init__``) and the core methods they call, so each mixin
type-checks on its own. It adds no runtime behaviour.
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.outbox.types import OutboxEvent, OutboxStatus

# Helpers log through the original module's logger so log records keep the
# same logger name as before the module was split.
logger = logging.getLogger("sagaz.core.storage.backends.redis.outbox")


class RedisOutboxMixinBase:
    """Attribute and method declarations shared by the Redis outbox mixins."""

    _redis: Any
    _initialized: bool
    _prefix: str
    _consumer_group: str
    _max_stream_length: int
    _event_ttl_seconds: int
    _stream_key: str
    _dlq_key: str
    _processing_key: str

    if TYPE_CHECKING:

        async def initialize(self) -> None: ...

        async def get_by_id(self, event_id: str) -> OutboxEvent | None: ...

        async def update_status(
            self,
            event_id: str,
            status: OutboxStatus,
            error_message: str | None = None,
            connection: Any | None = None,
            event: OutboxEvent | None = None,
        ) -> OutboxEvent: ...
