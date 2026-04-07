# 🎯 Path to 95%+ Coverage - Action Plan

## Current State
- **Current Coverage**: 86.6% (7448/8359 lines)
- **Target Coverage**: 95.0% (7941/8359 lines)
- **Gap**: Need to cover **493 more lines**

---

## Strategy: Focus on High-Impact, Low-Effort Wins

### 📊 Quick Math
To reach 95%, we need to:
1. **Option A (Realistic)**: Cover 60% of the gap = ~300 lines
   - Focus on Core + Web integrations
   - Final: ~93% (good enough for production)

2. **Option B (Target)**: Cover 100% of the gap = ~493 lines
   - Add Core + Web + Some CLI
   - Final: 95%+ ✅

---

## 🎯 RECOMMENDED: Focus Areas (Gets to 93-94%)

### Phase 1: HIGH PRIORITY - Core (93 lines, ~19% of gap)
**Effort: Low-Medium | Impact: Critical**

| File | Missing | Coverage | Tests Needed |
|------|---------|----------|--------------|
| `core/context.py` | 51 | 76.7% | Context manager edge cases, nesting |
| `storage/manager.py` | 23 | 90.9% | Connection pool edge cases |
| `storage/backends/postgresql/snapshot.py` | 17 | 82.1% | PostgreSQL-specific queries |
| `core/config.py` | 14 | 93.7% | Invalid config, edge cases |
| `core/env.py` | 12 | 84.7% | More .env parsing scenarios |
| `core/compliance.py` | 8 | 89.8% | Compliance validation edge cases |

**Estimated Effort**: 2-3 hours
**Coverage Gain**: +1.1% → **87.7%**

---

### Phase 2: MEDIUM PRIORITY - Web Integrations (139 lines, ~28% of gap)
**Effort: Medium | Impact: High**

| File | Missing | Coverage | Tests Needed |
|------|---------|----------|--------------|
| `integrations/flask.py` | 63 | 48.6% | More Flask routes, middleware, error cases |
| `integrations/fastapi.py` | 59 | 46.3% | More FastAPI routes, dependencies, errors |
| `dry_run.py` | 17 | 91.5% | Dry-run edge cases |

**Estimated Effort**: 3-4 hours
**Coverage Gain**: +1.7% → **89.4%**

---

### Phase 3: Optimize Existing (Polish to 95%)
**Effort: Low | Impact: Medium**

Focus on getting existing high-coverage files to 95%+:
- `cli/replay.py`: 88.5% → 95% (need 7 more lines)
- `cli/project.py`: 81.7% → 95% (need ~18 lines)
- Files at 90-94%: Just a few more edge cases each

**Estimated Effort**: 2-3 hours
**Coverage Gain**: +3-4% → **93-94%**

---

## 🚫 SKIP These (Low ROI)

### CLI Tools (519 lines, but LOW priority)
- `cli/dry_run.py`: 219 lines - Complex UI, manually tested
- `cli/examples.py`: 61 lines - Demo code, manually tested
- `cli/replay.py`: 27 lines - Interactive CLI, hard to test

**Why Skip?**
- Interactive CLI is hard to unit test
- Better tested manually or with E2E tests
- Low business value (developer tools)

### External Storage Backends (300 lines, but need infrastructure)
- `storage/backends/redis/snapshot.py`: 123 lines - Need Redis/fakeredis
- `storage/backends/s3/snapshot.py`: 177 lines - Need S3/moto

**Why Skip?**
- Requires external dependencies (Redis, S3)
- Can use mocks but less valuable
- Integration tests more appropriate

---

## 📋 Detailed Action Plan

### Step 1: Core Library Edge Cases (Target: 88%)
**Time: 2-3 hours**

#### `core/context.py` (51 lines)
```python
# Test cases needed:
- Nested context managers
- Context cleanup on errors
- Transaction rollback scenarios
- Concurrent context usage
- Invalid context state transitions
```

#### `storage/manager.py` (23 lines)
```python
# Test cases needed:
- Connection pool exhaustion
- Reconnection after failure
- Multiple storage backends
- Transaction isolation
- Cleanup on shutdown
```

#### `core/config.py` + `core/env.py` (26 lines)
```python
# Test cases needed:
- Invalid configuration values
- Missing required fields
- Type conversion errors
- Circular dependencies in config
- Edge case environment variables
```

---

### Step 2: Web Integrations (Target: 92%)
**Time: 3-4 hours**

