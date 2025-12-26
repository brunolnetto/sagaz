"""
Pytest configuration and shared fixtures for saga pattern tests

Optimizations:
- Session-scoped fixtures for expensive setup (Docker containers, K8s manifests)
- Reduced sleep times where possible
"""

import warnings

import pytest

from examples.order_processing.notification import NotificationService

# ============================================
# AUTO-USE FIXTURES
# ============================================


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

    return
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


# ============================================
# KUBERNETES MANIFEST FIXTURES (CACHED)
# ============================================


@pytest.fixture(scope="session")
def k8s_manifests():
    """
    Load and cache all K8s manifests at session start.
    Prevents repeated file I/O.
    """
    import yaml

    manifests = {}
    manifest_files = [
        "k8s/configmap.yaml",
        "k8s/outbox-worker.yaml",
        "k8s/postgresql.yaml",
        "k8s/migration-job.yaml",
        "k8s/prometheus-monitoring.yaml",
    ]

    for filepath in manifest_files:
        try:
            with open(filepath) as f:
                manifests[filepath] = list(yaml.safe_load_all(f))
        except FileNotFoundError:
            manifests[filepath] = None

    return manifests
