# Container Optimization Plan for Integration Tests

## Current Status

**Problem**: Integration test containers start sequentially, causing long test suite startup (120-180s).

## Proposed Solution: Parallel Container Initialization

### Architecture

1. **Pytest Plugin** (`tests/conftest_containers.py`)
   - Implements `pytest_configure()` hook
   - Starts all containers in parallel using `ThreadPoolExecutor`
   - Stores container status in global manager
   - Implements `pytest_unconfigure()` for cleanup

2. **Smart Fixtures** (updated `tests/conftest.py`)
   - No env vars needed (SAGAZ_KAFKA_TESTS, SAGAZ_S3_TESTS removed)
   - Auto-detect container availability
   - Skip gracefully if container unavailable
   - Simple fixture signatures: `def postgres_container(container_manager)`

3. **Benefits**
   - ✅ All 5 containers start simultaneously  
   - ✅ Total time = slowest container (not sum of all)
   - ✅ Auto-detection (no manual configuration)
   - ✅ Tests run if available, skip if not
   - ✅ Clean separation of concerns

### Implementation

#### File 1: `tests/conftest_containers.py` (CREATED)
```python
# Parallel container manager
# - ThreadPoolExecutor starts all containers
# - 180s total timeout
# - Graceful error handling
```

#### File 2: `tests/conftest.py` (TO UPDATE)
```python
# Add to top:
pytest_plugins = ["tests.conftest_containers"]

# Replace fixtures:
@pytest.fixture(scope="session")
def postgres_container(container_manager):
    if not container_manager or not container_manager.available.get("postgres"):
        pytest.skip("PostgreSQL unavailable")
    return container_manager.containers["postgres"]
```

### Expected Results

**Before**:
- Postgres: 10s
- Redis: 5s
- RabbitMQ: 15s
- Kafka: 90s
- LocalStack: 30s
- **Total: 150s sequential**

**After**:
- All start in parallel
- **Total: ~90s (longest = Kafka)**
- **40% faster startup**

### Migration Steps

1. ✅ Create `conftest_containers.py` with parallel manager
2. ⏳ Update `conftest.py` fixtures to use manager
3. ⏳ Remove env var checks (SAGAZ_KAFKA_TESTS, SAGAZ_S3_TESTS)
4. ⏳ Update S3 integration test fixtures
5. ⏳ Test with: `pytest tests/integration/ -v`

### Edge Cases Handled

- **No Docker**: Manager returns None, all tests skip
- **Partial failure**: Available containers work, others skip
- **Timeout**: 180s total limit, then skip remaining
- **Cleanup**: All containers stopped in `pytest_unconfigure()`

### API Changes

**Before**:
```bash
SAGAZ_KAFKA_TESTS=1 pytest -k kafka  # Manual opt-in
```

**After**:
```bash
pytest  # Auto-detects, runs if available
```

## Current Files

- ✅ `tests/conftest_containers.py` - Created (158 lines)
- ⏳ `tests/conftest.py` - Needs fixture updates
- ⏳ `tests/integration/test_s3_snapshot_integration.py` - Remove env var check

## Next Steps

Complete the fixture migration in `conftest.py` by replacing the sequential
container initialization with the parallel manager approach.

