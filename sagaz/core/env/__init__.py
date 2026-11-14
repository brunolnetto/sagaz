"""
Environment variable management with .env file support.

This module provides utilities for loading and managing environment variables
with support for .env files, variable substitution in YAML configs, and
secure handling of sensitive data.

Example:
    >>> from sagaz.core.env import EnvManager, load_env
    >>> env = EnvManager()
    >>> env.load()  # Loads .env if exists
    >>> storage_url = env.get("SAGAZ_STORAGE_URL")
    >>> debug = env.get_bool("DEBUG")
    >>> port = env.get_int("PORT", default=8000)
"""

from __future__ import annotations

from typing import Any

from sagaz.core.env import _manager
from sagaz.core.env._conversion import get_bool, get_int
from sagaz.core.env._manager import EnvManager, get_env, load_dotenv, load_env
from sagaz.core.env._substitution import substitute, substitute_dict
from sagaz.core.env._template import create_env_template


def __getattr__(name: str) -> Any:
    """Expose the live global ``EnvManager`` (owned by ``_manager``) as ``_global_env``."""
    if name == "_global_env":
        return _manager._global_env
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted([*globals(), "_global_env"])


__all__ = [
    "EnvManager",
    "create_env_template",
    "get_bool",
    "get_env",
    "get_int",
    "load_env",
    "substitute",
    "substitute_dict",
]
