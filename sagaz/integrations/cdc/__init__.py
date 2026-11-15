"""Change Data Capture for the transactional outbox (ADR-011, #50).

Instead of polling ``saga_outbox``, a CDC source streams inserted rows from the
database's write-ahead log, through PostgreSQL logical replication
(:mod:`sagaz.integrations.cdc.pg_logical`) or Debezium on Kafka
(:mod:`sagaz.integrations.cdc.debezium`). The outbox worker publishes them as
they commit.
"""

from sagaz.integrations.cdc._events import event_from_row, parse_timestamp
from sagaz.integrations.cdc._types import CDCChange, CDCError, CDCSource

__all__ = ["CDCChange", "CDCError", "CDCSource", "event_from_row", "parse_timestamp"]
