# Coverage 95%+ Action Plan (Phases 1+2 Focus)

**Current Coverage**: 87%  
**Target**: 95%+  
**Gap**: Missing ~400 statements

## ROI Analysis: Best Targets for 95%+ Coverage

Based on the coverage report, here are files ordered by **impact** (missing statements × usage):

| File | Coverage | Missing Stmts | Priority | Est. Hours |
|------|----------|---------------|----------|------------|
| **CLI dry_run.py** | 42% | 219 | 🔴 **HIGH** | 6h |
| **Redis snapshot.py** | 21% | 123 | 🔴 **HIGH** | 4h |
| **S3 snapshot.py** | 16% | 177 | 🟡 MEDIUM | 6h |
| **CLI examples.py** | 69% | 61 | 🟡 MEDIUM | 3h |
| **Flask integration** | 49% | 63 | 🟡 MEDIUM | 3h |
| **FastAPI integration** | 46% | 59 | 🟡 MEDIUM | 3h |
| **Context.py** | 77% | 51 | 🟡 MEDIUM | 2h |
| **CLI replay.py** | 89% | 27 | 🟢 LOW | 2h |
| **Storage manager** | 91% | 23 | 🟢 LOW | 1h |
| **CLI project.py** | 82% | 18 | 🟢 LOW | 1h |
| **PostgreSQL snapshot** | 82% | 17 | 🟢 LOW | 1h |

---

## Phase 1: High-ROI Targets (24 hours) → **92% Coverage**

Focus on **most impactful** files that will get us to 92% quickly.

### 1.1 CLI Dry-Run Module (6 hours) - **+219 statements**

**File**: `sagaz/cli/dry_run.py`  
**Current**: 42% (204/423 covered)  
**Target**: 85%+ (360/423 covered)

**Missing areas**:
- Lines 158-185: Error display formatting
- Lines 272-280: Saga discovery logic
- Lines 319-336: DAG visualization
- Lines 441-464: Interactive validation
- Lines 555-580: Simulation execution
- Lines 631-679: Result formatting

**Test strategy**:
```python
# tests/unit/cli/test_dry_run.py
def test_validate_cmd_success(runner, tmp_path):
    """Test validate command with valid saga project."""
    
def test_validate_cmd_missing_config(runner, tmp_path):
    """Test validate with missing config file."""
    
def test_simulate_cmd_shows_dag(runner, tmp_path):
    """Test simulate command displays execution DAG."""
    
def test_dry_run_error_formatting(runner):
    """Test error display with rich formatting."""
```

**Impact**: +2.6% coverage (219/8359)

---

### 1.2 Redis Snapshot Storage (4 hours) - **+123 statements**

**File**: `sagaz/storage/backends/redis/snapshot.py`  
**Current**: 21% (41/164 covered)  
**Target**: 90%+ (148/164 covered)

**Missing areas**:
- Lines 72-83: `initialize()` method
- Lines 87-96: `save_snapshot()` method
- Lines 116-121: `get_snapshot()` method
- Lines 125-130: `list_snapshots()` method
- Lines 134-155: `get_latest_snapshot()` method
- Lines 161-197: Query and filtering logic
- Lines 201-253: Cleanup methods

**Test strategy**:
```python
# tests/unit/storage/backends/test_snapshot_redis.py
@pytest.mark.asyncio
async def test_redis_snapshot_save_and_get():
    """Test saving and retrieving snapshots from Redis."""
    storage = RedisSnapshotStorage("redis://localhost:6379")
    await storage.initialize()
    
    snapshot = SagaSnapshot(saga_id="test", status=SagaStatus.COMPLETED, ...)
    await storage.save_snapshot(snapshot)
    
    retrieved = await storage.get_snapshot("test", snapshot.version)
    assert retrieved.saga_id == "test"

async def test_redis_snapshot_list_snapshots():
    """Test listing all snapshots for a saga."""
    
async def test_redis_snapshot_cleanup_expired():
    """Test cleanup of expired snapshots."""
```

**Impact**: +1.5% coverage (123/8359)

---

### 1.3 FastAPI + Flask Integrations (6 hours) - **+122 statements**

**Files**: 
- `sagaz/integrations/fastapi.py` (46% → 90%) - 59 missing
- `sagaz/integrations/flask.py` (49% → 90%) - 63 missing

**Missing areas (FastAPI)**:
- Lines 182-200: Middleware implementation
- Lines 245-266: Error handling
- Lines 295-366: Health endpoints

**Missing areas (Flask)**:
- Lines 167-184: Before/after request handlers
- Lines 234-260: Error handlers
- Lines 291-363: Blueprint registration

