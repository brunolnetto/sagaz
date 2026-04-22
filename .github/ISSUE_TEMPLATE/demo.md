---
name: Propose Demonstration
about: Suggest a new demo module for documentation & roadmap
labels: demo:roadmap
title: "demo: [domain] [pattern]"
---

## What capability does this demo showcase?

<!-- Describe briefly what feature/pattern this demo will illustrate. -->
<!-- Example: "How to use Redis with saga pattern for high-throughput scenarios" -->

## Related Feature

<!-- Link to the feature issue this demo documents. -->
<!-- Example: Closes #123 (after feature is implemented) -->

Closes #[feature-issue]

## Demo Location

```
sagaz/demonstrations/[domain]/[pattern]/
└── main.py

tests/unit/demonstrations/[domain]/
└── test_[pattern].py
```

- **Domain:** `[e.g., observability, reliability, integrations]`
- **Pattern:** `[e.g., distributed_tracing, dlq_handling]`

## Success Criteria

- [ ] Demo module `main.py` implements `async def _run() -> None`
- [ ] Three-phase structure: Setup → Execute → Verify
- [ ] All external services mocked (no Docker dependencies)
- [ ] Test file achieves 100% code coverage
- [ ] All tests pass without Docker in unit test suite
- [ ] Runs via `sagaz demo [domain] [pattern]`
- [ ] Documented in `docs/demonstrations/[domain].md`
- [ ] Registered in `sagaz/demonstrations/__init__.py`
- [ ] Demo completes in <500ms
- [ ] Includes realistic usage patterns (not toy examples)

## Acceptance Criteria

Before marking as ready for merge:

- [ ] Code review approval
- [ ] All CI checks pass (lint, type, coverage)
- [ ] Coverage report shows 100% on demo module
- [ ] Feature issue links back to this demo
- [ ] Release notes updated with demo reference

## Notes

<!-- Any additional context or implementation hints. -->
