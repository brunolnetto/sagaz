"""
Built-in Sagaz demonstrations, organised by domain.

Demonstrations are nested two levels deep:

    sagaz/demonstrations/<domain>/<name>/main.py

Domains:
    core_patterns          — fundamental saga building blocks
    developer_experience   — dry-run, visualisation, hooks
    reliability_recovery   — idempotency, snapshots, replay, compliance
    orchestration_config   — multi-saga co-ordination and storage
    schema_evolution       — context migration and step versioning
    framework_integrations — FastAPI, outbox, metrics, Kubernetes

Run with:

    sagaz demo list
    sagaz demo run <name>
    sagaz demo               # interactive menu
"""

from __future__ import annotations

import importlib.resources as pkg_resources
from pathlib import Path

# Ordered list that defines the canonical display order for domains.
DOMAIN_ORDER: list[str] = [
    "core_patterns",
    "developer_experience",
    "reliability_recovery",
    "orchestration_config",
    "schema_evolution",
    "framework_integrations",
]

DOMAIN_LABELS: dict[str, str] = {
    "core_patterns": "Domain 1 — Core Patterns",
    "developer_experience": "Domain 2 — Developer Experience",
    "reliability_recovery": "Domain 3 — Reliability & Recovery",
    "orchestration_config": "Domain 4 — Orchestration & Configuration",
    "schema_evolution": "Domain 5 — Schema Evolution",
    "framework_integrations": "Domain 6 — Framework Integrations",
}


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


def discover_demos_by_domain() -> dict[str, dict[str, Path]]:
    """
    Scan for domains and the demos within each domain.

    Returns:
        Ordered dict: {domain_name: {demo_name: path_to_main_py}}
        Domains appear in DOMAIN_ORDER; demos within each domain are sorted.
    """
    demos_dir = get_demonstrations_dir()
    by_domain: dict[str, dict[str, Path]] = {}

    for item in demos_dir.iterdir():
        if not _is_domain_dir(item):
            continue
        domain_demos: dict[str, Path] = {}
        for sub in sorted(item.iterdir()):
            if _is_demo_dir(sub):
                domain_demos[sub.name] = sub / "main.py"
        if domain_demos:
            by_domain[item.name] = domain_demos

    # Return in canonical domain order; unknown domains go last (sorted).
    ordered: dict[str, dict[str, Path]] = {}
    for domain in DOMAIN_ORDER:
        if domain in by_domain:
            ordered[domain] = by_domain[domain]
    for domain in sorted(by_domain):
        if domain not in ordered:
            ordered[domain] = by_domain[domain]

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
