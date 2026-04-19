"""
CDC (Change Data Capture) integration for sagaz.

Provides two source implementations:

- ``CDCWorker``      — polls a Debezium Kafka Connect REST endpoint and
                       forwards CDC events to the outbox processor.
- ``PgLogicalSource`` — connects to a PostgreSQL logical-replication slot
                        directly (no Kafka required) for lower-latency CDC.
"""

from sagaz.integrations.cdc.metrics import CDCMetrics
from sagaz.integrations.cdc.pg_logical import PgLogicalSource
from sagaz.integrations.cdc.worker import CDCEvent, CDCEventType, CDCWorker

__all__ = [
    "CDCEvent",
    "CDCEventType",
    "CDCMetrics",
    "CDCWorker",
    "PgLogicalSource",
]
