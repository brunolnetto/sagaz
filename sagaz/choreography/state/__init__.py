"""Durable memory of choreography participants (#448)."""

from __future__ import annotations

from sagaz.choreography.state._base import ParticipantState
from sagaz.choreography.state.memory import InMemoryParticipantState


def create_participant_state(url: str) -> ParticipantState:
    """A participant state for *url*: ``memory://``, ``sqlite://<path>`` or ``postgresql://...``."""
    if url.startswith("memory://"):
        return InMemoryParticipantState()
    if url.startswith("sqlite://"):
        from sagaz.choreography.state.sqlite import SQLiteParticipantState

        return SQLiteParticipantState(url[len("sqlite://") :] or ":memory:")
    if url.startswith(("postgresql://", "postgres://")):
        from sagaz.choreography.state.postgresql import PostgreSQLParticipantState

        return PostgreSQLParticipantState(url)
    msg = f"Unsupported participant state URL {url!r}: use memory://, sqlite:// or postgresql://"
    raise ValueError(msg)


__all__ = ["InMemoryParticipantState", "ParticipantState", "create_participant_state"]
