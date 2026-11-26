"""What ``ChoreographedSaga.begin`` records before it publishes (#449, #562)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sagaz.core.exceptions import SagaAlreadyExistsError
from sagaz.core.storage._reserved import RESERVED_SAGA_PREFIX
from sagaz.core.tenant import tenant_scope

if TYPE_CHECKING:
    from sagaz.choreography.events import Event
    from sagaz.choreography.state import ParticipantState

#: The participant name under which ``begin`` records a correlation id it started, in
#: the participant state's delivery records (#562). Reserved: no participant uses it.
BEGIN_RECORD = f"{RESERVED_SAGA_PREFIX}begin"


async def claim_correlation_id(state: ParticipantState, event: Event) -> None:
    """Record *event*'s correlation id as started; raise if it already was (#562)."""
    correlation_id = event.saga_id or ""
    with tenant_scope(event.tenant_id):
        first = await state.first_delivery(BEGIN_RECORD, correlation_id)
    if not first:
        raise SagaAlreadyExistsError(correlation_id)


async def set_deadline(
    state: ParticipantState,
    participant: str,
    event: Event,
    deadline: timedelta | float,
    watch: Callable[[], None] | None,
) -> None:
    """Make *participant* own *event*'s transaction deadline (#449)."""
    seconds = deadline.total_seconds() if isinstance(deadline, timedelta) else deadline
    due_at = datetime.now(UTC) + timedelta(seconds=seconds)
    with tenant_scope(event.tenant_id):  # set before the transaction can finish
        await state.set_deadline(participant, event.saga_id or "", due_at)
    if watch is not None:
        watch()
