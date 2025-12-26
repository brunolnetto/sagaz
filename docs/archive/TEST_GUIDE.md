# Testing Guide

## Quick Start

### Run All Unit Tests
```bash
# Fast - no Docker required (~2 minutes)
pytest tests/ -v

# With coverage report
pytest tests/ --cov=sage --cov-report=term-missing -v
```

### Run Integration Tests
```bash
# Requires Docker to be running
docker ps

# Run PostgreSQL integration tests (~70 seconds)
RUN_INTEGRATION=1 pytest tests/test_integration_containers.py::TestPostgreSQLOutboxStorageIntegration -v

# Run all integration tests (~5-10 minutes depending on containers)
RUN_INTEGRATION=1 pytest tests/test_integration_containers.py -v
```

### Run Specific Test Files
```bash
# Core saga tests
pytest tests/test_core.py -v

# Decorator/declarative API tests
pytest tests/test_decorators.py -v

# Storage tests
pytest tests/test_storage.py -v

# Outbox pattern tests
pytest tests/test_outbox.py -v

# Coverage improvement tests
pytest tests/test_coverage_improvements.py -v
pytest tests/test_coverage_final.py -v
```

## Test Organization

```
tests/
├── conftest.py                      # Shared fixtures
├── test_core.py                     # Core saga logic tests
├── test_decorators.py               # Declarative API tests
├── test_state_machine.py            # State machine tests
├── test_strategies.py               # Failure strategy tests
├── test_orchestrator.py             # Saga orchestrator tests
├── test_compensation_graph.py       # Compensation graph tests
├── test_monitoring.py               # Logging/metrics/tracing tests
├── test_storage.py                  # Storage backend tests
├── test_storage_*.py                # Storage-specific tests
├── test_outbox.py                   # Outbox pattern tests
├── test_outbox_*.py                 # Outbox-specific tests
├── test_coverage_improvements.py    # New coverage tests
├── test_coverage_final.py           # Final coverage tests
└── test_integration_containers.py   # Docker integration tests
```

## Coverage Reports

### Terminal Report
```bash
# Basic coverage
pytest tests/ --cov=sage

# With missing lines
pytest tests/ --cov=sage --cov-report=term-missing

# Skip covered files
pytest tests/ --cov=sage --cov-report=term-missing:skip-covered
```

### HTML Report
```bash
# Generate HTML report
pytest tests/ --cov=sage --cov-report=html

# Open in browser
open htmlcov/index.html
```

### Coverage by Module
```bash
# Specific module
pytest tests/ --cov=sage.core --cov-report=term

# Multiple modules
pytest tests/ --cov=sage.core --cov=sage.decorators --cov-report=term
```

## Test Markers

### Skip Integration Tests
```bash
# These are skipped by default
pytest tests/

# Force run integration tests
RUN_INTEGRATION=1 pytest tests/
```

### Run Specific Test Classes
```bash
# Run a specific test class
pytest tests/test_core.py::TestSagaExecution -v

# Run a specific test method
pytest tests/test_core.py::TestSagaExecution::test_saga_with_three_steps -v
```

### Run Tests Matching Pattern
```bash
# Run tests with "timeout" in the name
pytest tests/ -k "timeout" -v

# Exclude certain tests
pytest tests/ -k "not integration" -v

# Multiple patterns
pytest tests/ -k "saga and not integration" -v
```

## Debugging Tests

### Verbose Output
```bash
# Show test names
pytest tests/ -v

# Extra verbose (show all output)
pytest tests/ -vv

# Show print statements
pytest tests/ -s
```

### Stop on First Failure
```bash
# Stop immediately on failure
pytest tests/ -x

# Stop after N failures
pytest tests/ --maxfail=3
```

### Run Last Failed Tests
```bash
# Rerun only failed tests from last run
pytest tests/ --lf

# Run failed tests first, then others
pytest tests/ --ff
```

### Debug with PDB
```bash
# Drop into debugger on failure
pytest tests/ --pdb

# Drop into debugger at start of test
pytest tests/ --trace
```

## Parallel Execution

```bash
# Run tests in parallel (faster!)
pytest tests/ -n auto

# Specify number of workers
pytest tests/ -n 4

# With coverage (use pytest-cov)
pytest tests/ -n auto --cov=sage
```

## Watch Mode

```bash
# Re-run tests on file changes
pytest-watch tests/

# With specific options
ptw tests/ -- -v --cov=sage
```

## Performance

### Test Execution Times
```bash
# Show slowest 10 tests
pytest tests/ --durations=10

# Show all test durations
pytest tests/ --durations=0
```

### Timeouts
```bash
# Set global timeout (seconds)
pytest tests/ --timeout=30

# Specific test timeout (in test code)
@pytest.mark.timeout(10)
async def test_something():
    ...
```

## CI/CD Integration

### GitHub Actions
```yaml
- name: Run tests with coverage
  run: |
    pytest tests/ --cov=sage --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
```

### GitLab CI
```yaml
test:
  script:
    - pytest tests/ --cov=sage --cov-report=term --cov-report=html
  coverage: '/TOTAL.*\s+(\d+%)$/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

## Troubleshooting

### Docker Not Running
```
Error: Cannot connect to the Docker daemon
Solution: Start Docker Desktop or docker service
```

### Import Errors
```
Error: ModuleNotFoundError: No module named 'sage'
Solution: Install in development mode
  uv pip install -e .
  # or
  pip install -e .
```

### Timeout Errors in Integration Tests
```
Error: Container did not emit logs within timeout
Solution: 
  1. Increase Docker resources (Memory/CPU)
  2. Skip slow tests: pytest tests/ -k "not Kafka"
  3. Run tests sequentially: pytest tests/ -n 0
```

### Coverage Not Working
```
Error: No data to report
Solution: Install with dev dependencies
  uv pip install -e ".[dev]"
```

## Best Practices

1. **Run unit tests frequently** - They're fast (~2 min)
2. **Run integration tests before commits** - Ensure database compatibility
3. **Check coverage on new code** - Aim for 95%+ on new modules
4. **Use watch mode during development** - Instant feedback
5. **Run full suite before push** - Catch integration issues early

## Current Status

✅ 626 unit tests passing  
✅ 3 integration tests passing  
✅ 91-93% overall coverage  
✅ Zero failing tests  
✅ ~2 minute unit test runtime  
✅ ~70 second PostgreSQL integration test runtime  
