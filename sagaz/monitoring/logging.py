"""
Structured logging for saga execution

Provides structured logging utilities specifically designed for saga pattern tracing,
with proper context propagation and correlation IDs for distributed systems.
"""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sagaz.core.types import SagaStatus

# Context variables for propagating saga context
saga_context: ContextVar[dict[str, Any]] = ContextVar("saga_context", default={})


class SagaJsonFormatter(logging.Formatter):
    """
    JSON formatter for saga logs with structured fields

    Ensures all saga-related logs include correlation IDs and context
    """

    # Fields to extract from log record if present
    _EXTRA_FIELDS = (
        "saga_id",
        "saga_name",
        "step_name",
        "correlation_id",
        "duration_ms",
        "retry_count",
        "error_type",
    )

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON"""
        log_entry = self._build_base_entry(record)
        self._add_saga_context(log_entry)
        self._add_record_extras(log_entry, record)
        return json.dumps(log_entry)

    def _build_base_entry(self, record: logging.LogRecord) -> dict[str, Any]:
        """Build base log entry with standard fields."""
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

    def _add_saga_context(self, log_entry: dict[str, Any]) -> None:
        """Add saga context to log entry if available."""
        context = saga_context.get({})
        if context:
            log_entry.update(
                {
                    "saga_id": context.get("saga_id"),
                    "saga_name": context.get("saga_name"),
                    "step_name": context.get("step_name"),
                    "correlation_id": context.get("correlation_id"),
                }
            )

    def _add_record_extras(self, log_entry: dict[str, Any], record: logging.LogRecord) -> None:
        """Add extra fields from log record."""
        for field in self._EXTRA_FIELDS:
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)


class SagaContextFilter(logging.Filter):
    """
    Logging filter that adds saga context to log records
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add saga context to log record"""

        context = saga_context.get({})

        # Add saga context fields to the record
        record.saga_id = context.get("saga_id", "unknown")
        record.saga_name = context.get("saga_name", "unknown")
        record.step_name = context.get("step_name", "")
        record.correlation_id = context.get("correlation_id", "")

        return True


class SagaLogger:
    """
    Saga-aware logger with automatic context propagation
    """

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

        # Add saga context filter
        saga_filter = SagaContextFilter()
        self.logger.addFilter(saga_filter)

    def set_saga_context(
        self,
        saga_id: str,
        saga_name: str,
        step_name: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Set saga context for current execution"""

        context = {
            "saga_id": saga_id,
            "saga_name": saga_name,
            "step_name": step_name,
            "correlation_id": correlation_id or saga_id,
        }
        saga_context.set(context)

    def clear_saga_context(self) -> None:
        """Clear saga context"""
        saga_context.set({})

    def saga_started(
        self, saga_id: str, saga_name: str, total_steps: int, correlation_id: str | None = None
    ) -> None:
        """Log saga start"""

        self.set_saga_context(saga_id, saga_name, correlation_id=correlation_id)
        self.logger.info(
            f"Saga started: {saga_name}",
            extra={
                "saga_id": saga_id,
                "saga_name": saga_name,
                "total_steps": total_steps,
                "correlation_id": correlation_id or saga_id,
            },
        )

    def saga_completed(
        self,
        saga_id: str,
        saga_name: str,
        status: SagaStatus,
        duration_ms: float,
        completed_steps: int,
        total_steps: int,
    ) -> None:
        """Log saga completion"""

        log_level = logging.INFO if status == SagaStatus.COMPLETED else logging.WARNING

        self.logger.log(
            log_level,
            f"Saga finished: {saga_name} - Status: {status.value}",
            extra={
                "saga_id": saga_id,
                "saga_name": saga_name,
                "status": status.value,
                "duration_ms": duration_ms,
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            },
        )

    def step_started(self, saga_id: str, saga_name: str, step_name: str) -> None:
        """Log step start"""

        self.set_saga_context(saga_id, saga_name, step_name)
        self.logger.info(
            f"Step started: {step_name}",
            extra={
                "saga_id": saga_id,
                "saga_name": saga_name,
                "step_name": step_name,
            },
        )

    def step_completed(
        self, saga_id: str, saga_name: str, step_name: str, duration_ms: float, retry_count: int = 0
    ) -> None:
        """Log step completion"""

        self.logger.info(
            f"Step completed: {step_name}",
            extra={
                "saga_id": saga_id,
                "saga_name": saga_name,
                "step_name": step_name,
                "duration_ms": duration_ms,
                "retry_count": retry_count,
            },
        )

    def step_failed(
        self, saga_id: str, saga_name: str, step_name: str, error: Exception, retry_count: int = 0
    ) -> None:
        """Log step failure"""

        self.logger.error(
            f"Step failed: {step_name} - {error!s}",
            extra={
                "saga_id": saga_id,
                "saga_name": saga_name,
                "step_name": step_name,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "retry_count": retry_count,
            },
            exc_info=True,
        )

    def compensation_started(self, saga_id: str, saga_name: str, step_name: str) -> None:
        """Log compensation start"""

        self.logger.warning(
            f"Compensation started: {step_name}",
            extra={
                "saga_id": saga_id,
                "saga_name": saga_name,
                "step_name": step_name,
            },
        )

    def compensation_completed(
        self, saga_id: str, saga_name: str, step_name: str, duration_ms: float
    ) -> None:
        """Log compensation completion"""

        self.logger.warning(
            f"Compensation completed: {step_name}",
            extra={
                "saga_id": saga_id,
                "saga_name": saga_name,
                "step_name": step_name,
                "duration_ms": duration_ms,
            },
        )

    def compensation_failed(
        self, saga_id: str, saga_name: str, step_name: str, error: Exception
    ) -> None:
        """Log compensation failure - critical error"""

        self.logger.critical(
            f"Compensation FAILED: {step_name} - {error!s}",
            extra={
                "saga_id": saga_id,
                "saga_name": saga_name,
                "step_name": step_name,
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
            exc_info=True,
        )


def setup_saga_logging(
    log_level: str = "INFO", json_format: bool = True, include_console: bool = True
) -> SagaLogger:
    """
    Set up structured logging for sagas

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        json_format: Use JSON formatting for structured logs
        include_console: Include console handler

    Returns:
        Configured SagaLogger instance
    """

    # Configure root logger
    root_logger = logging.getLogger("saga")
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    if include_console:
        console_handler = logging.StreamHandler()

        if json_format:
            console_handler.setFormatter(SagaJsonFormatter())
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - [%(saga_id)s:%(step_name)s] - %(message)s"
            )
            console_handler.setFormatter(formatter)

        root_logger.addHandler(console_handler)

    return SagaLogger("saga")


# Default saga logger instance
saga_logger = SagaLogger("saga")
