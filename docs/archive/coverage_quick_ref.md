# 🎯 Quick Reference: Get to 95% Coverage

## TL;DR
**Current**: 86.6% | **Target**: 95% | **Gap**: 493 lines

**Recommended**: Focus on Core + Web = 93-94% in 5-7 hours ⭐

---

## 🎯 Priority Matrix

### Must Do (Core Library)
Files at 76-94% coverage - **93 lines total**

```
core/context.py          51 lines  [████░░░░] 76.7%  → Test nested contexts
storage/manager.py       23 lines  [████████░] 90.9%  → Test pool exhaustion  
postgresql/snapshot.py   17 lines  [████████░] 82.1%  → Test PG edge cases
core/config.py           14 lines  [█████████] 93.7%  → Test invalid config
core/env.py              12 lines  [████████░] 84.7%  → Test .env parsing
core/compliance.py        8 lines  [████████░] 89.8%  → Test validation
```

**Effort**: 2-3 hours | **Gain**: +1.1% → 87.7%

---

### Should Do (Web Integrations)
Files at 46-92% coverage - **139 lines total**

```
integrations/flask.py    63 lines  [████░░░░░] 48.6%  → Test routes/middleware
integrations/fastapi.py  59 lines  [████░░░░░] 46.3%  → Test routes/deps
dry_run.py               17 lines  [█████████] 91.5%  → Test edge cases
```

**Effort**: 3-4 hours | **Gain**: +1.7% → 89.4%

---

### Polish (Get to 95%)
Files at 85-94% - **~150 lines total**

```
Multiple files at 88-94%  → Add edge cases, error paths
```

**Effort**: 2-3 hours | **Gain**: +3-4% → 93-95%

---

### Skip (Low ROI)
```
cli/dry_run.py          219 lines  → Manual testing OK
cli/examples.py          61 lines  → Demo code
redis/snapshot.py       123 lines  → Needs Redis
s3/snapshot.py          177 lines  → Needs S3/moto
```

**Why**: Hard to test, low business value, or needs infrastructure

---

## 📋 Quick Action Plan

### Phase 1: Core (2-3 hrs) → 87.7%
```bash
# Create test files
touch tests/unit/core/test_context_advanced.py
touch tests/unit/storage/test_manager_advanced.py
touch tests/unit/test_config_validation.py

# Test specific areas
pytest tests/unit/core/test_context.py -v --cov=sagaz/core/context.py --cov-report=term-missing
```

### Phase 2: Web (3-4 hrs) → 89-90%
```bash
# Create/extend test files
touch tests/unit/integrations/test_fastapi_advanced.py
touch tests/unit/integrations/test_flask_advanced.py

# Test with coverage
pytest tests/unit/integrations/ -v --cov=sagaz/integrations --cov-report=term-missing
```

### Phase 3: Polish (2-3 hrs) → 93-95%
```bash
# Find files at 85-94%
make coverage MISSING=yes | grep -E "(8[5-9]|9[0-4])%"

# Add edge case tests to each
```

---

## 🎯 Target by Priority

| Priority | Files | Lines | Effort | Result |
|----------|-------|-------|--------|--------|
| **High** | 6 | 93 | 2-3h | 87.7% |
| **Medium** | 3 | 139 | 3-4h | 89-90% |
| **Polish** | ~10 | 150 | 2-3h | 93-95% |
| **Total** | ~19 | 382 | 7-10h | **93-95%** ✅ |

---

## 🚀 Commands to Track Progress

```bash
# Current coverage
make coverage | tail -1

# See missing lines
make coverage MISSING=yes | less

# Test specific file
pytest tests/unit/core/ -v --cov=sagaz/core --cov-report=term-missing

# Quick check
python -m pytest --cov=sagaz --cov-report=term | grep TOTAL
```

---

## ✅ Done When

### Minimum Success (93%)
- [ ] All core files > 95%
- [ ] Web integrations > 85%
- [ ] Storage backends > 90%

### Target Success (95%)
- [ ] All core files > 97%
- [ ] Web integrations > 90%
- [ ] Most storage > 95%

---

## 💡 Pro Tips

1. **Focus on high-impact files first** (core, storage)
2. **Use `--cov-report=term-missing`** to see what lines need tests
3. **Test error paths** - they're usually the missing coverage
4. **Don't test CLI interactively** - manual testing is fine
5. **Mock external dependencies** (don't need real Redis/S3)

---

## 📊 ROI Analysis

| Approach | Coverage | Effort | Value |
|----------|----------|--------|-------|
| Current | 86.6% | 0h | ✅ Good |
| Core Only | 87.7% | 2-3h | ✅ Better |
| Core+Web | 89-90% | 5-7h | ⭐ Great |
| All 3 | 93-95% | 7-10h | ⭐⭐ Excellent |
| Perfect | 97-98% | 15-20h | 🤷 Overkill |

**Recommendation**: Core+Web (89-90%) or All 3 (93-95%)

---

## Bottom Line

🎯 **To get 95%**: Cover ~380-400 lines in 7-10 hours
✅ **Realistic target**: 93-94% in 5-8 hours
⚡ **Quick win**: 89-90% in 5-7 hours

**Start with Core (Phase 1) → See results → Decide if Phase 2/3 worth it**
