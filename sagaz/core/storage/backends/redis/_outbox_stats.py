"""
Health check and statistics for ``RedisOutboxStorage`` (the pending count is
in ``_outbox_pending``).

Counts cover the current tenant, or every tenant in the system scope (ADR-020).
"""

import time

from sagaz.core.storage.backends.redis._outbox_pending import RedisOutboxPendingCountMixin
from sagaz.core.storage.core import (
    HealthCheckResult,
    HealthStatus,
    StorageStatistics,
)


class RedisOutboxStatisticsMixin(RedisOutboxPendingCountMixin):
    """``health_check`` and ``get_statistics``."""

    async def _xlen(self, key: str) -> int:
        try:
            return int(await self._redis.xlen(key))
        except Exception:
            return 0

    async def health_check(self) -> HealthCheckResult:
        """Check Redis connection health."""
        if not self._initialized:
            try:
                await self.initialize()
            except Exception as e:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=0,
                    message=f"Failed to initialize: {e}",
                )

        start = time.perf_counter()

        try:
            assert self._redis is not None
            await self._redis.ping()
            stream_len = await self._redis.xlen(self._stream_key)
            elapsed_ms = (time.perf_counter() - start) * 1000

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                latency_ms=elapsed_ms,
                message="OK",
                details={
                    "stream_length": stream_len,
                    "consumer_group": self._consumer_group,
                },
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=elapsed_ms,
                message=f"Redis error: {e}",
            )

    async def get_statistics(self) -> StorageStatistics:
        """Get storage statistics."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        pending = await self.get_pending_count()
        dlq_len = sum(await self._per_tenant(lambda: self._xlen(self._scoped_dlq_key())))

        return StorageStatistics(
            pending_records=pending,
            failed_records=dlq_len,
        )
