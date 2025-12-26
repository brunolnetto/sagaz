"""
Pytest configuration and shared fixtures for saga pattern tests
"""

import pytest
import warnings
from examples.order_processing.notification import NotificationService


@pytest.fixture(autouse=True)
def deterministic_notifications():
    """
    Automatically set deterministic behavior for notification failures in tests.
    
    This fixture runs automatically for all tests (autouse=True) and ensures
    that notification services don't randomly fail, making tests deterministic.
    """
    # Set failure rates to 0 for deterministic tests
    NotificationService.set_failure_rates(email=0.0, sms=0.0)
    
    yield
    
    # Reset to defaults after test
    NotificationService.reset_failure_rates()


@pytest.fixture(autouse=True, scope="session")
def suppress_otel_warnings():
    """
    Suppress OpenTelemetry export warnings during tests.
    
    The OTel exporter tries to connect to localhost:4317 which doesn't exist
    in test environment, causing harmless but noisy error messages.
    
    The OTLP exporter uses Python logging (not warnings), so we need to
    suppress the logger for the gRPC exporter specifically.
    
    This is session-scoped to keep logging suppressed during session teardown.
    """
    import logging
    
    # Suppress the OpenTelemetry exporter logger (logs gRPC connection errors)
    otel_loggers = [
        "opentelemetry.exporter.otlp.proto.grpc.exporter",
        "opentelemetry.exporter.otlp.proto.grpc",
        "opentelemetry.sdk.trace.export",
        "grpc._channel",
    ]
    
    for logger_name in otel_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL + 1)  # Disable all logging
    
    # Also filter out Python warnings as a fallback
    warnings.filterwarnings(
        "ignore",
        message=".*StatusCode.UNAVAILABLE.*",
        category=UserWarning,
    )
    
    yield
    # Don't restore levels - keep suppressed during session teardown


@pytest.fixture
def enable_notification_failures():
    """
    Fixture to explicitly enable notification failures for specific tests.
    
    Use this when you want to test failure scenarios:
        def test_with_failures(enable_notification_failures):
            # SMS/email may fail randomly
            ...
    """
    NotificationService.reset_failure_rates()
    yield
    # Reset after test
    NotificationService.set_failure_rates(email=0.0, sms=0.0)