**Test strategy**:
```python
# tests/unit/integrations/test_fastapi_coverage.py
@pytest.mark.asyncio
async def test_fastapi_middleware_executes_saga():
    """Test FastAPI middleware executes saga on request."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    
    app = FastAPI()
    # Add Sagaz middleware
    client = TestClient(app)
    response = client.get("/test-endpoint")
    assert response.status_code == 200

async def test_fastapi_error_handling():
    """Test error handling in FastAPI integration."""

async def test_fastapi_health_endpoint():
    """Test health check endpoint."""

# tests/unit/integrations/test_flask_coverage.py
def test_flask_before_request_saga():
    """Test Flask before_request handler."""
    
def test_flask_error_handlers():
    """Test Flask error handlers."""
```

**Impact**: +1.5% coverage (122/8359)

---

### 1.4 Context Streaming (2 hours) - **+51 statements**

**File**: `sagaz/core/context.py`  
**Current**: 77% (176/227 covered)  
**Target**: 95%+ (215/227 covered)

**Missing areas**:
- Lines 175-180: External storage initialization
- Lines 186-217: Streaming context methods
- Lines 227-264: Context serialization
- Lines 267-286: External storage operations

**Test strategy**:
```python
# tests/unit/core/test_context_streaming.py
@pytest.mark.asyncio
async def test_context_external_storage():
    """Test context with external storage (S3/Redis)."""
    
async def test_context_streaming_large_payload():
    """Test streaming context with large payloads."""
    
async def test_context_serialization():
    """Test context serialization/deserialization."""
```

**Impact**: +0.6% coverage (51/8359)

---

### 1.5 CLI Examples Module (3 hours) - **+61 statements**

**File**: `sagaz/cli/examples.py`  
**Current**: 69% (153/214 covered)  
**Target**: 90%+ (193/214 covered)

**Missing areas**:
- Lines 310-320: Example cleanup
- Lines 325-334: Error handling
- Lines 561-573: Interactive menu
- Lines 596-616: Example execution

**Test strategy**:
```python
# tests/unit/cli/test_examples_coverage.py
def test_examples_list(runner):
    """Test listing available examples."""
    
def test_examples_run_success(runner):
    """Test running an example successfully."""
    
def test_examples_cleanup(runner):
    """Test cleanup after example run."""
```

**Impact**: +0.7% coverage (61/8359)

---

## Phase 1 Summary

**Total effort**: 21 hours  
**Coverage gain**: +6.9% (576/8359 statements)  
**New coverage**: 87% + 6.9% = **~94%** ✅

---

## Phase 2: Polish to 95%+ (6 hours) → **95%+ Coverage**

Complete the remaining gaps to exceed 95%.

### 2.1 PostgreSQL Snapshot (1 hour) - **+17 statements**

**File**: `sagaz/storage/backends/postgresql/snapshot.py`  
**Current**: 82% (84/101 covered)  
**Target**: 95%+ (96/101 covered)

**Missing**: Lines 300-303, 328-345, 362-379

**Test strategy**:
```python
# tests/unit/storage/backends/test_snapshot_postgresql_extended.py
async def test_postgresql_snapshot_edge_cases():
    """Test edge cases: empty results, null values, etc."""
    
async def test_postgresql_snapshot_concurrent_access():
    """Test concurrent snapshot saves."""
```

**Impact**: +0.2% coverage

---

### 2.2 Storage Manager (1 hour) - **+23 statements**

**File**: `sagaz/storage/manager.py`  
**Current**: 91% (189/212 covered)  
**Target**: 98%+ (208/212 covered)

**Missing**: Lines 360-383, 408-422

**Test strategy**:
```python
# tests/unit/storage/test_manager_extended.py
async def test_manager_backend_switching():
    """Test switching between storage backends."""
    
async def test_manager_health_checks():
    """Test health check aggregation."""
```

**Impact**: +0.3% coverage

---

### 2.3 CLI Project Module (1 hour) - **+18 statements**

**File**: `sagaz/cli/project.py`  
**Current**: 82% (88/106 covered)  
**Target**: 95%+ (101/106 covered)

**Missing**: Lines 162-164, 192-193, 220-225

**Test strategy**:
```python
# tests/unit/cli/test_project_extended.py
def test_check_missing_files(runner):
    """Test check command with missing files."""
    
def test_list_sagas_empty_project(runner):
    """Test list command on empty project."""
```

**Impact**: +0.2% coverage

---

### 2.4 Core Modules Polish (3 hours) - **+40 statements**

**Files**:
- `sagaz/core/env.py` (85% → 95%) - 12 missing
- `sagaz/dry_run.py` (92% → 97%) - 17 missing
- `sagaz/core/saga.py` (98% → 99%) - 10 missing

