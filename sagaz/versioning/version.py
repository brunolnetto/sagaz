"""Version value object — semantic versioning for sagas (ADR-018)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True, order=True, slots=True)
class Version:
    """
    Semantic version value object.

    Immutable, hashable and ordered by ``(major, minor, patch)``. Supports
    parsing and minor-version compatibility checks.
    """

    major: int
    minor: int
    patch: int

    # ── construction ──

    @classmethod
    def parse(cls, value: str) -> Version:
        """Parse a ``MAJOR.MINOR.PATCH`` string into a Version object."""
        m = _SEMVER_RE.match(value.strip())
        if not m:
            msg = f"Invalid semver string: '{value}'. Expected MAJOR.MINOR.PATCH"
            raise ValueError(msg)
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # ── dunder ──

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __repr__(self) -> str:
        return f"Version({self!s})"

    # ── compatibility ──

    def is_compatible_with(self, other: Version) -> bool:
        """
        Return True if this version is backward-compatible with *other*.

        Two versions are compatible when they share the same major version
        and this version is not older than the other version within that
        major line.
        """
        return self.major == other.major and self >= other
