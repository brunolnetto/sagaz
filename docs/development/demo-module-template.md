# Demo Module Template & Governance

When adding a new demonstration to the "demos dept," follow this pattern. Demos are **look-ahead documentation**: they show how upcoming features work and serve as the official examples when released.

## Prerequisites

- Feature must be **implemented** in `sagaz/` (not just planned)
- Must be **runnable** without Docker (use mocks)
- Must achieve **100% test coverage**

## File Structure

```
sagaz/demonstrations/
├── [domain]/                          # e.g., observability, reliability
│   └── [pattern]/                     # e.g., distributed_tracing
│       ├── __init__.py                # Empty or re-exports
│       └── main.py                    # Demo implementation
│
tests/unit/demonstrations/
├── [domain]/                          # Same domain
│   └── test_[pattern].py              # 100% coverage tests
```

## Implementation Checklist

Before submitting a demo PR, verify:

### Demo Module (`sagaz/demonstrations/[domain]/[pattern]/main.py`)

- [ ] **Async function signature:** `async def _run() -> None`
- [ ] **Three-phase structure:**
  - **Phase 1 (Setup):** Create fixtures, mocks, saga instances
  - **Phase 2 (Execute):** Run the feature demo logic
  - **Phase 3 (Verify):** Assert results, print success
- [ ] **Logging:** Use structured logging (`logger.info()`)
- [ ] **Duration:** Completes in <500ms (no long sleeps)
- [ ] **Realistic:** Simulates real usage patterns, not toy examples
- [ ] **No Docker:** All external services mocked (see examples below)

### Test Module (`tests/unit/demonstrations/[domain]/test_[pattern].py`)

- [ ] **Coverage:** 100% of demo lines executed
- [ ] **Test structure:** One test per logical path through `_run()`
- [ ] **Mocking:** Use `unittest.mock.patch()` for imports
- [ ] **No integration markers:** Only `@pytest.mark.asyncio`, no `@pytest.mark.integration`
- [ ] **Naming:** `test_[pattern]_run_function` + scenario tests

### Documentation

- [ ] **Docstring:** Clear one-liner in `_run()` describing what is demonstrated
- [ ] **Comments:** Explain *why* each phase is needed, not *what* code does
- [ ] **Link:** Add entry to `docs/demonstrations/[domain].md` index

### CI/CD

- [ ] **Lint:** `ruff check` passes
- [ ] **Types:** `mypy sagaz/demonstrations/` passes
- [ ] **Tests:** `pytest tests/unit/demonstrations/[domain]/` passes
- [ ] **Coverage:** Report shows 100%

## Example: Distributed Tracing Demo

### Demo Module

```python
# sagaz/demonstrations/observability/distributed_tracing/main.py
"""Demonstrate distributed tracing with OpenTelemetry."""

import asyncio
import logging
from uuid import uuid4
from unittest.mock import AsyncMock, patch, MagicMock

from sagaz.core.saga import Saga, SagaContext

logger = logging.getLogger(__name__)

async def _run() -> None:
    """Show how distributed tracing captures saga execution flow."""
    
    # Phase 1: Setup
    # Mock OTEL tracer + collector
    mock_tracer = MagicMock()
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(
        return_value=False
    )
    
    saga_id = f"trace-demo-{uuid4().hex[:8]}"
    
    # Phase 2: Execute
    # Build a simple saga that will be traced
    class TracedSaga(Saga):
        async def build(self):
            await self.add_step(
                name="step1",
                action=self._do_step1,
                timeout=5.0
            )
        
        async def _do_step1(self, ctx: SagaContext):
            logger.info(f"Executing step1 in saga {ctx.saga_id}")
            # Simulate traced operation
            with mock_tracer.start_as_current_span("step1") as span:
                await asyncio.sleep(0.01)
                span.set_attribute("saga.id", ctx.saga_id)
            return {"result": "success"}
    
    saga = TracedSaga(saga_id=saga_id)
    await saga.build()
    result = await saga.execute()
    
    # Phase 3: Verify
    # Check that tracing happened
    assert result.status.value == "COMPLETED"
    assert mock_tracer.start_as_current_span.called
    logger.info(f"✅ Distributed tracing demo: {saga_id}")
    logger.info(f"   Spans created: {mock_tracer.start_as_current_span.call_count}")
```

