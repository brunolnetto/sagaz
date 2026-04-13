"""
DLQ replay validator — ADR-038 Phase 2.

DLQReplayValidator.can_replay(event) → (bool, reason_str)

Prevents blind/looping replays by checking:
  1. Error classification — PERMANENT errors must not be replayed.
  2. Replay count — events that have already been replayed max_replays
     times are blocked (unless the caller uses force=True on the
     storage method directly).
"""

from __future__ import annotations

from sagaz.core.outbox.types import OutboxEvent

_DEFAULT_MAX_REPLAYS = 3


class DLQReplayValidator:
    """
    Stateless validator that decides whether a dead-lettered event
    may be replayed.

    Parameters:
        max_replays: Maximum number of replay attempts before an event
            is considered stuck.  Defaults to ``3`` (ADR-038 §Phase-2).
    """

    def __init__(self, max_replays: int = _DEFAULT_MAX_REPLAYS) -> None:
        self.max_replays = max_replays

    def can_replay(self, event: OutboxEvent) -> tuple[bool, str]:
        """
        Check whether *event* may be replayed.

        Returns:
            A ``(allowed, reason)`` tuple where *reason* is an empty
            string when *allowed* is ``True``, or a human-readable
            explanation when it is ``False``.
        """
        if event.error_classification == "PERMANENT":
            return (
                False,
                f"Event {event.event_id} has a PERMANENT error classification "
                f"(error_type={event.error_type!r}); replaying will not succeed.",
            )

        if event.replay_count >= self.max_replays:
            return (
                False,
                f"Event {event.event_id} has been replayed {event.replay_count} time(s) "
                f"(max {self.max_replays}). Use force=True to override.",
            )

        return True, ""
