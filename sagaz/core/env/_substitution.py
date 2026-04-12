"""Environment variable substitution utilities."""

import os
import re
from typing import Any


def substitute(text: str) -> str:
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
        >>> substitute("postgresql://${DB_HOST}/db")
        'postgresql://localhost/db'
    """
    # Pattern: ${VAR}, ${VAR:-default}, ${VAR:?error}
    pattern = r"\$\{([^}:]+)(?::([?-])([^}]*))?\}"

    def replace(match):
        var_name = match.group(1)
        operator = match.group(2)
        operand = match.group(3)

        value = os.environ.get(var_name)

        if operator == "-":  # ${VAR:-default}
            return value if value is not None else operand
        if operator == "?":  # ${VAR:?error}
            if value is None:
                error_msg = operand or f"Required variable not set: {var_name}"
                raise ValueError(error_msg)
            return value
        # ${VAR}
        return value if value is not None else f"${{{var_name}}}"

    # Also handle simple $VAR syntax
    text = re.sub(pattern, replace, text)
    return re.sub(
        r"\$([A-Z_][A-Z0-9_]*)", lambda m: os.environ.get(m.group(1), m.group(0)), text
    )


def substitute_dict(data: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively substitute environment variables in dictionary values.

    Args:
        data: Dictionary potentially containing variable references

    Returns:
        Dictionary with variables substituted
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = substitute(value)
        elif isinstance(value, dict):
            result[key] = substitute_dict(value)
        elif isinstance(value, list):
            result[key] = [
                substitute(item)
                if isinstance(item, str)
                else substitute_dict(item)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result
