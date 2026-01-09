"""
Centralized logger configuration for Sagaz.

Provides a unified logging interface that can be customized by the user.
By default, uses Python's standard logging with the 'sagaz' namespace.

Usage:
    # Use default logger
    from sagaz.core.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Message")

    # Set custom logger (e.g., structlog, loguru)
    from sagaz.core.logger import set_logger
    import structlog
    set_logger(structlog.get_logger())
"""

import logging
from typing import Any

# Global logger instance - defaults to standard logging
_custom_logger: Any = None


class NullLogger:  # pragma: no cover
    """A logger that does nothing (for when logging is disabled)."""

    def debug(self, *args, **kwargs): pass
    def info(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass
    def exception(self, *args, **kwargs): pass
    def critical(self, *args, **kwargs): pass


def set_logger(logger: Any) -> None:
    """
    Set a custom logger for all Sagaz components.

    Args:
        logger: A logger instance (e.g., structlog logger, loguru logger)
                Must support debug/info/warning/error/exception methods.

    Example:
        import structlog
        from sagaz.core.logger import set_logger
        set_logger(structlog.get_logger())
    """
    global _custom_logger
    _custom_logger = logger


def get_logger(name: str = "sagaz") -> Any:
    """
    Get a logger instance.

    If a custom logger was set via set_logger(), returns that.
    Otherwise, returns a standard Python logger with the given name.

    Args:
        name: Logger name (typically __name__ of the calling module)

    Returns:
        A logger instance
    """
    if _custom_logger is not None:
        return _custom_logger

    # Return standard Python logger
    logger = logging.getLogger(name)

    # Ensure we have at least a NullHandler to avoid "No handler found" warnings
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    return logger


def configure_default_logging(  # pragma: no cover
    level: int = logging.INFO,
    format_string: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
) -> None:
    """
    Configure basic logging for Sagaz.

    Call this if you want simple console logging without custom configuration.

    Args:
        level: Logging level (default: INFO)
        format_string: Log message format
    """
    logging.basicConfig(level=level, format=format_string)

    # Set sagaz namespace to the specified level
    sagaz_logger = logging.getLogger("sagaz")
    sagaz_logger.setLevel(level)

