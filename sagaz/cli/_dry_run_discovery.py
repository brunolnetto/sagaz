"""Saga discovery and module loading for the dry-run CLI commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from types import ModuleType

    from sagaz import Saga


def _discover_project_sagas() -> list[dict[str, Any]]:
    """Discover sagas from project sagaz.yaml configuration."""
    import yaml

    if not Path("sagaz.yaml").exists():
        return []

    try:
        config = yaml.safe_load(Path("sagaz.yaml").read_text(encoding="utf-8"))
        paths = config.get("paths", ["sagas/"])
    except Exception:
        return []

    return _discover_sagas_in_paths(paths)


def _discover_sagas_in_paths(paths: list[str]) -> list[dict[str, Any]]:
    """Discover Saga classes in given paths."""
    import importlib.util
    import inspect

    from sagaz import Saga

    discovered: list[dict[str, Any]] = []

    for path_str in paths:
        p = Path(path_str)
        if p.exists():
            discovered.extend(_discover_sagas_in_directory(p, sys, importlib, inspect, Saga))

    return discovered


def _discover_sagas_in_directory(
    directory: Path,
    sys: ModuleType,
    importlib: ModuleType,
    inspect: ModuleType,
    saga_class: type[Saga],
) -> list[dict[str, Any]]:
    """Discover sagas in a specific directory."""
    discovered: list[dict[str, Any]] = []

    for file_path in directory.rglob("*.py"):
        if not file_path.name.startswith("__"):
            saga_info = _try_load_sagas_from_file(file_path, sys, importlib, inspect, saga_class)
            discovered.extend(saga_info)

    return discovered


def _try_load_sagas_from_file(
    file_path: Path,
    sys: ModuleType,
    importlib: ModuleType,
    inspect: ModuleType,
    saga_class: type[Saga],
) -> list[dict[str, Any]]:
    """Try to load sagas from a Python file."""
    try:
        module_name = f"sagaz_user_code.{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)

        if not (spec and spec.loader):
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        return _extract_sagas_from_module(module, file_path, inspect, saga_class)
    except Exception:
        return []


def _extract_sagas_from_module(
    module: ModuleType, file_path: Path, inspect: ModuleType, saga_class: type[Saga]
) -> list[dict[str, Any]]:
    """Extract saga_class classes from module."""
    discovered: list[dict[str, Any]] = []

    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and issubclass(obj, saga_class) and obj is not saga_class:
            discovered.append({"name": name, "file": str(file_path), "class": obj})

    return discovered


def _load_saga(module_path: str, saga_class_name: str | None) -> Saga:
    """Load saga from Python module."""
    import importlib.util
    import inspect

    from sagaz import Saga

    module = _load_python_module(module_path, importlib)
    saga_cls = _find_saga_class_in_module(module, saga_class_name, inspect, Saga)

    return saga_cls()


def _load_python_module(module_path: str, importlib: ModuleType) -> ModuleType:
    """Load Python module from path."""
    path = Path(module_path)
    if not path.exists():
        click.echo(f"Error: Module not found: {module_path}", err=True)
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("saga_module", path)
    if spec is None or spec.loader is None:
        click.echo(f"Error: Could not load module: {module_path}", err=True)
        sys.exit(1)

    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def _find_saga_class_in_module(
    module: ModuleType,
    saga_class_name: str | None,
    inspect: ModuleType,
    saga_class: type[Saga],
) -> type[Saga]:
    """Find saga_class class in module."""
    if saga_class_name:
        return _get_named_saga_class(module, saga_class_name)
    return _auto_detect_saga_class(module, inspect, saga_class)


def _get_named_saga_class(module: ModuleType, saga_class_name: str) -> type[Saga]:
    """Get specific saga_class class by name."""
    saga_cls: type[Saga] | None = getattr(module, saga_class_name, None)
    if saga_cls is None:
        click.echo(f"Error: Saga class '{saga_class_name}' not found", err=True)
        sys.exit(1)
    return saga_cls


def _auto_detect_saga_class(
    module: ModuleType, inspect: ModuleType, saga_class: type[Saga]
) -> type[Saga]:
    """Auto-detect Saga class in module."""
    saga_classes: list[type[Saga]] = [
        obj
        for name, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, saga_class) and obj is not saga_class
    ]

    if not saga_classes:
        click.echo("Error: No Saga class found in module", err=True)
        sys.exit(1)

    if len(saga_classes) > 1:
        click.echo(
            f"Error: Multiple saga_class classes found: {[c.__name__ for c in saga_classes]}. "
            "Use --saga-class to specify.",
            err=True,
        )
        sys.exit(1)

    return saga_classes[0]
