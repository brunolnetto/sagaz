"""
Pending-event counting for ``RedisOutboxStorage``.

A PENDING event is one whose stream entry has not been delivered to the
consumer group yet: ``insert`` and DLQ requeue append an entry, and
``claim_batch`` (XREADGROUP) delivers it and marks the event CLAIMED. The
count is therefore the group's *lag*, not the stream length, which also
includes delivered entries until MAXLEN trims them.
"""

from typing import Any

from sagaz.core.storage.backends.redis._outbox_base import RedisOutboxMixinBase, logger

# Entries fetched per XRANGE call when the lag has to be counted by hand.
_UNDELIVERED_PAGE_SIZE = 1000


class RedisOutboxPendingCountMixin(RedisOutboxMixinBase):
    """``get_pending_count`` from the consumer group's undelivered entries."""

    @staticmethod
    def _text(value: Any) -> str:
        return value.decode() if isinstance(value, bytes) else str(value)

    async def _consumer_group_info(self) -> dict[str, Any] | None:
        assert self._redis is not None
        groups: list[dict[str, Any]] = await self._redis.xinfo_groups(self._stream_key)
        for group in groups:
            if self._text(group.get("name", "")) == self._consumer_group:
                return group
        return None

    async def _count_entries_after(self, last_delivered_id: str) -> int:
        """Count stream entries newer than ``last_delivered_id`` (paged XRANGE)."""
        assert self._redis is not None
        total = 0
        start = f"({last_delivered_id}"
        while True:
            page = await self._redis.xrange(
                self._stream_key, min=start, max="+", count=_UNDELIVERED_PAGE_SIZE
            )
            total += len(page)
            if len(page) < _UNDELIVERED_PAGE_SIZE:
                return total
            start = f"({self._text(page[-1][0])}"

    async def get_pending_count(self) -> int:
        """Count events waiting to be claimed (status PENDING)."""
        if not self._initialized:
            await self.initialize()

        try:
            group = await self._consumer_group_info()
            if group is None:
                return 0
            # Redis >= 7 reports the lag directly; it is None (or absent on
            # older servers) when it cannot be derived, e.g. after XDEL.
            lag = group.get("lag")
            if lag is not None:
                return int(lag)
            return await self._count_entries_after(self._text(group["last-delivered-id"]))
        except Exception as e:
            logger.warning(f"Error counting pending events: {e}")
            return 0
