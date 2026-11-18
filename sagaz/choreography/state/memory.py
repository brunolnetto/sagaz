"""In-memory participant state: the default, lost on restart."""

from __future__ import annotations

from collections import OrderedDict

from sagaz.choreography.events import Event
from sagaz.choreography.state._base import COMPENSATED, COMPLETED, ParticipantState
from sagaz.core.storage._tenancy import write_tenant


def _bounded_set(ids: OrderedDict, key: object, value: object, limit: int) -> None:
    ids[key] = value
    ids.move_to_end(key)
    while len(ids) > limit:
        ids.popitem(last=False)


class InMemoryParticipantState(ParticipantState):
    """Keeps the last ``max_transactions`` transactions and ``max_deliveries`` deliveries."""

    def __init__(self, max_transactions: int = 10_000, max_deliveries: int = 100_000) -> None:
        self.max_transactions = max_transactions
        self.max_deliveries = max_deliveries
        self._actions: OrderedDict[tuple[str, str, str], list[Event]] = OrderedDict()
        self._ended: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self._seen: OrderedDict[tuple[str, str, str], None] = OrderedDict()

    @staticmethod
    def _key(participant: str, value: str) -> tuple[str, str, str]:
        return write_tenant(), participant, value

    async def record_action(self, participant: str, event: Event) -> None:
        key = self._key(participant, event.saga_id or "")
        if not event.saga_id or key in self._ended:
            return
        done = self._actions.get(key, [])
        if any(e.event_id == event.event_id for e in done):
            return
        _bounded_set(self._actions, key, [*done, event], self.max_transactions)

    async def finish(
        self, participant: str, correlation_id: str, *, compensated: bool
    ) -> list[Event]:
        key = self._key(participant, correlation_id)
        done = self._actions.pop(key, [])
        state = COMPENSATED if compensated or self._ended.get(key) == COMPENSATED else COMPLETED
        _bounded_set(self._ended, key, state, self.max_transactions)
        return done

    async def was_compensated(self, participant: str, correlation_id: str) -> bool:
        return self._ended.get(self._key(participant, correlation_id)) == COMPENSATED

    async def first_delivery(self, participant: str, event_id: str) -> bool:
        key = self._key(participant, event_id)
        if key in self._seen:
            return False
        _bounded_set(self._seen, key, None, self.max_deliveries)
        return True
