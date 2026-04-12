"""
Backward-compatibility import hook for sagaz Phase-2 restructuring.

After the Phase-2 refactoring, several top-level sub-packages were moved:

  Old path                 →  New canonical path
  ─────────────────────────────────────────────────────
  sagaz.monitoring.*       →  sagaz.observability.monitoring.*
  sagaz.storage.*          →  sagaz.core.storage.*
  sagaz.outbox.*           →  sagaz.core.outbox.*
  sagaz.triggers.*         →  sagaz.core.triggers.*

This module installs a ``MetaPathFinder`` that transparently redirects any
import of the old paths to the new canonical paths, so that:

- ``import sagaz.monitoring.tracing`` works
- ``from sagaz.storage.redis import RedisSagaStorage`` works
- ``@patch("sagaz.outbox.worker.PROMETHEUS_AVAILABLE", ...)`` works
- ``importlib.import_module("sagaz.triggers.engine")`` works

Both the new AND the old path resolve to the **same module object**, so
patching via either path affects the same namespace.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from typing import Any

_REDIRECTS: tuple[tuple[str, str], ...] = (
    ("sagaz.monitoring", "sagaz.observability.monitoring"),
    ("sagaz.storage", "sagaz.core.storage"),
    ("sagaz.outbox", "sagaz.core.outbox"),
    ("sagaz.triggers", "sagaz.core.triggers"),
)


def _canonical(name: str) -> str | None:
    """Return the canonical module path for a legacy *name*, or ``None``."""
    for old, new in _REDIRECTS:
        if name == old:
            return new
        if name.startswith(old + "."):
            return new + name[len(old):]
    return None


class _CompatLoader(Loader):
    """Loader that replaces a legacy shim with the real module object."""

    def __init__(self, alias: str, real_name: str) -> None:
        self._alias = alias
        self._real_name = real_name

    def create_module(self, spec: ModuleSpec) -> Any:  # noqa: ARG002
        return None  # use default module creation

    def exec_module(self, module: Any) -> None:  # noqa: ANN001
        # Import (or retrieve from cache) the real module.
        real = importlib.import_module(self._real_name)

        # Replace the alias in sys.modules with the real module object so that
        # attribute access and unittest.mock.patch both target the same object.
        sys.modules[self._alias] = real

        # Bind the attribute on the parent package so that
        #   import sagaz; sagaz.monitoring  →  sagaz.observability.monitoring
        # works without a prior explicit import.
        parts = self._alias.rsplit(".", 1)
        if len(parts) == 2:
            parent_name, child_attr = parts
            parent = sys.modules.get(parent_name)
            if parent is not None:
                setattr(parent, child_attr, real)


class _CompatFinder(MetaPathFinder):
    """MetaPathFinder that redirects legacy sagaz sub-package paths."""

    def find_spec(
        self,
        fullname: str,
        path: Any,  # noqa: ARG002
        target: Any = None,  # noqa: ARG002
    ) -> ModuleSpec | None:
        real = _canonical(fullname)
        if real is None:
            return None

        # If the alias is already registered, nothing to do.
        if fullname in sys.modules:
            return None

        # Verify the real module exists before promising to load the alias.
        try:
            real_spec = importlib.util.find_spec(real)
        except (ModuleNotFoundError, ValueError):
            real_spec = None

        if real_spec is None:
            return None

        return ModuleSpec(fullname, _CompatLoader(fullname, real))


_installed: bool = False


def install_compat_imports() -> None:
    """Install the backward-compatibility import hook (idempotent)."""
    global _installed  # noqa: PLW0603
    if _installed:
        return
    _installed = True
    # Insert at position 0 so we intercept BEFORE PathFinder.
    # If we were appended (last), PathFinder would find e.g. sagaz.monitoring.tracing
    # by traversing sagaz.monitoring.__path__ (which points to the real package dir),
    # creating a *new* module object with the alias name.  That would prevent
    # @patch("sagaz.monitoring.tracing.X") from affecting the canonical module namespace.
    sys.meta_path.insert(0, _CompatFinder())
