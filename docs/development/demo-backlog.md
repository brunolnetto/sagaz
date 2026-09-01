# Demo Module Backlog

**Last Updated:** April 20, 2026 (PR #239)  
**Review Schedule:** Quarterly (Jan/Apr/Jul/Oct)  
**Status:** Active demos live in `sagaz/demonstrations/`; planned demos tracked here.

## Quick Stats

| Metric | Value |
|--------|-------|
| **Active Demos** | 6 modules |
| **Coverage** | 100% (all tested) |
| **Next Review** | Q2 2026 (July) |

---

## Active Demonstrations (Released/Ready)

### 1. Core Patterns

**Domain:** `core_patterns`

| Demo | Status | Coverage | Notes |
|------|--------|----------|-------|
| basic_saga | ✅ Ready | 100% | Fundamental saga execution |
| parallel_steps | ✅ Ready | 100% | DAG with concurrent tasks |
| compensation | ✅ Ready | 100% | Rollback on failure |

### 2. Reliability & Recovery

**Domain:** `reliability_recovery`

| Demo | Status | Coverage | Notes |
|------|--------|----------|-------|
| saga_replay | ✅ Ready | 100% | Recover from checkpoints |
| sqlite_storage | ✅ Ready | 100% | Lightweight persistence |
| postgres_storage | ✅ Ready | 100% | Production storage backend |

### 3. Orchestration

**Domain:** `orchestration_config`

| Demo | Status | Coverage | Notes |
|------|--------|----------|-------|
| storage_backends | ✅ Ready | 100% | In-Memory, Redis, PostgreSQL |
| event_triggers | ✅ Ready | 100% | Saga activation patterns |

### 4. Framework Integrations

**Domain:** `framework_integrations`

| Demo | Status | Coverage | Notes |
|------|--------|----------|-------|
| fastapi_integration | ✅ Ready | 96.8% | FastAPI webhook patterns (pragma: no cover intentional) |

---

## Planned Demonstrations (Backlog)

### High Priority (Q2 2026 - Next Release)

These are features being built now; demos planned for release alongside.

| Feature | Domain | Pattern | Status | ETA |
|---------|--------|---------|--------|-----|
| Distributed Tracing | observability | otel_tracing | 🎯 Planned | Jun 2026 |
| Dead-Letter Queues | reliability | dlq_handling | 🎯 Planned | Jun 2026 |
| Event Sourcing | storage | event_sourcing | 🎯 Planned | Jul 2026 |

### Medium Priority (Q3 2026)

Demos for features on the roadmap.

| Feature | Domain | Pattern | Status | Notes |
|---------|--------|---------|--------|-------|
| Chaos Engineering | reliability | chaos_patterns | ⏳ Design | Learning impact patterns |
| Performance Tuning | performance | optimization_guide | ⏳ Design | Throughput / latency tradeoffs |
| Multi-Tenant Sagas | integrations | multi_tenancy | 💭 Idea | Isolation strategies |

### Low Priority (Q4 2026+)

Nice-to-have demonstrations; not blocking any releases.

| Feature | Domain | Pattern | Status |
|---------|--------|---------|--------|
| GraphQL Integration | integrations | graphql_mutations | 💭 Idea |
| Temporal Integration | integrations | temporal_integration | 💭 Idea |

---

## Governance Rules

### When to Create a Demo

✅ **DO** create a demo if:
- Feature is **fully implemented** in `sagaz/`
- Feature is **generic/reusable** (not domain-specific business logic)
- Feature **introduces new patterns** (worth documenting)
- Feature is part of **next release** or **roadmap**

❌ **DON'T** create a demo if:
- Feature is still in design phase
- Feature is internal implementation detail
- Demo would require Docker containers in unit tests
- Feature is already well-documented in API docs

### Coverage Requirement

**All demos must achieve 100% test coverage** with mocked dependencies:

```python
# ✅ GOOD: Mocked dependencies
@patch('sagaz.demonstrations.observability.otel_tracing.tracer')
async def test_otel_tracing_creates_spans(mock_tracer):
    await _run()
    assert mock_tracer.start_as_current_span.called

# ❌ BAD: Requires Docker/real service
@pytest.mark.integration
async def test_otel_sends_to_collector():
    # This runs Docker container - not allowed in demo tests!
```

### Lifecycle

| Phase | Owner | Duration | Action |
|-------|-------|----------|--------|
| **Design** | Feature PM | ~1 week | Create issue with `demo:roadmap` label |
| **Implementation** | Engineer | ~2 weeks | Build feature + demo module in parallel |
| **Testing** | Engineer | ~1 week | Achieve 100% coverage, all tests pass |
| **Review** | Maintainer | ~3 days | Code review, demo clarity check |
| **Release** | Release Lead | ~1 day | Package demo in release notes + docs |

---

## How to Add a Demo

1. **Create issue** using [demo.md template](.github/ISSUE_TEMPLATE/demo.md)
   ```bash
   gh issue create --template=demo.md \
     --title "demo: [domain] [pattern]" \
     --label "demo:roadmap"
   ```

2. **Implement** following [demo-module-template.md](docs/development/demo-module-template.md)
   ```
   sagaz/demonstrations/[domain]/[pattern]/main.py    # Demo impl
   tests/unit/demonstrations/[domain]/test_[pattern].py  # Tests (100% coverage)
   ```

3. **Register** in `sagaz/demonstrations/__init__.py`
   ```python
   DEMONSTRATIONS = {
       "[domain]": {
           "[pattern]": {
               "module": "sagaz.demonstrations.[domain].[pattern].main",
               "description": "...",
               "added_version": "0.1.0",
           }
       }
   }
   ```

4. **Test & verify**
   ```bash
   uv run pytest tests/unit/demonstrations/[domain]/ \
     --cov=sagaz.demonstrations.[domain].[pattern] --cov-report=term-missing
   # Must show 100%
   ```

5. **Submit PR**
   - Label: `demo:roadmap` + `demo:[domain]`
   - Milestone: Next release
   - Description: Link to feature issue (`Closes #[n]`)

---

## Automation

### Inventory Generation

Run monthly to update status:

```bash
python scripts/inventory_demos.py           # Markdown report
python scripts/inventory_demos.py --json    # JSON for CI
python scripts/inventory_demos.py --table   # Table format
```

### CI/CD Checks

Every demo PR validates:

```bash
# Coverage check
pytest tests/unit/demonstrations/ \
  --cov=sagaz.demonstrations \
  --cov-report=term-missing

# Type check
mypy sagaz/demonstrations/

# Lint
ruff check sagaz/demonstrations/
```

---

## Related Documents

- **Template:** [docs/development/demo-module-template.md](docs/development/demo-module-template.md)
- **Issue Template:** [.github/ISSUE_TEMPLATE/demo.md](.github/ISSUE_TEMPLATE/demo.md)
- **Inventory Script:** [scripts/inventory_demos.py](scripts/inventory_demos.py)
- **Feature Roadmap:** [docs/ROADMAP.md](docs/ROADMAP.md)

---

## Review History

| Date | Reviewer | Changes | Notes |
|------|----------|---------|-------|
| 2026-04-20 | Agent | Created backlog (PR #239) | Established governance for demo dept |
| (Next review) | - | - | Expected Jul 2026 |

---

**Question?** Ask in [GitHub Discussions](https://github.com/brunolnetto/sagaz/discussions) with label `demos`.
