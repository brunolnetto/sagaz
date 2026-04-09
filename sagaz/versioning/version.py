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

    __slots__ = ("_major", "_minor", "_patch")

    def __init__(self, major: int, minor: int, patch: int) -> None:
        object.__setattr__(self, "_major", major)
        object.__setattr__(self, "_minor", minor)
        object.__setattr__(self, "_patch", patch)

    def __setattr__(self, _name: str, _value: object) -> None:
        msg = "Version instances are immutable"
        raise AttributeError(msg)

    @property
    def major(self) -> int:
        return self._major

    @property
    def minor(self) -> int:
        return self._minor

    @property
    def patch(self) -> int:
        return self._patch

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
        return (self._major, self._minor, self._patch) == (other._major, other._minor, other._patch)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self._major, self._minor, self._patch) < (other._major, other._minor, other._patch)

    def __hash__(self) -> int:
        return hash((self._major, self._minor, self._patch))

    # ── compatibility ──

    def is_compatible_with(self, other: Version) -> bool:
        """
        Return True if this version is backward-compatible with *other*.

        Two versions are compatible when they share the same major version
        and this version is not older than the other version within that
        major line.
        """
        return self.major == other.major and self >= other
