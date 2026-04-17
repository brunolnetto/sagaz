"""
Built-in Sagaz demonstrations.

Each subdirectory contains a self-contained demonstration of a specific
Sagaz feature.  Run them with:

    sagaz demo list
    sagaz demo run <name>
    sagaz demo               # interactive menu
"""

from __future__ import annotations

import importlib.resources as pkg_resources
import os
from pathlib import Path


def get_demonstrations_dir() -> Path:
    """Return the directory that contains built-in demonstrations."""
    try:
        return Path(str(pkg_resources.files("sagaz.demonstrations")))
    except (ModuleNotFoundError, TypeError):
        return Path(__file__).parent


def discover_demos() -> dict[str, Path]:
    """
    Scan the demonstrations directory for valid demonstrations.

    Returns: Dict[demo_name, path_to_main_py]
    """
    demos_dir = get_demonstrations_dir()
    found: dict[str, Path] = {}

    for item in demos_dir.iterdir():
        if not item.is_dir() or item.name.startswith("_"):
            continue
        main_py = item / "main.py"
        if main_py.exists():
            found[item.name] = main_py

    return dict(sorted(found.items()))


def get_demo_description(path: Path) -> str:
    """Extract the first line of the module docstring from a demo's main.py."""
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
