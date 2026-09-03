"""SagaVersion dataclass — metadata for a registered saga version (ADR-018)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sagaz.versioning.version import Version


@dataclass
class SagaVersion:
    """
    Metadata record for a single registered saga version.

    Attributes:
        saga_name:     Logical saga identifier (e.g. ``"order-processing"``).
        version:       Semantic version of this saga.
        step_names:    Ordered list of step names defined by this version.
        schema:        Mapping of context field names to type descriptors.
        deprecated_at: UTC timestamp when this version was deprecated, or
                       ``None`` if still active.
    """

    saga_name: str
    version: Version
    step_names: list[str] = field(default_factory=list)
    schema: dict[str, str] = field(default_factory=dict)
    deprecated_at: datetime | None = None

    @property
    def is_deprecated(self) -> bool:
        """Return True when this version has been marked deprecated."""
        return self.deprecated_at is not None
