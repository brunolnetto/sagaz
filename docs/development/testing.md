# Testing Guide

How to run and write tests for the Sagaz library.

---

## TDD Workflow

All production code must be developed using **red-green-refactor**:

1. **Red** — Write a failing test that describes the desired behaviour.
2. **Green** — Write the minimal code to make the test pass.
3. **Refactor** — Clean up without changing observable behaviour; keep all tests green.

Never write implementation code before a failing test exists.

---

## Test Structure

Tests are separated into four categories. **Do not mix them.**

```
tests/
├── unit/                    # Fast, isolated — no I/O, no containers
│   ├── test_core.py
│   ├── test_context.py
│   ├── test_types.py
│   └── outbox/
│       ├── test_worker.py
│       ├── test_storage.py
│       └── test_brokers.py
│
├── integration/             # Real dependencies via testcontainers
│   ├── test_postgresql.py
│   ├── test_rabbitmq.py
│   └── test_kafka.py
│
├── e2e/                     # Full workflow across services
│   └── test_order_saga.py
│
├── performance/             # Benchmarks and throughput assertions
│   └── test_saga_throughput.py
│
└── conftest.py              # Shared fixtures
```

---

## Quick Start

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage (enforces 95% threshold)
make coverage
```

---

## Running by Category

```bash
# Unit tests only (fast, no dependencies)
pytest tests/unit/

# Integration tests (spins up containers automatically)
pytest tests/integration/

# End-to-end tests
pytest tests/e2e/

# Performance benchmarks
pytest tests/performance/

# Single file or test
pytest tests/unit/test_core.py::test_saga_execute_success -v
```

---

## Integration & E2E Tests

Integration and e2e tests use **testcontainers** — no manual Docker setup required.
Containers are started and stopped automatically by the fixture.

```python
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16") as pg:
        yield pg.get_connection_url()
```

If testcontainers is unavailable, start dependencies manually:

```bash
docker compose up -d
pytest tests/integration/
docker compose down
```

---

## Coverage Policy

- **Minimum threshold**: 95% — PRs that drop below this will fail CI.
- Check before opening a PR:
  ```bash
  make coverage              # terminal report
  make coverage-html         # HTML report → htmlcov/index.html
  ```
- The CI pipeline enforces the threshold via `--cov-fail-under=95`.

---

## Writing Tests

### Async Tests

All saga code is async. Use `@pytest.mark.asyncio`:

```python
import pytest
from sagaz import Saga, SagaContext

@pytest.mark.asyncio
async def test_saga_executes_all_steps():
    # Arrange
    executed = []

    async def step1(ctx: SagaContext):
        executed.append("step1")

    async def step2(ctx: SagaContext):
        executed.append("step2")

    saga = Saga("test")
    await saga.add_step("first", action=step1)
    await saga.add_step("second", action=step2)

    # Act
    result = await saga.execute(SagaContext(saga_id="test-001"))

    # Assert
    assert result.status == "completed"
    assert executed == ["step1", "step2"]
```

### Common Fixtures

```python
@pytest.fixture
def saga_context():
    return SagaContext(saga_id="test-saga-001")

@pytest.fixture
async def memory_storage():
    storage = InMemoryOutboxStorage()
    await storage.initialize()
    yield storage
    await storage.close()

@pytest.fixture
async def memory_broker():
    broker = InMemoryBroker()
    await broker.connect()
    yield broker
    await broker.close()
```

---

## CI/CD

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
      - name: Run tests with coverage
        run: pytest --cov=sagaz --cov-fail-under=95
```

---

## Troubleshooting

```bash
# Set per-test timeout to catch hangs
pytest --timeout=30

# Verbose output with full tracebacks
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
