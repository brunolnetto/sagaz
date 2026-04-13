"""
DLQ error classification and fingerprinting helpers — ADR-038 Phase 1.

classify_error()         → "TRANSIENT" | "PERMANENT" | "UNKNOWN"
create_error_fingerprint() → 16-char hex hash of normalised error message
"""

from __future__ import annotations

import hashlib
import re

# ---------------------------------------------------------------------------
# Error category tables
# ---------------------------------------------------------------------------

_TRANSIENT_TYPES: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

_PERMANENT_TYPES: tuple[type[BaseException], ...] = (
    ValueError,
    TypeError,
    KeyError,
    AssertionError,
    AttributeError,
)

# Regex patterns that strip variable tokens from error messages so
# structurally equivalent errors produce the same fingerprint.
_NORMALISATION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # IPv4 addresses and ports
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<HOST>"),
    # Bare hostnames with optional port
    (re.compile(r"\b[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z]{2,})+(?::\d+)?\b"), "<HOST>"),
    # Pure numbers (standalone integers)
    (re.compile(r"\b\d+\b"), "<N>"),
    # UUIDs
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<UUID>"),
]


def classify_error(exc: BaseException) -> str:
    """
    Return the error category for *exc*.

    Returns:
        ``"TRANSIENT"``  — connection/network/transient failures worth retrying.
        ``"PERMANENT"``  — logical/validation failures that will never succeed on retry.
        ``"UNKNOWN"``    — anything else.
    """
    if isinstance(exc, _TRANSIENT_TYPES):
        return "TRANSIENT"
    if isinstance(exc, _PERMANENT_TYPES):
        return "PERMANENT"
    return "UNKNOWN"


def create_error_fingerprint(message: str) -> str:
    """
    Return a 16-char hex fingerprint for *message*.

    Variable tokens (numbers, hostnames, UUIDs) are normalised before
    hashing so that structurally equivalent error messages produce the
    same fingerprint regardless of instance-specific values.
    """
    normalised = message.strip().lower()
    for pattern, replacement in _NORMALISATION_PATTERNS:
        normalised = pattern.sub(replacement, normalised)
    digest = hashlib.md5(normalised.encode(), usedforsecurity=False).hexdigest()
    return digest[:16]