### Test Module

```python
# tests/unit/demonstrations/observability/test_distributed_tracing.py
"""Test distributed tracing demo module."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from sagaz.demonstrations.observability.distributed_tracing.main import _run


@pytest.mark.asyncio
async def test_distributed_tracing_run_function():
    """Test that tracing demo executes and creates spans."""
    
    with patch('sagaz.demonstrations.observability.distributed_tracing.main.mock_tracer') as mock:
        await _run()
        # Verify tracer was used
        assert mock.start_as_current_span.called


@pytest.mark.asyncio
async def test_distributed_tracing_with_exception_path():
    """Test tracing behavior when step fails."""
    
    # Test the exception handling path if present
    with patch('sagaz.demonstrations.observability.distributed_tracing.main.Saga') as MockSaga:
        mock_saga = AsyncMock()
        mock_saga.execute.return_value = MagicMock(status=MagicMock(value="FAILED"))
        MockSaga.return_value = mock_saga
        
        await _run()
        assert mock_saga.execute.called
```

## Running Your Demo

Once implemented and tested, users run it via:

```bash
# List available demos
sagaz demo --list

# Run specific demo
sagaz demo observability distributed_tracing

# List by domain
sagaz demo --domain observability
```

## Registration

Add your demo to the registry in `sagaz/demonstrations/__init__.py`:

```python
DEMONSTRATIONS = {
    "observability": {
        "distributed_tracing": {
            "module": "sagaz.demonstrations.observability.distributed_tracing.main",
            "description": "Show distributed tracing with OpenTelemetry",
            "added_version": "0.1.0",
        }
    }
}
```

## PR Submission

When submitting a demo PR:

1. **Title:** `feat(demos): add [domain] [pattern] demonstration`
2. **Body:** Link to feature issue: `Related #[feature-issue]`
3. **Labels:** Add `demo:roadmap` + `demo:[domain]`
4. **Milestone:** Assign to next release (e.g., v0.1.0)

Example:

```markdown
## Description

Adds demonstration for the new distributed tracing integration.

## Demo Details

- **Domain:** observability
- **Pattern:** distributed_tracing
- **Coverage:** 100% (2 test functions)
- **Runtime:** <100ms

## Related

- Closes #[feature-issue]
- Feature PR: #[feature-pr]
```

## FAQ

**Q: Can I add a demo for an unreleased feature?**  
A: Yes! Demo should be on a feature branch alongside the feature implementation. When the feature merges to `develop`, the demo merges too.

**Q: What if the feature is complex with many paths?**  
A: Add multiple demo functions for different scenarios:
  - Happy path
  - Common failure scenario
  - Edge case

**Q: Should the demo module have all the same error handling as production code?**  
A: No—keep demos simple and readable. Error handling shown should be typical usage patterns, not exhaustive.

**Q: How do I update a demo if the feature changes?**  
A: Same as updating any code:
  1. Update demo module
  2. Update tests
  3. Run coverage check
  4. Submit PR with label `demo:maintenance`

## Governance

- **Review:** All demos reviewed for clarity + coverage by project maintainers
- **Acceptance:** 100% coverage + all tests passing in CI
- **Deprecation:** If underlying feature removed, demo marked `# pragma: no cover` and scheduled for removal in next major version
- **Quarterly Audit:** Demo backlog reviewed every quarter to align with roadmap

---

**Questions?** See [Quality Backlog](quality-backlog.md) for tracking demo improvements.