#### `integrations/fastapi.py` (59 lines)
```python
# Test cases needed:
- More webhook routes (different sources)
- Authentication/authorization middleware
- Request validation errors
- Background task failures
- Dependency injection edge cases
- Status tracking errors
```

#### `integrations/flask.py` (63 lines)
```python
# Test cases needed:
- More Flask routes
- Blueprint registration errors
- Middleware chain
- Request context edge cases
- Error handlers
- Status tracking
```

#### `dry_run.py` (17 lines)
```python
# Test cases needed:
- Dry-run with errors
- Complex saga graphs
- Missing dependencies
- Invalid configurations
```

---

### Step 3: Polish Existing Files (Target: 95%)
**Time: 2-3 hours**

Focus on files at 85-94% coverage:
- Add edge case tests
- Cover error paths
- Test cleanup/teardown
- Test concurrency scenarios

---

## 📊 Expected Results

### Conservative Estimate (Step 1 + 2)
- **Coverage**: 92-93%
- **Effort**: 5-7 hours
- **Lines Covered**: ~250 of 493 (51%)

### Optimistic Estimate (All 3 Steps)
- **Coverage**: 94-95%
- **Effort**: 7-10 hours
- **Lines Covered**: ~350-400 of 493 (71-81%)

### Perfect (Include CLI + External)
- **Coverage**: 97-98%
- **Effort**: 15-20 hours
- **Lines Covered**: ~450+ of 493 (91%+)
- **Not Recommended**: Diminishing returns

---

## 🎯 RECOMMENDED APPROACH

### Focus on Business Value
**Target: 93-94% coverage (Steps 1 & 2)**

**Prioritize:**
1. ✅ Core library (saga, storage, config)
2. ✅ Web integrations (FastAPI, Flask)
3. ✅ High-value features (idempotency, compliance)

**Defer:**
1. ⏸️ CLI tools (manually tested)
2. ⏸️ External storage (integration tests better)
3. ⏸️ Demo/example code

---

## 📝 Implementation Template

### Create These Test Files:

1. **`tests/unit/core/test_context_advanced.py`**
   - Nested contexts
   - Error handling
   - Concurrent usage

2. **`tests/unit/storage/test_manager_advanced.py`**
   - Connection pooling
   - Multi-backend
   - Error recovery

3. **`tests/unit/integrations/test_fastapi_advanced.py`**
   - More routes
   - Auth/validation
   - Background tasks

4. **`tests/unit/integrations/test_flask_advanced.py`**
   - More routes
   - Middleware
   - Error handlers

5. **`tests/unit/test_config_validation.py`**
   - Config validation
   - Type errors
   - Edge cases

---

## 🚀 Quick Start Commands

```bash
# See what's missing
make coverage MISSING=yes | less

# Focus on specific file
pytest tests/unit/core/test_context.py -v --cov=sagaz/core/context.py --cov-report=term-missing

# Check progress
make coverage | grep "TOTAL"
```

---

## ✅ Success Criteria

### Minimum (93%):
- ✅ All core library > 95%
- ✅ Web integrations > 85%
- ✅ Storage backends > 90%

### Target (95%):
- ✅ All core library > 97%
- ✅ Web integrations > 90%
- ✅ Storage backends > 95%
- ✅ Most CLI > 85%

### Excellence (97%+):
- Requires CLI + external storage
- Significant effort
- Diminishing returns

---

## 💡 Bottom Line

**Current**: 86.6% - Good for production
**Target**: 93-94% - Excellent for production (Recommended)
**Stretch**: 95%+ - Outstanding (if you have time)

**Best ROI**: Focus on Steps 1 & 2 (core + web integrations)
- 5-7 hours effort
- Gets to 92-93%
- Covers all critical code paths

---

## Summary

| Approach | Coverage | Effort | ROI | Recommendation |
|----------|----------|--------|-----|----------------|
| **Current** | 86.6% | - | - | ✅ Good baseline |
| **Step 1+2** | 92-93% | 5-7h | ⭐⭐⭐⭐⭐ | ✅ **RECOMMENDED** |
| **All 3 Steps** | 94-95% | 7-10h | ⭐⭐⭐⭐ | ✅ Great if time allows |
| **Perfect** | 97-98% | 15-20h | ⭐⭐ | ⏸️ Not worth it |

**Verdict: Target 93-94% for best value. 95%+ if you want "perfect" badge.** 🎯
