"""
Environment variable management with .env file support.

This module provides utilities for loading and managing environment variables
with support for .env files, variable substitution in YAML configs, and
secure handling of sensitive data.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


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
        
        if env_file is None:
            env_file = self.project_root / ".env"
        else:
            env_file = Path(env_file)
        
        if not env_file.exists():
            return False
        
        load_dotenv(env_file, override=override)
        self._loaded = True
        return True
    
    def get(
        self, 
        key: str, 
        default: str | None = None, 
        required: bool = False
    ) -> str | None:
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
        value = self.get(key, "").lower()
        if value in ("true", "1", "yes", "on"):
            return True
        if value in ("false", "0", "no", "off"):
            return False
        return default
    
    def get_int(self, key: str, default: int = 0) -> int:
        """Get environment variable as integer."""
        try:
            return int(self.get(key, str(default)))
        except (ValueError, TypeError):
            return default
    
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
        # Pattern: ${VAR}, ${VAR:-default}, ${VAR:?error}
        pattern = r'\$\{([^}:]+)(?::([?-])([^}]*))?\}'
        
        def replace(match):
            var_name = match.group(1)
            operator = match.group(2)
            operand = match.group(3)
            
            value = os.environ.get(var_name)
            
            if operator == '-':  # ${VAR:-default}
                return value if value is not None else operand
            elif operator == '?':  # ${VAR:?error}
                if value is None:
                    error_msg = operand or f"Required variable not set: {var_name}"
                    raise ValueError(error_msg)
                return value
            else:  # ${VAR}
                return value if value is not None else f"${{{var_name}}}"
        
        # Also handle simple $VAR syntax
        text = re.sub(pattern, replace, text)
        text = re.sub(r'\$([A-Z_][A-Z0-9_]*)', lambda m: os.environ.get(m.group(1), m.group(0)), text)
        
        return text
    
    def substitute_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively substitute environment variables in dictionary values.
        
        Args:
            data: Dictionary potentially containing variable references
            
        Returns:
            Dictionary with variables substituted
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.substitute(value)
            elif isinstance(value, dict):
                result[key] = self.substitute_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self.substitute(item) if isinstance(item, str)
                    else self.substitute_dict(item) if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
    
    @staticmethod
    def create_env_template(
        target_path: Path | str,
        config_data: dict[str, Any],
        include_examples: bool = True
    ) -> None:
        """
        Create a .env.template file from configuration data.
        
        Args:
            target_path: Path to write .env.template
            config_data: Configuration dictionary
            include_examples: Include example values
        """
        path = Path(target_path)
        
        lines = [
            "# Sagaz Environment Configuration",
            "# Copy this file to .env and fill in your values",
            "# DO NOT commit .env to version control!",
            "",
            "# Project Settings",
            "SAGAZ_ENV=development  # development, staging, production",
            "",
        ]
        
        # Extract configuration sections
        storage_type = config_data.get("storage", {}).get("type", "postgresql")
        broker_type = config_data.get("broker", {}).get("type", "redis")
        
        # Storage configuration
        lines.extend([
            "# Storage Configuration",
            f"SAGAZ_STORAGE_TYPE={storage_type}",
        ])
        
        if storage_type == "postgresql":
            lines.extend([
                "SAGAZ_STORAGE_HOST=localhost",
                "SAGAZ_STORAGE_PORT=5432",
                "SAGAZ_STORAGE_DB=sagaz",
                "SAGAZ_STORAGE_USER=postgres",
                "SAGAZ_STORAGE_PASSWORD=  # Set your password",
                "# Or use full URL:",
                "# SAGAZ_STORAGE_URL=postgresql://user:pass@host:port/db",
            ])
        elif storage_type == "redis":
            lines.extend([
                "SAGAZ_STORAGE_URL=redis://localhost:6379/0",
            ])
        
        lines.append("")
        
        # Broker configuration
        lines.extend([
            "# Message Broker Configuration",
            f"SAGAZ_BROKER_TYPE={broker_type}",
        ])
        
        if broker_type == "kafka":
            lines.extend([
                "SAGAZ_BROKER_HOST=localhost",
                "SAGAZ_BROKER_PORT=9092",
                "# Or use full URL:",
                "# SAGAZ_BROKER_URL=kafka://localhost:9092",
            ])
        elif broker_type == "rabbitmq":
            lines.extend([
                "SAGAZ_BROKER_HOST=localhost",
                "SAGAZ_BROKER_PORT=5672",
                "SAGAZ_BROKER_USER=guest",
                "SAGAZ_BROKER_PASSWORD=guest",
                "# Or use full URL:",
                "# SAGAZ_BROKER_URL=amqp://guest:guest@localhost:5672/",
            ])
        elif broker_type == "redis":
            lines.extend([
                "SAGAZ_BROKER_URL=redis://localhost:6379/1",
            ])
        
        lines.append("")
        
        # Observability
        obs_config = config_data.get("observability", {})
        if obs_config.get("prometheus", {}).get("enabled"):
            lines.extend([
                "# Observability",
                "SAGAZ_METRICS_ENABLED=true",
                "SAGAZ_METRICS_PORT=9090",
            ])
        
        if obs_config.get("tracing", {}).get("enabled"):
            lines.extend([
                "SAGAZ_TRACING_ENABLED=true",
                "SAGAZ_TRACING_ENDPOINT=http://localhost:4317",
            ])
        
        lines.extend([
            "",
            "# Logging",
            "SAGAZ_LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR",
            "",
        ])
        
        # Outbox configuration
        lines.extend([
            "# Outbox Worker Configuration (if using separate outbox database)",
            "# SAGAZ_OUTBOX_STORAGE_URL=postgresql://user:pass@host:port/outbox_db",
            "# SAGAZ_OUTBOX_BATCH_SIZE=100",
            "# SAGAZ_OUTBOX_POLL_INTERVAL=1.0",
            "",
        ])
        
        path.write_text("\n".join(lines))


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
