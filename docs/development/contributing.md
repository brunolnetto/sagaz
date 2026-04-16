# Contributing Guide

How to contribute to the Sagaz saga pattern library.

---

## Branching & Pull Requests (GitFlow Workflow)

### ⚠️ Direct Pushes to `main` and `develop` Are Blocked

The repository enforces GitFlow discipline via automated workflow checks:
- Direct pushes to `main` or `develop` will **fail** and be rejected
- All changes must go through the pull request workflow
- Bot pushes (Dependabot, Renovate) are automatically allowed
- Merge commits from properly configured workflows bypass protection

### Required Workflow

1. **Create a feature branch** from `develop`:
   ```bash
   git checkout -b feature/my-feature develop
   # or: fix/bug-name, docs/guide-name, ci/workflow-update
   ```

2. **Develop and commit** (see Commit Messages section below):
   ```bash
   git add .
   git commit -m "feat(scope): description"
   ```

3. **Push to your branch** (direct pushes to feature branches allowed):
   ```bash
   git push -u origin feature/my-feature
   ```

4. **Create a pull request** on GitHub:
   - Target: `develop` (for features) or `main` (for develop→main release PR)
   - Title must follow conventional commit format
   - Description must include motivation, impact, and changes
<<<<<<< HEAD
   - Link related issues using `Closes #<n>` or `Relates to #<n>`
=======
   - **Link related issues** (see [Issue-PR Policy](./ISSUE-PR-POLICY.md)):
     - **Required for**: feature/*, fix/*, refactor/* (major), perf/*, revert/* PRs
     - **Use**: `Closes #<n>`, `Fixes #<n>`, `Resolves #<n>` to auto-close on merge
     - **Optional refs**: `Relates to #<n>` for partial/related work (doesn't auto-close)
     - **Exempt types**: chore/*, ci/*, build/*, test/*, docs/* (no issue reference needed)
>>>>>>> develop

5. **Address PR feedback** and ensure all checks pass:
   - Commitlint validation
   - Branch flow validation
   - CI/CD pipeline tests
   - Code review approval (if required)

6. **Merge via GitHub UI** (creates audit trail):
   - Use "Create a merge commit" or "Squash and merge"
   - Avoid "Rebase and merge" unless specifically needed

### What If You Accidentally Push Directly to a Protected Branch?

You'll see this error message:

```
❌ Direct pushes to 'main' are not allowed.

Please use the GitFlow workflow:
  1. Create a feature branch: git checkout -b feature/your-feature
  2. Push your branch: git push -u origin feature/your-feature
  3. Create a Pull Request on GitHub
  4. Get approval and merge via GitHub UI

This ensures all commits follow conventional format and pass CI/CD checks.
```

**To fix it**: Create a PR from your current branch with the changes, get approval, and merge.

---

## Commit Messages

Commits must follow [Conventional Commits](https://www.conventionalcommits.org/) enforced by commitlint.

### Format

```
<type>(<scope>): <subject>
```

### Rules

| Rule | Details |
|------|---------|
| `type` | Must be one of: `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `chore`, `revert` |
| `scope` | Must be present and non-empty; see approved scopes below |
| `subject` | No sentence case, start case, or pascal case; don't end with period |
| `footer` | Use `Closes #<n>` to auto-close related issues on merge |

### Approved Scopes

Choose from: `saga`, `dag`, `outbox`, `storage`, `strategies`, `monitoring`, `cli`, `execution`, `triggers`, `visualization`, `integrations`, `sagaz`, `docs`, `ci`, `deps`, `tests`

### Examples

✅ Valid:
```
feat(saga): add compensation timeout handling
fix(storage): correct postgres connection pool leak
test(dag): add unit tests for parallel step ordering
docs(contributing): document branching policy
ci(ci): add direct push protection

Closes #131
```

❌ Invalid:
```
Added new feature (no type/scope)
feat: something (no scope)
feat(mysaga): Add feature. (sentence case, ends with period)
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

## Release Process (main Branch)

The `main` branch represents production-ready code:

1. When ready to release, create a PR from `develop` → `main`
2. Title: `ci(ci): release vX.Y.Z` or similar
3. Wait for all checks to pass
4. Merge via GitHub UI
5. Tag the merge commit with version: `v1.2.3`

Only `develop` pushes to `main` — never feature branches directly.

---

## See Also

- [Development Policy](../../.github/skills/development-policy/SKILL.md) — enforced policies and branch protection
- [Workflow Improvements](workflow-improvements.md) — potential future enhancements
- [Testing Guide](testing.md) — running tests and writing new ones
- [Makefile Reference](makefile.md) — all available make targets
- [Changelog](changelog.md) — project history

---

## Questions?

If you encounter GitFlow issues or need clarification, please:
1. Check the [Development Policy](../../.github/skills/development-policy/SKILL.md)
2. Review the automated messages from failing jobs
3. Create an issue with label `enhancement` if something could be improved
