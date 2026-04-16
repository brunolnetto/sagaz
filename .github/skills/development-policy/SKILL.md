---
name: development-policy
description: "Use when applying or reminding about PR-based feature work, test regression thresholds, commitlint rules, TDD workflow, and GitFlow enforcement."
---

# Development Policy

## Core Principles

- **No direct pushes to `main` or `develop`** — All changes must go through PR workflow (enforced by `prevent-direct-push` job)
- Any new feature must be assigned to a PR; do not publish directly to `main`
- New work should be implemented on a dedicated feature branch and reviewed via PR before merging
- GitFlow discipline is not optional — the CI/CD pipeline enforces it via automated checks

## Protected Branches

- **`main`**: Production-ready code. Only accepts merges from `develop` branch PRs.
- **`develop`**: Integration branch. Only accepts merges from feature/fix/docs branches via PR.
- **Feature/fix/docs branches**: Can accept direct pushes from developers (no protection)

## GitFlow Workflow (Required)

1. **Create feature branch** from `develop`:
   ```bash
   git checkout -b feature/your-feature develop
   ```

2. **Develop and commit** using conventional format (see Commit Rules below)

3. **Push to feature branch**:
   ```bash
   git push -u origin feature/your-feature
   ```

4. **Create Pull Request** to `develop`:
   - Title must follow conventional commit format
   - Description must include motivation and impact
   - Must reference related issue(s) using `Closes #<n>` or `Relates to #<n>`

5. **Get PR approval** and ensure all checks pass:
   - Commitlint validation
   - Branch flow validation
   - CI/CD pipeline tests
   - Code review (if required)

6. **Merge to `develop`** via GitHub UI (enables audit trail)

7. **Release to `main`** via PR from `develop` when ready:
   - Create PR: `develop` → `main`
   - Wait for promotion checks
   - Merge via GitHub UI

## What Happens If You Push Directly to `main`/`develop`?

The `prevent-direct-push` job will **automatically fail** and display this message:

```
❌ Direct pushes to 'main' are not allowed.

Please use the GitFlow workflow:
  1. Create a feature branch: git checkout -b feature/your-feature
  2. Push your branch: git push -u origin feature/your-feature
  3. Create a Pull Request on GitHub
  4. Get approval and merge via GitHub UI

This ensures all commits follow conventional format and pass CI/CD checks.
```

**Exception**: Bot pushes (Dependabot, Renovate, GitHub Actions) and merge commits are automatically allowed.

## Commit Rules (Enforced by Commitlint)

Commits must follow conventional commit style:

- **Type**: `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `chore`, or `revert`
- **Scope**: Must be non-empty and in approved list (see below)
- **Subject**: 
  - Must not use sentence case, start case, or pascal case
  - Must not end with a full stop
  - Should be concise and descriptive

### Approved Scopes

`saga`, `dag`, `outbox`, `storage`, `strategies`, `monitoring`, `cli`, `execution`, `triggers`, `visualization`, `integrations`, `sagaz`, `docs`, `ci`, `deps`, `tests`

### Examples

✅ Valid:
- `feat(saga): add replay capability for saga execution`
- `fix(storage): resolve connection pool leak on disconnect`
- `docs(ci): update GitFlow workflow documentation`
- `ci(tests): add performance regression detection`

❌ Invalid:
- `Added new feature` (missing type and scope)
- `feat: something` (missing scope)
- `feat(my-scope): Something` (invalid scope, sentence case)
- `feat(saga): Add feature.` (sentence case, ends with period)

## Testing & Quality Gates

- Regression-sensitive features must preserve coverage at or above `95%` relative to `main`
- Follow TDD with a red-green-refactor cycle: write failing tests first, then implement code to pass them
- Keep unit, integration, end-to-end, and performance tests clearly separated
- Use lightweight testcontainers or ephemeral container fixtures when available

## PR Validation Checklist

GitFlow-compliance workflow validates:

- ✅ **PR Title Format**: Must follow conventional commit format
- ✅ **PR Description**: Must include motivation, impact, and changes sections
- ✅ **Issue Reference**: PR body must contain issue reference (conditional by PR type)
  - **Required for**: `feature/*`, `fix/*`, `refactor/*` (major), `perf/*`, `revert/*`
  - **Optional for**: Other types (via `Relates to #<n>` or `Ref #<n>`)
  - **Exempt**: `test/*`, `ci/*`, `build/*`, `chore/*`, `docs/*`
  - Patterns accepted: `Closes #<n>`, `Fixes #<n>`, `Resolves #<n>`, `Relates to #<n>`, `Ref #<n>`
- ✅ **Branch Flow**: Ensures correct source/target branches per GitFlow rules
- ✅ **Commit Lint**: All commits must follow conventional format
- ✅ **CI/CD Checks**: All tests and linters must pass

## Issue References in PRs

### When to Create an Issue
✅ **Create for**: Bug reports, feature requests, technical debt, ADRs, design discussions
❌ **Don't create for**: Dependency updates, CI changes, chore work, trivial fixes

### How to Reference Issues
- **`Closes #<n>` / `Fixes #<n>` / `Resolves #<n>`**: Use when PR **fully resolves** the issue
  - GitHub automatically closes the issue on merge
  - Guarantees issue is complete (no follow-up work)
- **`Relates to #<n>` / `Ref #<n>`**: Use when PR is **related to but doesn't fully resolve** the issue
  - GitHub does NOT auto-close
  - Use for: partial work, follow-up phases, refactoring related to feature
- **No reference**: Allowed for explicitly exempt PR types (chore, ci, build, test, docs)

See [Issue-PR Policy](../../docs/development/ISSUE-PR-POLICY.md) for complete guidelines and examples.

## Branch Naming

Branches must follow `<type>/<topic>` where type is one of:
`feature`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`

Examples: `feature/saga-replay`, `docs/refactor-dev-guides`, `fix/storage-pool-leak`

## Related Documentation

- [Conventional Commits](https://www.conventionalcommits.org/) - Message format specification
- [GitFlow Workflow](https://www.atlassian.com/git/tutorials/comparing-workflows/gitflow-workflow) - Branching model
- [Issue-PR Policy](../../docs/development/ISSUE-PR-POLICY.md) - When to create issues and how to reference them
- Workflow config: `.github/workflows/gitflow-compliance.yml` - Direct push protection and PR validation
- Commit config: `commitlint.config.cjs` - Commit message validation

## Workflow Enforcement Checklist

When creating a PR, the automated workflow verifies:

- ✅ **Event type filtering**: Jobs only run on correct event types (push or pull_request)
- ✅ **Bot exclusion**: Bots (Dependabot, Renovate) bypass certain checks
- ✅ **Protected branch detection**: main/develop require PR workflow  
- ✅ **Merge commit allowance**: Auto-merges bypass direct-push protection
- ✅ **Conventional commit validation**: All commits must follow format rules
- ✅ **Issue tracking**: Feature/fix PRs must reference related issues; exempt types can be issue-free

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Direct pushes to 'main' not allowed" | Use `git checkout -b feature/name develop` then PR workflow |
| Commitlint failing on merge commit | Merge commits are auto-ignored; check regular commits |
| PR job not running | Verify head branch doesn't start with `dependabot/` or `renovate/` |
| Force push needed urgently | Create emergency PR or contact maintainers for review |
