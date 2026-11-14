"""
Built-in Sagaz demonstrations, organised by domain.

Demonstrations are nested two levels deep:

    sagaz/demonstrations/<domain>/<name>/main.py

Each domain folder carries a ``DOMAIN`` dict in its ``__init__.py``::

    DOMAIN = {
        "order":       1,
        "name":        "core_patterns",
        "label":       "Domain 1 — Core Patterns",
        "short_label": "Core Patterns",
        "description": "...",
    }

Adding a new domain requires only creating the folder — no changes to this
module are needed.

Run with:

    sagaz demo list
    sagaz demo run <name>
    sagaz demo               # interactive menu
"""

from sagaz.demonstrations._discovery import (
    _domain_metadata,
    _is_demo_dir,
    _is_domain_dir,
    discover_demos,
    discover_demos_by_domain,
    discover_domains,
    get_demo_description,
    get_demonstrations_dir,
    get_domain_for_demo,
)

__all__ = [
    "discover_demos",
    "discover_demos_by_domain",
    "discover_domains",
    "get_demo_description",
    "get_demonstrations_dir",
    "get_domain_for_demo",
]
