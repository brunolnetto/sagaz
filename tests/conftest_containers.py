"""
Parallel container initialization plugin for pytest.

Starts all test containers in parallel at session start to minimize total startup time.
No environment variables needed - tests automatically detect container availability.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest


class ContainerManager:
    """Manages parallel initialization of test containers."""

    def __init__(self):
        self.containers = {}
        self.available = {}
        self.errors = {}
        self._lock = threading.Lock()

    def start_postgres(self):
        """Start PostgreSQL container."""
        try:
            from testcontainers.postgres import PostgresContainer
            
            container = PostgresContainer("postgres:16-alpine")
            container.start()
            return ("postgres", container, None)
        except Exception as e:
            return ("postgres", None, str(e))

    def start_redis(self):
        """Start Redis container."""
        try:
            from testcontainers.redis import RedisContainer
            
            container = RedisContainer("redis:7-alpine")
            container.start()
            return ("redis", container, None)
        except Exception as e:
            return ("redis", None, str(e))

    def start_rabbitmq(self):
        """Start RabbitMQ container."""
        try:
            from testcontainers.rabbitmq import RabbitMqContainer
            
            container = RabbitMqContainer("rabbitmq:3.12-alpine")
            container.start()
            return ("rabbitmq", container, None)
        except Exception as e:
            return ("rabbitmq", None, str(e))

    def start_kafka(self):
        """Start Kafka container."""
        try:
            from testcontainers.kafka import KafkaContainer
            
            container = KafkaContainer("confluentinc/cp-kafka:7.6.0")
            container.start()
            return ("kafka", container, None)
        except Exception as e:
            return ("kafka", None, str(e))

    def start_localstack(self):
        """Start LocalStack container for S3."""
        try:
            from testcontainers.localstack import LocalStackContainer
            
            container = LocalStackContainer("localstack/localstack:3.0")
            container.with_services("s3")
            container.start()
            return ("localstack", container, None)
        except Exception as e:
            return ("localstack", None, str(e))

    def initialize_all(self):
        """Initialize all containers in parallel."""
        print("\n🚀 Starting test containers in parallel...")
        start_time = time.time()
        
        starters = [
            self.start_postgres,
            self.start_redis,
            self.start_rabbitmq,
            self.start_kafka,
            self.start_localstack,
        ]

        with ThreadPoolExecutor(max_workers=len(starters)) as executor:
            futures = [executor.submit(starter) for starter in starters]
            
            for future in as_completed(futures, timeout=180):
                name, container, error = future.result()
                
                if container:
                    self.containers[name] = container
                    self.available[name] = True
                    print(f"  ✅ {name}: ready")
                else:
                    self.available[name] = False
                    self.errors[name] = error
                    print(f"  ⏭️  {name}: {error[:50]}...")

        elapsed = time.time() - start_time
        available_count = sum(self.available.values())
        print(f"📦 {available_count}/{len(starters)} containers ready in {elapsed:.1f}s\n")

    def stop_all(self):
        """Stop all running containers."""
        print("\n🧹 Stopping containers...")
        for name, container in self.containers.items():
            try:
                container.stop()
            except Exception as e:
                print(f"  ⚠️  {name}: {e}")


# Global instance
_manager = None


def pytest_configure(config):
    """Initialize containers when pytest starts."""
    global _manager
    
    try:
        import testcontainers
        _manager = ContainerManager()
        _manager.initialize_all()
    except ImportError:
        print("\n⏭️  testcontainers not available - integration tests will skip\n")
        _manager = None
    except Exception as e:
        print(f"\n⚠️  Container initialization failed: {e}\n")
        _manager = None


def pytest_unconfigure(config):
    """Stop containers when pytest exits."""
    if _manager:
        _manager.stop_all()


@pytest.fixture(scope="session")
def container_manager():
    """Provide access to the container manager."""
    return _manager
