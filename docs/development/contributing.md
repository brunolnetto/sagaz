# Contributing Guide

How to contribute to the Sagaz saga pattern library.

---

## Branching & Pull Requests

- **Never push directly to `main`.** All changes must go through a pull request.
- Create a dedicated feature branch for every piece of work:
  ```bash
  git checkout -b feat/my-feature
  ```
- Open a PR against `main` and request a review before merging.

---

## Commit Messages

Commits must follow [Conventional Commits](https://www.conventionalcommits.org/) enforced by commitlint.

### Format

```
<type>(<scope>): <subject>
```

### Rules

| Rule | Values |
|------|--------|
| `type` | `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `chore`, `revert` |
| `scope` | Must be present and non-empty |
| `subject` | No sentence-case, start-case, or pascal-case |
| `subject` | Must not end with a full stop |

### Examples

```
feat(saga): add compensation timeout handling
fix(storage): correct postgres connection pool leak
test(dag): add unit tests for parallel step ordering
docs(contributing): document branching policy
```

---

## Test-Driven Development (TDD)

All new features must follow the **red-green-refactor** cycle:

1. **Red** — Write a failing test that describes the desired behaviour.
2. **Green** — Write the minimal code to make the test pass.
3. **Refactor** — Clean up without changing behaviour; keep all tests green.

---

## Test Organisation

Keep tests strictly separated by category:

| Category | Location | Purpose |
|----------|----------|---------|
| Unit | `tests/unit/` | Fast, isolated, no I/O |
| Integration | `tests/integration/` | Real dependencies via containers |
| End-to-End | `tests/e2e/` | Full workflow across services |
| Performance | `tests/performance/` | Benchmarks and throughput assertions |

```bash
# Unit tests only (fast, no dependencies)
pytest tests/unit/

# Integration tests (requires Docker)
pytest tests/integration/

# Performance benchmarks
pytest tests/performance/
```

Use **lightweight testcontainers** (e.g. `testcontainers-python`) for integration and e2e tests instead of assuming an external environment.

---

## Coverage Policy

- Coverage must not drop below **95%** relative to `main` for any PR that touches production code.
- Check before opening a PR:
  ```bash
  make coverage
  ```
- The CI pipeline enforces this threshold automatically.

---

## See Also

- [Testing Guide](testing.md) — running tests and writing new ones
- [Makefile Reference](makefile.md) — all available make targets
- [Changelog](changelog.md) — project history
