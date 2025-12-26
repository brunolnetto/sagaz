"""
Outbox State Machine - Manages outbox event lifecycle transitions.

Ensures events transition through valid states only and provides
hooks for metrics and logging.

State Diagram:

    ┌─────────┐
    │ PENDING │ ←────────────────────┐
    └────┬────┘                      │
         │ claim()                   │ retry (if retries < max)
         ▼                           │
    ┌─────────┐                      │
    │ CLAIMED │ ─────────────────────┤
    └────┬────┘                      │
         │                           │
    ┌────┴────┐                      │
    │         │                      │
    ▼         ▼                      │
┌──────┐  ┌────────┐                 │
│ SENT │  │ FAILED │ ────────────────┘
└──────┘  └────┬───┘
               │ retry exceeded
               ▼
         ┌─────────────┐
         │ DEAD_LETTER │
         └─────────────┘
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sagaz.outbox.types import OutboxEvent, OutboxStatus


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, event_id: str, from_status: OutboxStatus, to_status: OutboxStatus):
        self.event_id = event_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Invalid transition for event {event_id}: {from_status.value} → {to_status.value}"
        )


class OutboxStateMachine:
    """
    State machine for outbox event lifecycle.

    Manages valid state transitions and provides hooks for
    monitoring and logging state changes.

    Valid Transitions:
        PENDING → CLAIMED (via claim)
        CLAIMED → SENT (via mark_sent)
        CLAIMED → FAILED (via mark_failed)
        FAILED → PENDING (via retry, if retries < max)
        FAILED → DEAD_LETTER (via move_to_dead_letter)

    Usage:
        >>> sm = OutboxStateMachine(max_retries=10)
        >>>
        >>> # Claim an event for processing
        >>> event = sm.claim(event, worker_id="worker-1")
        >>>
        >>> try:
        ...     await publish_to_broker(event)
        ...     event = sm.mark_sent(event)
        ... except Exception as e:
        ...     event = sm.mark_failed(event, str(e))
        ...     if event.retry_count >= sm.max_retries:
        ...         event = sm.move_to_dead_letter(event)
    """

    # Valid transitions: from_status -> [to_status, ...]
    VALID_TRANSITIONS = {
        OutboxStatus.PENDING: [OutboxStatus.CLAIMED],
        OutboxStatus.CLAIMED: [OutboxStatus.SENT, OutboxStatus.FAILED],
        OutboxStatus.FAILED: [OutboxStatus.PENDING, OutboxStatus.DEAD_LETTER],
        OutboxStatus.SENT: [],  # Terminal state
        OutboxStatus.DEAD_LETTER: [],  # Terminal state
    }

    def __init__(
        self,
        max_retries: int = 10,
        on_transition: Callable[[OutboxEvent, OutboxStatus, OutboxStatus], Any] | None = None,
    ):
        """
        Initialize the state machine.

        Args:
            max_retries: Maximum retry attempts before dead letter
            on_transition: Optional callback for state transitions
        """
        self.max_retries = max_retries
        self._on_transition = on_transition

    def _validate_transition(self, event: OutboxEvent, target_status: OutboxStatus) -> None:
        """Validate that the transition is allowed."""
        valid_targets = self.VALID_TRANSITIONS.get(event.status, [])

        if target_status not in valid_targets:
            raise InvalidStateTransitionError(event.event_id, event.status, target_status)

    def _transition(self, event: OutboxEvent, target_status: OutboxStatus) -> OutboxEvent:
        """Execute a state transition."""
        old_status = event.status
        self._validate_transition(event, target_status)

        event.status = target_status

        if self._on_transition:
            self._on_transition(event, old_status, target_status)

        return event

    def claim(self, event: OutboxEvent, worker_id: str) -> OutboxEvent:
        """
        Claim an event for processing.

        Args:
            event: The event to claim
            worker_id: ID of the claiming worker

        Returns:
            Updated event with CLAIMED status

        Raises:
            InvalidStateTransitionError: If event is not PENDING
        """
        event = self._transition(event, OutboxStatus.CLAIMED)
        event.worker_id = worker_id
        event.claimed_at = datetime.now(UTC)
        return event

    def mark_sent(self, event: OutboxEvent) -> OutboxEvent:
        """
        Mark event as successfully sent.

        Args:
            event: The event to mark as sent

        Returns:
            Updated event with SENT status

        Raises:
            InvalidStateTransitionError: If event is not CLAIMED
        """
        event = self._transition(event, OutboxStatus.SENT)
        event.sent_at = datetime.now(UTC)
        return event

    def mark_failed(self, event: OutboxEvent, error_message: str) -> OutboxEvent:
        """
        Mark event as failed.

        Args:
            event: The event that failed
            error_message: Error description

        Returns:
            Updated event with FAILED status

        Raises:
            InvalidStateTransitionError: If event is not CLAIMED
        """
        event = self._transition(event, OutboxStatus.FAILED)
        event.retry_count += 1
        event.last_error = error_message
        return event

    def retry(self, event: OutboxEvent) -> OutboxEvent:
        """
        Retry a failed event by moving it back to PENDING.

        Args:
            event: The failed event to retry

        Returns:
            Updated event with PENDING status

        Raises:
            InvalidStateTransitionError: If event is not FAILED
            ValueError: If max retries exceeded
        """
        if event.retry_count >= self.max_retries:
            msg = (
                f"Event {event.event_id} has exceeded max retries "
                f"({event.retry_count}/{self.max_retries})"
            )
            raise ValueError(
                msg
            )

        event = self._transition(event, OutboxStatus.PENDING)
        event.worker_id = None
        event.claimed_at = None
        return event

    def move_to_dead_letter(self, event: OutboxEvent) -> OutboxEvent:
        """
        Move event to dead letter queue.

        Args:
            event: The event to move to DLQ

        Returns:
            Updated event with DEAD_LETTER status

        Raises:
            InvalidStateTransitionError: If event is not FAILED
        """
        return self._transition(event, OutboxStatus.DEAD_LETTER)

    def can_retry(self, event: OutboxEvent) -> bool:
        """
        Check if an event can be retried.

        Args:
            event: The event to check

        Returns:
            True if event can be retried
        """
        return event.status == OutboxStatus.FAILED and event.retry_count < self.max_retries

    def should_dead_letter(self, event: OutboxEvent) -> bool:
        """
        Check if an event should be moved to dead letter.

        Args:
            event: The event to check

        Returns:
            True if event should go to DLQ
        """
        return event.status == OutboxStatus.FAILED and event.retry_count >= self.max_retries
