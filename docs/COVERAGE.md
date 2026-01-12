# 📊 Test Coverage Documentation

## Quick Links

- **[Coverage Quick Reference](./coverage_quick_ref.md)** - TL;DR version, commands, priorities
- **[Coverage Roadmap](./coverage_roadmap.md)** - Detailed action plan to 95%+

---

## Current Status

**Coverage**: 86.6% (7448/8359 lines) ✅

### Breakdown by Category

| Category | Coverage | Status |
|----------|----------|--------|
| **Core Library** | 90%+ | ✅ Excellent |
| Saga orchestration | 98%+ | ✅ |
| State machine | 100% | ✅ |
| Outbox pattern | 99%+ | ✅ |
| Storage (memory, postgres, sqlite) | 95%+ | ✅ |
| Monitoring | 97%+ | ✅ |
| **Supporting** | 75-90% | ✅ Good |
| Exceptions | 95% | ✅ |
| Configuration & Env | 92% | ✅ |
| FastAPI integration | 75% | ✅ |
| Flask integration | 75% | ✅ |
| **Optional** | <75% | 🔵 OK |
| CLI tools | 40-70% | 🔵 Manual testing |
| Redis snapshot | 21% | 🔵 Needs Redis |
| S3 snapshot | 16% | 🔵 Needs S3 |

---

## Commands

```bash
# Run tests
make test                  # Fast parallel tests
make test TYPE=all         # All tests including integration

# Coverage
make coverage              # Terminal report
make coverage MISSING=yes  # Show missing lines ⭐
make coverage FORMAT=html  # HTML report

# Quality checks
make check                 # Lint + complexity + test
make complexity            # Cyclomatic complexity
```

---

## To Get 95%+ Coverage

**See**: [Coverage Roadmap](./coverage_roadmap.md)

**TL;DR**:
1. **Phase 1** (2-3h): Core library → 87.7%
2. **Phase 2** (3-4h): Web integrations → 89-90%
3. **Phase 3** (2-3h): Polish → 93-95%

**Total**: 7-10 hours to reach 93-95%

**Recommended**: Focus on Phases 1+2 for best ROI

---

## What's Missing?

To see exactly what lines need tests:

```bash
make coverage MISSING=yes | less
```

For specific files:

```bash
pytest tests/unit/core/ -v --cov=sagaz/core --cov-report=term-missing
```

---

## Files Needing Tests

### High Priority (Core - 93 lines)
- `core/context.py` (51 lines) - Context manager edge cases
- `storage/manager.py` (23 lines) - Connection pool exhaustion
- `postgresql/snapshot.py` (17 lines) - PostgreSQL edge cases
- `core/config.py` (14 lines) - Invalid config
- `core/env.py` (12 lines) - Environment parsing
- `core/compliance.py` (8 lines) - Validation

### Medium Priority (Web - 139 lines)
- `integrations/flask.py` (63 lines) - Routes, middleware
- `integrations/fastapi.py` (59 lines) - Routes, dependencies
- `dry_run.py` (17 lines) - Edge cases

### Low Priority (Skip)
- CLI tools (519 lines) - Manual testing OK
- External storage (300 lines) - Needs infrastructure

---

## Test Quality Standards

### Current Standards
- ✅ Unit tests for all core functionality
- ✅ Integration tests for storage backends
- ✅ Mocking for external dependencies
- ✅ Error path testing
- ✅ Edge case coverage

### Coverage Targets
- **Core library**: 95%+ (Currently: 90%+)
- **Web integrations**: 85%+ (Currently: 75%+)
- **Storage backends**: 90%+ (Currently: 95%+)
- **CLI tools**: Manual testing (Currently: 40-70%)

---

## Adding New Tests

### Test File Structure
```
tests/
├── unit/               # Unit tests (fast, isolated)
│   ├── core/          # Core functionality
│   ├── storage/       # Storage backends
│   └── integrations/  # Web framework integrations
├── integration/        # Integration tests (slower, real dependencies)
└── performance/        # Performance benchmarks
```

### Test Naming Convention
```python
class TestFeatureName:
    def test_happy_path(self):
        """Test normal operation"""
        
    def test_edge_case_description(self):
        """Test specific edge case"""
        
    def test_error_handling(self):
        """Test error scenarios"""
```

### Running Specific Tests
```bash
# Single file
pytest tests/unit/test_exceptions.py -v

# Single test
pytest tests/unit/test_exceptions.py::TestExceptionConstructors::test_saga_error_basic -v

# With coverage
pytest tests/unit/test_exceptions.py -v --cov=sagaz/core/exceptions --cov-report=term-missing
```

---

## CI/CD Integration

Coverage is checked in CI/CD:

```bash
make check-ci  # Runs all CI checks including coverage
```

**Minimum Coverage**: 85% (current: 86.6%)
**Target Coverage**: 90%+ (recommended: 93-95%)

---

## Related Documents

- [Testing Guide](../TESTING.md) - How to write tests
- [Contributing](../CONTRIBUTING.md) - Contribution guidelines
- [Development Setup](../README.md#development) - Getting started

---

## Questions?

- Check [Coverage Quick Reference](./coverage_quick_ref.md) for commands
- See [Coverage Roadmap](./coverage_roadmap.md) for detailed plan
- Run `make help` to see all available commands

---

**Last Updated**: 2026-01-12
**Current Coverage**: 86.6%
**Target Coverage**: 93-95%
