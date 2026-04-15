"""
Lazy container initialization plugin for pytest.

Containers are only started when a test actually requests them via fixtures.
Use ``--no-containers`` to skip all container-dependent tests instantly.

Environment variable ``SAGAZ_NO_CONTAINERS=1`` has the same effect.

Parallel mode: set ``SAGAZ_PARALLEL_CONTAINERS=1`` or pass ``--parallel-containers``
to pre-start all containers simultaneously at session start (faster for full runs).
"""

import os
import subprocess
import threading
import time

import pytest

# Disable Ryuk (the testcontainers reaper) to avoid 409 name conflicts on restart.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# Per-container startup timeout in seconds.
_CONTAINER_TIMEOUT = 120


def _cleanup_stale_containers() -> None:
    """Remove any stopped test containers left over from previous runs."""
    try:
        subprocess.run(
            ["docker", "container", "prune", "-f"],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass  # Best-effort; don't block test startup


class ContainerManager:
    """Manages lazy, on-demand initialization of test containers."""

    def __init__(self):
        self.containers: dict[str, object] = {}
        self.available: dict[str, bool] = {}
        self.errors: dict[str, str] = {}
        self._lock = threading.Lock()
        # Events to wait for container readiness (used in parallel mode)
        self._events: dict[str, threading.Event] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start(self, name: str, factory):
        """Start a container (thread-safe, idempotent)."""
        with self._lock:
            if name in self.available:
                return  # already attempted
            if name in self._events:
                # Another thread is starting it; wait for it
                ev = self._events[name]
            else:
                ev = threading.Event()
                self._events[name] = ev
                # We own the startup
                ev = None  # Sentinel to indicate we proceed with startup
        if ev is not None:
            # Another thread owns startup; wait then return
            ev.wait(timeout=_CONTAINER_TIMEOUT + 30)
            return

        try:
            container = factory()
            with self._lock:
                self.containers[name] = container
                self.available[name] = True
            print(f"  ✅ {name}: ready")
        except Exception as e:
            with self._lock:
                self.available[name] = False
                self.errors[name] = str(e)
            print(f"  ⏭️  {name}: {str(e)[:60]}...")
        finally:
            self._events[name].set()

    # ------------------------------------------------------------------
    # Public: called lazily by fixtures
    # ------------------------------------------------------------------

    def ensure_postgres(self):
        def _factory():
            from testcontainers.postgres import PostgresContainer

            c = PostgresContainer("postgres:16-alpine")
            c.start()
            return c

        self._start("postgres", _factory)

    def ensure_redis(self):
        def _factory():
            from testcontainers.redis import RedisContainer

            c = RedisContainer("redis:7-alpine")
            c.start()
            return c

        self._start("redis", _factory)

    def ensure_rabbitmq(self):
        def _factory():
            from testcontainers.rabbitmq import RabbitMqContainer

            c = RabbitMqContainer("rabbitmq:3.12-alpine")
            # Note: RabbitMqContainer does not accept timeout parameter (unlike KafkaContainer)
            c.start()
            return c

        self._start("rabbitmq", _factory)

    def ensure_kafka(self):
        def _factory():
            from testcontainers.kafka import KafkaContainer

            c = KafkaContainer("confluentinc/cp-kafka:7.6.0")
            c.start(timeout=120)
            return c

        self._start("kafka", _factory)

    def ensure_localstack(self):
        def _factory():
            from testcontainers.localstack import LocalStackContainer

            c = LocalStackContainer("localstack/localstack:3.0")
            c.with_services("s3")
            c.start(timeout=180)
            return c

        self._start("localstack", _factory)

    def stop_all(self):
        """Stop all running containers."""
        if not self.containers:
            return
        print("\n🧹 Stopping containers...")
        for name, container in self.containers.items():
            try:
                container.stop()
            except Exception as e:
                print(f"  ⚠️  {name}: {e}")

    def start_all_parallel(self) -> None:
        """Start all supported containers simultaneously using background threads.

        Called once at session start when ``--parallel-containers`` or
        ``SAGAZ_PARALLEL_CONTAINERS=1`` is set.  Tests requested later will find
        their container already running (or already-failed) without waiting.
        """
        factories = {
            "postgres": self.ensure_postgres,
            "redis": self.ensure_redis,
            "rabbitmq": self.ensure_rabbitmq,
            "kafka": self.ensure_kafka,
            "localstack": self.ensure_localstack,
        }
        print("\n🚀 Pre-starting all containers in parallel…")
        threads = []
        for fn in factories.values():
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            threads.append(t)
        # Wait for all (with generous ceiling so slow images don't block forever)
        for t in threads:
            t.join(timeout=_CONTAINER_TIMEOUT + 60)


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------

_manager: ContainerManager | None = None
_no_containers: bool = False


def pytest_addoption(parser):
    parser.addoption(
        "--no-containers",
        action="store_true",
        default=False,
        help="Skip all tests that require Docker containers.",
    )
    parser.addoption(
        "--parallel-containers",
        action="store_true",
        default=False,
        help="Pre-start all containers in parallel at session start for faster runs.",
    )


def _is_docker_available() -> bool:
    """Return True if Docker daemon is reachable within 3 seconds."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def pytest_configure(config):
    """Set up the container manager (no containers started yet)."""
    global _manager, _no_containers

    _no_containers = (
        config.getoption("--no-containers", default=False)
        or os.environ.get("SAGAZ_NO_CONTAINERS", "") == "1"
    )

    if _no_containers:
        print("\n⏭️  --no-containers: all container-dependent tests will be skipped\n")
        return

    if not _is_docker_available():
        print("\n⏭️  Docker not available — container-dependent tests will skip\n")
        _no_containers = True
        return

    _cleanup_stale_containers()

    try:
        import testcontainers  # noqa: F401

        _manager = ContainerManager()
    except ImportError:
        print("\n⏭️  testcontainers not installed — integration tests will skip\n")


def pytest_sessionstart(session):
    """Optionally pre-start all containers in parallel."""
    parallel = (
        session.config.getoption("--parallel-containers", default=False)
        or os.environ.get("SAGAZ_PARALLEL_CONTAINERS", "") == "1"
    )
    if parallel and _manager is not None:
        _manager.start_all_parallel()


def pytest_unconfigure(config):
    """Stop containers when pytest exits."""
    if _manager:
        _manager.stop_all()


@pytest.fixture(scope="session")
def container_manager():
    """Provide access to the container manager."""
    if _no_containers:
        pytest.skip("--no-containers")
    return _manager
