"""
Pytest configuration and shared fixtures for saga pattern tests

Optimizations:
- Session-scoped fixtures for expensive setup (Docker containers, K8s manifests)
- Parallel container initialization (all start simultaneously)
- Automatic container availability detection (no env vars needed)
- Reduced sleep times where possible
"""

import warnings

import pytest

# Import parallel container plugin
pytest_plugins = ["tests.conftest_containers"]

# ============================================
# AUTO-USE FIXTURES
# ============================================


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
# Containers start in PARALLEL via conftest_containers.py
# Automatic availability detection - no env vars needed
# ============================================

@pytest.fixture(scope="session")
def postgres_container(container_manager):
    """PostgreSQL container (auto-initialized in parallel)."""
    if not container_manager:
        pytest.skip("testcontainers not available")
    if not container_manager.available.get("postgres"):
        pytest.skip(f"PostgreSQL: {container_manager.errors.get('postgres', 'unavailable')}")
    return container_manager.containers["postgres"]


@pytest.fixture(scope="session")
def redis_container(container_manager):
    """Redis container (auto-initialized in parallel)."""
    if not container_manager:
        pytest.skip("testcontainers not available")
    if not container_manager.available.get("redis"):
        pytest.skip(f"Redis: {container_manager.errors.get('redis', 'unavailable')}")
    return container_manager.containers["redis"]


@pytest.fixture(scope="session")
def kafka_container(container_manager):
    """Kafka container (auto-initialized in parallel)."""
    if not container_manager:
        pytest.skip("testcontainers not available")
    if not container_manager.available.get("kafka"):
        pytest.skip(f"Kafka: {container_manager.errors.get('kafka', 'unavailable')}")
    return container_manager.containers["kafka"]


@pytest.fixture(scope="session")
def rabbitmq_container(container_manager):
    """RabbitMQ container (auto-initialized in parallel)."""
    if not container_manager:
        pytest.skip("testcontainers not available")
    if not container_manager.available.get("rabbitmq"):
        pytest.skip(f"RabbitMQ: {container_manager.errors.get('rabbitmq', 'unavailable')}")
    return container_manager.containers["rabbitmq"]


@pytest.fixture(scope="session")
def localstack_container(container_manager):
    """LocalStack S3 container (auto-initialized in parallel)."""
    if not container_manager:
        pytest.skip("testcontainers not available")
    if not container_manager.available.get("localstack"):
        pytest.skip(f"LocalStack: {container_manager.errors.get('localstack', 'unavailable')}")
    return container_manager.containers["localstack"]


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

    from sagaz.storage.backends.postgresql.saga import PostgreSQLSagaStorage

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

    from sagaz.storage.backends.redis.saga import RedisSagaStorage

    def factory(**kwargs):
        return RedisSagaStorage(redis_url=redis_url, **kwargs)

    return factory
