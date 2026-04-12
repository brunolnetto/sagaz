"""Environment variable type conversion utilities."""

import os


def get_bool(key: str, default: bool = False) -> bool:
    """
    Get environment variable as boolean.

    Args:
        key: Environment variable name
        default: Default value if not found

    Returns:
        Boolean value
    """
    value = (os.environ.get(key) or "").lower()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off"):
        return False
    return default


def get_int(key: str, default: int = 0) -> int:
    """
    Get environment variable as integer.

    Args:
        key: Environment variable name
        default: Default value if not found

    Returns:
        Integer value
    """
    try:
        return int(os.environ.get(key) or str(default))
    except (ValueError, TypeError):
        return default
