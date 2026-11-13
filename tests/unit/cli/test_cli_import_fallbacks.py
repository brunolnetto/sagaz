"""Optional-dependency fallbacks of the private CLI command modules.

Each module is executed as a fresh, unregistered copy with ``rich`` (and
``simple_term_menu``) unavailable, so the cached module objects other tests
patch are left untouched.
"""

import importlib.util
import sys
from types import ModuleType
from unittest.mock import patch

import pytest

_NO_RICH = {"rich": None, "rich.console": None, "rich.panel": None, "rich.table": None}


def _fresh_copy(name: str, blocked: dict) -> ModuleType:
    spec = importlib.util.find_spec(name)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, blocked):
        spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "name",
    [
        "sagaz.cli._benchmark_cmd",
        "sagaz.cli._dev_cmds",
        "sagaz.cli._project_cmds",
        "sagaz.cli._examples_runner",
        "sagaz.cli._examples_menu",
    ],
)
def test_console_is_none_without_rich(name):
    module = _fresh_copy(name, _NO_RICH)

    assert module.console is None


@pytest.mark.parametrize("name", ["sagaz.cli._benchmark_cmd", "sagaz.cli._project_cmds"])
def test_panel_is_none_without_rich(name):
    module = _fresh_copy(name, _NO_RICH)

    assert module.Panel is None


def test_examples_menu_without_simple_term_menu():
    module = _fresh_copy("sagaz.cli._examples_menu", {"simple_term_menu": None})

    assert module.TERM_MENU_AVAILABLE is False
    assert module.TerminalMenu is None