**Test strategy**:
```python
# tests/unit/core/test_env_extended.py
def test_env_validation_edge_cases():
    """Test environment validation with edge cases."""

# tests/unit/test_dry_run_extended.py
async def test_dry_run_resource_cleanup():
    """Test resource cleanup in dry-run mode."""

# tests/unit/core/test_saga_extended.py
async def test_saga_state_recovery():
    """Test saga state recovery after crash."""
```

**Impact**: +0.5% coverage

---

## Phase 2 Summary

**Total effort**: 6 hours  
**Coverage gain**: +1.2% (98/8359 statements)  
**Final coverage**: 94% + 1.2% = **~95.2%** ✅✅

---

## Total Implementation Plan

| Phase | Duration | Target Coverage | Key Deliverables |
|-------|----------|-----------------|------------------|
| **Phase 1** | 21 hours | **~94%** | CLI dry-run, Redis snapshot, integrations |
| **Phase 2** | 6 hours | **~95.2%** | PostgreSQL snapshot, manager, core polish |
| **Total** | **27 hours** | **95%+** | Full test coverage |

---

## Implementation Priority Order

### Week 1 (Day 1-3): High-Impact CLI + Storage
1. **Day 1** (8h): CLI dry-run tests (6h) + Redis snapshot (2h start)
2. **Day 2** (8h): Redis snapshot (2h finish) + FastAPI tests (4h) + Flask tests (2h)
3. **Day 3** (5h): Context streaming (2h) + CLI examples (3h)

**Milestone**: ~94% coverage achieved ✅

### Week 2 (Day 4-5): Polish to 95%+
4. **Day 4** (4h): PostgreSQL snapshot (1h) + Storage manager (1h) + CLI project (1h) + Core modules (1h)
5. **Day 5** (2h): Core modules polish (2h) + Final validation

**Milestone**: 95%+ coverage achieved ✅✅

---

## Success Criteria

✅ **Overall coverage**: 95%+ (target: 95.2%)  
✅ **Core modules**: 98%+ (decorators, saga, outbox)  
✅ **Storage backends**: 90%+ (all snapshot implementations)  
✅ **CLI modules**: 85%+ (dry-run, examples, project)  
✅ **Integrations**: 90%+ (FastAPI, Flask)  
✅ **No flaky tests**: All tests deterministic and fast  
✅ **CI/CD passes**: All checks green  

---

## Files to Create

### New Test Files (8 files)
1. `tests/unit/cli/test_dry_run_extended.py` - CLI dry-run coverage
2. `tests/unit/storage/backends/test_snapshot_redis.py` - Redis snapshot tests
3. `tests/unit/integrations/test_fastapi_coverage.py` - FastAPI coverage
4. `tests/unit/integrations/test_flask_coverage.py` - Flask coverage
5. `tests/unit/core/test_context_streaming.py` - Context streaming tests
6. `tests/unit/cli/test_examples_coverage.py` - CLI examples coverage
7. `tests/unit/storage/backends/test_snapshot_postgresql_extended.py` - PostgreSQL polish
8. `tests/unit/storage/test_manager_extended.py` - Storage manager polish

### Extended Test Files (3 files)
9. `tests/unit/cli/test_project_extended.py` - CLI project coverage
10. `tests/unit/core/test_env_extended.py` - Env validation tests
11. `tests/unit/test_dry_run_extended.py` - Dry-run resource cleanup

---

## Notes

- **S3 snapshot.py** (16% coverage, 177 missing) is **not included** - It's optional/low priority
- Focus is on **commonly used** modules that impact production deployments
- All tests should be **fast** (<1s each) and **deterministic** (no flakiness)
- Use **mocking** for external dependencies (Redis, PostgreSQL, S3)
- Parallel execution enabled (`pytest -n auto`) for fast CI/CD

---

## Post-95% Coverage: Optional Enhancements

After reaching 95%, consider:
- **S3 snapshot.py** → 90% (6 hours) - If S3 support is critical
- **CLI help/version** → 100% - Trivial commands
- **100% coverage goal** - Perfectionism (not recommended, diminishing returns)

---

## Command to Run

```bash
# Run all tests with coverage
make coverage MISSING=yes

# Run specific test file
.venv/bin/pytest tests/unit/cli/test_dry_run_extended.py -xvs --cov=sagaz.cli.dry_run --cov-report=term-missing

# Check coverage for single module
.venv/bin/pytest --cov=sagaz.storage.backends.redis.snapshot --cov-report=term-missing
```

---

**FOCUS**: Phases 1+2 → **95%+ coverage in 27 hours (3-4 days)**  
**ROI**: Maximum coverage gain with minimum effort ✨
