import logging
from unittest.mock import MagicMock

import pytest

from sagaz.core.listeners import LoggingSagaListener
from sagaz.core.logger import NullLogger, get_logger, set_logger


class MockLogger:
    def __init__(self):
        self.logs = []

    def info(self, msg, *args, **kwargs):
        self.logs.append(("INFO", msg))

    def error(self, msg, *args, **kwargs):
        self.logs.append(("ERROR", msg))

    def log(self, level, msg, *args, **kwargs):
        self.logs.append((level, msg))

    def debug(self, msg, *args, **kwargs):
        self.logs.append(("DEBUG", msg))

    def warning(self, msg, *args, **kwargs):
        self.logs.append(("WARNING", msg))

    def exception(self, msg, *args, **kwargs):
        self.logs.append(("EXCEPTION", msg))

def test_logger_propagation():
    """Test that setting a custom logger propagates to listeners."""

    # 1. Default state (standard logging)
    set_logger(None)
    logger1 = get_logger("test")
    assert isinstance(logger1, logging.Logger)

    # 2. Set custom logger
    mock_logger = MockLogger()
    set_logger(mock_logger)

    # 3. Check retrieval
    logger2 = get_logger("test")
    assert logger2 is mock_logger

    # 4. Check LoggingSagaListener picks it up automatically
    listener = LoggingSagaListener(level="INFO")

    # Simulate a log event
    listener.log.info("Test message")

    # Verify it went to our mock logger
    assert len(mock_logger.logs) == 1
    assert mock_logger.logs[0][1] == "Test message"

    # 5. Reset
    set_logger(None)
    logger3 = get_logger("test")
    assert isinstance(logger3, logging.Logger)

def test_null_logger():
    """Test NullLogger works as expected."""
    null_logger = NullLogger()
    null_logger.info("This should not blow up")
    null_logger.error("Neither should this")

def test_config_logging_usage():
    """Test that sagaz modules use the configured logger."""
    from sagaz.core.config import logger as config_logger
    from sagaz.integrations.fastapi import get_logger as get_fastapi_logger

    mock_logger = MockLogger()
    set_logger(mock_logger)

    # Modules should now return the mock logger
    assert get_logger("sagaz.config") is mock_logger

    # Note: Module-level variables like 'logger' in config.py are evaluated at import time.
    # They won't update automatically if they are simple variables.
    # However, get_logger() calls will return the new logger.

    assert get_fastapi_logger(__name__) is mock_logger

    # Reset
    set_logger(None)
