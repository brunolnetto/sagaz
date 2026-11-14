"""Records sagaz keeps in saga storage for itself (tenant registry, versions).

They are stored as sagas whose name starts with :data:`RESERVED_SAGA_PREFIX` and
must survive maintenance such as ``cleanup_completed_sagas``.
"""

from __future__ import annotations

RESERVED_SAGA_PREFIX = "__sagaz_"

#: SQL ``LIKE`` pattern (escape character ``\\``) matching reserved saga names.
RESERVED_SAGA_LIKE = r"\_\_sagaz\_%"


def is_reserved_saga_name(name: str | None) -> bool:
    """Whether ``name`` belongs to one of sagaz's own records."""
    return bool(name) and str(name).startswith(RESERVED_SAGA_PREFIX)
