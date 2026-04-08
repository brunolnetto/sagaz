"""Version value object — semantic versioning for sagas (ADR-018)."""

from __future__ import annotations

import re
from functools import total_ordering

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@total_ordering
class Version:
    """
    Semantic version value object.

    Supports parsing, comparison, and minor-version compatibility checks.
    """

    __slots__ = ("major", "minor", "patch")

    def __init__(self, major: int, minor: int, patch: int) -> None:
        self.major = major
        self.minor = minor
        self.patch = patch

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

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch))

    # ── compatibility ──

    def is_compatible_with(self, other: Version) -> bool:
        """
        Return True if this version is backward-compatible with *other*.

        Two versions are compatible when they share the same major version
        and this version's minor is >= other's minor (new minor releases
        are backward-compatible with older ones in the same major line).
        """
        return self.major == other.major and self.minor >= other.minor
