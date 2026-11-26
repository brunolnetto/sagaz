"""In-memory participant state: the default, lost on restart."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Collection
from datetime import UTC, datetime, timedelta

from sagaz.choreography.events import Event
from sagaz.choreography.state._base import COMPENSATED, COMPLETED, Deadline, ParticipantState
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
        self._seen: OrderedDict[tuple[str, str, str], None] = OrderedDict()  # done for good
        # key -> reserved until (a delivery being handled, #561)
        self._leases: OrderedDict[tuple[str, str, str], datetime] = OrderedDict()
        # key -> (due_at, claimed_until)
        self._deadlines: dict[tuple[str, str, str], tuple[datetime, datetime | None]] = {}

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
        self._deadlines.pop(key, None)
        state = COMPENSATED if compensated or self._ended.get(key) == COMPENSATED else COMPLETED
        _bounded_set(self._ended, key, state, self.max_transactions)
        return done

    async def actions(self, participant: str, correlation_id: str) -> list[Event]:
        return list(self._actions.get(self._key(participant, correlation_id), []))

    async def was_compensated(self, participant: str, correlation_id: str) -> bool:
        return self._ended.get(self._key(participant, correlation_id)) == COMPENSATED

    async def first_delivery(self, participant: str, event_id: str) -> bool:
        key = self._key(participant, event_id)
        if key in self._seen or key in self._leases:
            return False
        _bounded_set(self._seen, key, None, self.max_deliveries)
        return True

    async def claim_delivery(self, participant: str, event_id: str, lease: timedelta) -> bool:
        key = self._key(participant, event_id)
        now = datetime.now(UTC)
        if key in self._seen or self._leases.get(key, now) > now:
            return False
        _bounded_set(self._leases, key, now + lease, self.max_deliveries)
        return True

    async def finish_delivery(self, participant: str, event_id: str) -> None:
        key = self._key(participant, event_id)
        self._leases.pop(key, None)
        _bounded_set(self._seen, key, None, self.max_deliveries)

    async def set_deadline(self, participant: str, correlation_id: str, due_at: datetime) -> None:
        key = self._key(participant, correlation_id)
        if key not in self._ended:
            self._deadlines[key] = (due_at, None)

    async def claim_due_deadlines(
        self, participants: Collection[str], now: datetime, lease: timedelta, limit: int = 100
    ) -> list[Deadline]:
        claimed: list[Deadline] = []
        for key, (due_at, claimed_until) in sorted(
            self._deadlines.items(), key=lambda item: item[1][0]
        ):
            tenant, participant, correlation_id = key
            if len(claimed) == limit:
                break
            if participant not in participants or due_at > now:
                continue
            if claimed_until is not None and claimed_until > now:
                continue
            self._deadlines[key] = (due_at, now + lease)
            claimed.append(Deadline(tenant, participant, correlation_id, due_at))
        return claimed
