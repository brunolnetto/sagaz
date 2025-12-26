# Testing Guide

How to run tests for thesagaz library.

## Quick Start

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage
pytest --cov=sage --cov-report=html
```

## Test Structure

```
tests/
├── unit/                    # Fast, isolated tests
│   ├── test_core.py         # Saga engine tests
│   ├── test_context.py      # SagaContext tests
│   ├── test_types.py        # Type/enum tests
│   └── outbox/
│       ├── test_worker.py   # OutboxWorker tests
│       ├── test_storage.py  # Storage backend tests
│       └── test_brokers.py  # Broker tests
│
├── integration/             # Tests with real dependencies
│   ├── test_postgresql.py   # PostgreSQL integration
│   ├── test_rabbitmq.py     # RabbitMQ integration
│   └── test_kafka.py        # Kafka integration
│
└── conftest.py              # Shared fixtures
```

## Running Specific Tests

```bash
# Unit tests only (fast)
pytest tests/unit/

# Integration tests (requires Docker)
pytest tests/integration/ --integration

# Specific file
pytest tests/unit/test_core.py

# Specific test
pytest tests/unit/test_core.py::test_saga_execute_success

# With verbose output
pytest -v tests/unit/
```

## Integration Tests

Integration tests require Docker containers:

```bash
# Start containers
docker-compose -f docker-compose.test.yml up -d

# Run integration tests
pytest tests/integration/ --integration

# Stop containers
docker-compose -f docker-compose.test.yml down
```

## Coverage

```bash
# Run with coverage
pytest --cov=sage --cov-report=term-missing

# Generate HTML report
pytest --cov=sage --cov-report=html
open htmlcov/index.html

# Check minimum coverage
pytest --cov=sage --cov-fail-under=80
```

## Fixtures

Common fixtures in `conftest.py`:

```python
@pytest.fixture
def saga_context():
    """Create a fresh SagaContext for testing."""
    return SagaContext(saga_id="test-saga-001")

@pytest.fixture
async def memory_storage():
    """In-memory storage for testing."""
    storage = InMemoryOutboxStorage()
    await storage.initialize()
    yield storage
    await storage.close()

@pytest.fixture
async def memory_broker():
    """In-memory broker for testing."""
    broker = InMemoryBroker()
    await broker.connect()
    yield broker
    await broker.close()
```

## Writing Tests

### Unit Test Example

```python
import pytest
from sagaz import Saga, SagaContext

async def test_saga_executes_all_steps():
    # Arrange
    executed = []
    
    async def step1(ctx):
        executed.append("step1")
    
    async def step2(ctx):
        executed.append("step2")
    
    saga = (
        Saga("test")
        .step("first").action(step1)
        .step("second").action(step2)
        .build()
    )
    
    # Act
    result = await saga.execute(SagaContext())
    
    # Assert
    assert result.status == "completed"
    assert executed == ["step1", "step2"]
```

### Async Test Example

```python
import pytest

@pytest.mark.asyncio
async def test_worker_processes_events(memory_storage, memory_broker):
    # Insert test event
    await memory_storage.save_event(OutboxEvent(...))
    
    # Create worker
    worker = OutboxWorker(memory_storage, memory_broker)
    
    # Process
    processed = await worker.process_batch()
    
    # Verify
    assert processed == 1
```

## CI/CD

GitHub Actions workflow:

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      
      - name: Install dependencies
        run: pip install -e ".[dev]"
      
      - name: Run tests
        run: pytest --cov=sage --cov-fail-under=80
```

## Troubleshooting

### Tests Hang

```bash
# Set timeout
pytest --timeout=30

# Run with debug output
pytest -v --tb=long
```

### Async Issues

```bash
# Ensure pytest-asyncio is installed
pip install pytest-asyncio

# Add to conftest.py
pytest_plugins = ('pytest_asyncio',)
```

---

## Related

- [Benchmarking Guide](../guides/benchmarking.md)
- [Contributing](contributing.md)
