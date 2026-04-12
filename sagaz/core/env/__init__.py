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

import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]

from sagaz.core.env._conversion import get_bool, get_int
from sagaz.core.env._substitution import substitute, substitute_dict
from sagaz.core.env._template import create_env_template


class EnvManager:
    """
    Manages environment variables for Sagaz projects.

    Features:
    - Loads .env files automatically
    - Supports variable substitution in YAML configs
    - Provides defaults for common variables
    - Validates required variables

    Example:
        >>> env = EnvManager()
        >>> env.load()  # Loads .env if exists
        >>> storage_url = env.get("SAGAZ_STORAGE_URL")
    """

    def __init__(self, project_root: Path | str | None = None, auto_load: bool = True):
        """
        Initialize the environment manager.

        Args:
            project_root: Root directory of the project (searches for .env here)
            auto_load: Automatically load .env file if found
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._loaded = False

        if auto_load:
            self.load()

    def load(self, env_file: str | Path | None = None, override: bool = False) -> bool:
        """
        Load environment variables from .env file.

        Args:
            env_file: Path to .env file (defaults to .env in project root)
            override: Whether to override existing environment variables

        Returns:
            True if .env file was loaded, False otherwise
        """
        if load_dotenv is None:
            return False

        env_file = self.project_root / ".env" if env_file is None else Path(env_file)

        if not env_file.exists():
            return False

        load_dotenv(env_file, override=override)
        self._loaded = True
        return True

    def get(self, key: str, default: str | None = None, required: bool = False) -> str | None:
        """
        Get an environment variable value.

        Args:
            key: Environment variable name
            default: Default value if not found
            required: If True, raises ValueError if not found and no default

        Returns:
            Environment variable value or default

        Raises:
            ValueError: If required=True and variable not found
        """
        value = os.environ.get(key, default)

        if required and value is None:
            msg = f"Required environment variable not set: {key}"
            raise ValueError(msg)

        return value

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get environment variable as boolean."""
        return get_bool(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """Get environment variable as integer."""
        return get_int(key, default)

    def substitute(self, text: str) -> str:
        """
        Substitute environment variables in text using ${VAR} or $VAR syntax.

        Supports:
        - ${VAR} - variable substitution
        - ${VAR:-default} - with default value
        - ${VAR:?error} - required variable (raises error if not set)

        Args:
            text: Text containing variable references

        Returns:
            Text with variables substituted

        Example:
            >>> os.environ["DB_HOST"] = "localhost"
            >>> env.substitute("postgresql://${DB_HOST}/db")
            'postgresql://localhost/db'
        """
        return substitute(text)

    def substitute_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively substitute environment variables in dictionary values.

        Args:
            data: Dictionary potentially containing variable references

        Returns:
            Dictionary with variables substituted
        """
        return substitute_dict(data)

    @staticmethod
    def create_env_template(
        target_path: Path | str,
        config_data: dict[str, Any],
        include_examples: bool = True,
    ) -> None:
        """
        Create a .env.template file from configuration data.

        Args:
            target_path: Path to write .env.template
            config_data: Configuration dictionary
            include_examples: Include example values
        """
        create_env_template(target_path, config_data, include_examples)


# Global instance
_global_env: EnvManager | None = None


def get_env() -> EnvManager:
    """Get the global environment manager instance."""
    global _global_env
    if _global_env is None:
        _global_env = EnvManager()
    return _global_env


def load_env(project_root: Path | str | None = None, override: bool = False) -> bool:
    """
    Load environment variables from .env file.

    This is a convenience function that uses the global EnvManager instance.

    Args:
        project_root: Root directory to search for .env file
        override: Whether to override existing environment variables

    Returns:
        True if .env file was loaded
    """
    env = get_env()
    if project_root:
        env.project_root = Path(project_root)
    return env.load(override=override)


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
