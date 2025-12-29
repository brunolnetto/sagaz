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


# ============================================
# SESSION-SCOPED CONTAINER FIXTURES
# These are shared across ALL tests to avoid
# repeated container startup (~30-100s each)
# ============================================

# Check for testcontainers availability
try:
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False
    PostgresContainer = None
    RedisContainer = None


@pytest.fixture(scope="session")
def postgres_container():
    """
    Session-scoped PostgreSQL container.

    Shared across all tests in the session.
    Container starts once and stops at the end of the test session.
    Gracefully skips if container fails to start (e.g., Docker issues).
    """
    if not TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers not available")
        return None

    try:
        with PostgresContainer("postgres:16-alpine") as container:
            yield container
    except Exception as e:
        # Container failed to start (timeout, Docker issues, etc.)
        pytest.skip(f"PostgreSQL container failed to start: {e}")


@pytest.fixture(scope="session")
def redis_container():
    """
    Session-scoped Redis container.

    Shared across all tests in the session.
    Container starts once and stops at the end of the test session.
    Gracefully skips if container fails to start (e.g., Docker issues).
    """
    if not TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers not available")
        return None

    try:
        with RedisContainer("redis:7-alpine") as container:
            yield container
    except Exception as e:
        # Container failed to start (timeout, Docker issues, etc.)
        pytest.skip(f"Redis container failed to start: {e}")


@pytest.fixture(scope="session")
def postgres_connection_string(postgres_container):
    """Get PostgreSQL connection string from container."""
    if postgres_container is None:
        return None
    return postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )


@pytest.fixture(scope="session")
def redis_url(redis_container):
    """Get Redis URL from container."""
    if redis_container is None:
        return None
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}"


# ============================================
# SESSION-SCOPED STORAGE FIXTURES
# These avoid repeated schema initialization
# ============================================

# Check for storage backends
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

try:
    import redis.asyncio

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


@pytest.fixture(scope="session")
def postgres_storage_factory(postgres_connection_string):
    """
    Factory to create PostgreSQL storage instances using the session container.

    Usage:
        def test_something(postgres_storage_factory):
            async with postgres_storage_factory() as storage:
                await storage.save_saga_state(...)
    """
    if not ASYNCPG_AVAILABLE or postgres_connection_string is None:
        return None

    from sagaz.storage.postgresql import PostgreSQLSagaStorage

    def factory():
        return PostgreSQLSagaStorage(postgres_connection_string)

    return factory


@pytest.fixture(scope="session")
def redis_storage_factory(redis_url):
    """
    Factory to create Redis storage instances using the session container.

    Usage:
        def test_something(redis_storage_factory):
            async with redis_storage_factory() as storage:
                await storage.save_saga_state(...)
    """
    if not REDIS_AVAILABLE or redis_url is None:
        return None

    from sagaz.storage.redis import RedisSagaStorage

    def factory(**kwargs):
        return RedisSagaStorage(redis_url=redis_url, **kwargs)

    return factory
