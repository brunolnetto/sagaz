"""The statuses of a choreographed transaction (ADR-029), shared by the tracker and
its listener hooks. Import them from :mod:`sagaz.choreography.tracker`."""

from __future__ import annotations

#: Saga name of the records the tracker writes, and of its listener hooks (#563).
RECORD_NAME = "choreography"

EXECUTING, COMPLETED, COMPENSATING, ROLLED_BACK, FAILED = (
    "executing",
    "completed",
    "compensating",
    "rolled_back",
    "failed",
)
#: Compensated after a pivot: what could be undone was, the rest stays done (#571).
PARTIALLY_COMMITTED = "partially_committed"
#: The statuses a transaction does not leave.
ENDED = (COMPLETED, ROLLED_BACK, PARTIALLY_COMMITTED, FAILED)
