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

from __future__ import annotations

import importlib
import importlib.resources as pkg_resources
from pathlib import Path


def get_demonstrations_dir() -> Path:
    """Return the root demonstrations directory."""
    try:
        return Path(str(pkg_resources.files("sagaz.demonstrations")))
    except (ModuleNotFoundError, TypeError):
        return Path(__file__).parent


def _is_domain_dir(path: Path) -> bool:
    """Return True when *path* is a domain folder (has __init__.py, no main.py)."""
    return (
        path.is_dir()
        and not path.name.startswith("_")
        and (path / "__init__.py").exists()
        and not (path / "main.py").exists()
    )


def _is_demo_dir(path: Path) -> bool:
    """Return True when *path* is a demo folder (has main.py)."""
    return path.is_dir() and not path.name.startswith("_") and (path / "main.py").exists()


def _domain_metadata(domain_name: str) -> dict:
    """
    Import the domain package and return its ``DOMAIN`` dict.

    Falls back to a generated dict when the package does not define ``DOMAIN``
    (e.g. during development before the dict is added).
    """
    try:
        mod = importlib.import_module(f"sagaz.demonstrations.{domain_name}")
        meta = getattr(mod, "DOMAIN", None)
        if isinstance(meta, dict):
            return meta
    except ImportError:
        pass
    # Minimal fallback — no hardcoded knowledge needed here.
    return {
        "order": 999,
        "name": domain_name,
        "label": domain_name.replace("_", " ").title(),
        "short_label": domain_name.replace("_", " ").title(),
        "description": "",
    }


def discover_domains() -> list[dict]:
    """
    Return domain metadata dicts sorted by ``DOMAIN["order"]``.

    Each dict contains at minimum: order, name, label, short_label, description.
    """
    demos_dir = get_demonstrations_dir()
    domains: list[dict] = []
    for item in demos_dir.iterdir():
        if _is_domain_dir(item):
            domains.append(_domain_metadata(item.name))
    return sorted(domains, key=lambda d: (d.get("order", 999), d.get("name", "")))


def discover_demos_by_domain() -> dict[str, dict[str, Path]]:
    """
    Scan for domains and the demos within each domain.

    Returns:
        Ordered dict keyed by domain name, values are ``{demo_name: path_to_main_py}``.
        Domains are ordered by their ``DOMAIN["order"]`` value.
    """
    demos_dir = get_demonstrations_dir()
    raw: dict[str, dict[str, Path]] = {}

    for item in demos_dir.iterdir():
        if not _is_domain_dir(item):
            continue
        domain_demos: dict[str, Path] = {}
        for sub in sorted(item.iterdir()):
            if _is_demo_dir(sub):
                domain_demos[sub.name] = sub / "main.py"
        if domain_demos:
            raw[item.name] = domain_demos

    ordered: dict[str, dict[str, Path]] = {}
    for meta in discover_domains():
        name = meta["name"]
        if name in raw:
            ordered[name] = raw[name]
    # Any domain without a registered order goes last, alphabetically.
    for name in sorted(raw):
        if name not in ordered:
            ordered[name] = raw[name]

    return ordered


def discover_demos() -> dict[str, Path]:
    """
    Flat view of all available demonstrations.

    Returns:
        Sorted dict: {demo_name: path_to_main_py}

    Raises:
        ValueError: if two domains define a demo with the same name.
    """
    found: dict[str, Path] = {}
    for _domain, demos in discover_demos_by_domain().items():
        for name, path in demos.items():
            if name in found:
                msg = (
                    f"Duplicate demo name '{name}' found in multiple domains. "
                    "All demo names must be unique across domains."
                )
                raise ValueError(msg)
            found[name] = path
    return dict(sorted(found.items()))


def get_demo_description(path: Path) -> str:
    """Extract the first non-empty line of the module docstring from a main.py."""
    try:
        with path.open() as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#!") or not stripped:
                    continue
                if stripped.startswith(('"""', "'''")):
                    desc = stripped.strip("\"'").strip()
                    if not desc:
                        desc = f.readline().strip()
                    return desc if desc else "No description"
                break
    except Exception:
        pass
    return "No description"


def get_domain_for_demo(name: str) -> str | None:
    """Return the domain name that contains *name*, or None if not found."""
    for domain, demos in discover_demos_by_domain().items():
        if name in demos:
            return domain
    return None

