"""The dry-run display module loads without rich and reports it (plain fallback)."""

from __future__ import annotations

import importlib.util
import sys

from sagaz.cli import _dry_run_display


def test_module_loads_without_rich(monkeypatch):
    for name in ("rich", "rich.console", "rich.panel", "rich.table"):
        monkeypatch.setitem(sys.modules, name, None)
    spec = importlib.util.spec_from_file_location(
        "_dry_run_display_plain", _dry_run_display.__file__
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.RICH_AVAILABLE is False
    assert module.console is None
