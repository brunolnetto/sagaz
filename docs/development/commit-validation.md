# Commit Validation & Branch Protection Guide

This document describes the gitflow compliance measures and how to enforce them.

## Overview

The sagaz project uses **conventional commits** with **branch naming conventions** and automated validation to maintain code quality and enforce gitflow compliance.

## Conventional Commit Format

All commits must follow this format:

```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

### Rules

- **Type**: One of `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `chore`, `revert`
- **Scope**: One of the approved scopes (see `commitlint.config.cjs`)
- **Subject**: Lowercase, no period, maximum 72 characters, imperative mood
- **Empty messages**: NOT allowed and will be rejected

### Approved Scopes

- `saga` - core saga engine
- `dag` - DAG / parallel execution  
- `outbox` - transactional outbox
- `storage` - storage backends
- `strategies` - failure strategies
- `monitoring` - metrics, logging, tracing
- `cli` - CLI commands
- `execution` - saga execution
- `triggers` - saga triggers
- `visualization` - visualization UI
- `integrations` - external integrations
- `sagaz` - general sagaz changes
- `docs` - documentation
- `ci` - CI/CD workflows
- `deps` - dependency updates
- `tests` - test suite

### Examples

✅ Good commits:
```
feat(storage): add sqlite backend support
fix(saga): handle concurrent step execution
docs(cli): update installation guide
chore(deps): update pytest to v9.0.0
ci(workflows): add commit validation
```

❌ Bad commits:
```
Updated storage module  (no type/scope)
feat(storage): Added SQLite  (uppercase, period)
""  (empty message)
fixed bug  (no scope)
```

## Local Validation

### Install Git Hooks

When you clone or pull the repository, install git hooks:

```bash
npm install
npx husky install
```

Or use the npm script:

```bash
npm run hooks:install
```

### Commit Hook

When you run `git commit`, the `commit-msg` hook will:

1. ✅ Check for empty messages (reject if empty)
2. ✅ Validate type (feat, fix, docs, etc.)
3. ✅ Validate scope (saga, storage, cli, etc.)
4. ✅ Validate subject format (lowercase, no period)

**Example rejection:**

```
❌ COMMIT MESSAGE EMPTY

Your commit message is empty. Please provide a meaningful commit message.

Format: <type>(<scope>): <subject>

Examples:
  feat(storage): add sqlite backend support
  fix(saga): handle concurrent step execution
  docs(cli): update installation instructions
```

### Pre-Push Hook

Before pushing to remote, the `pre-push` hook will:

1. ✅ Validate branch name follows `<type>/<topic>` pattern
2. ✅ Check all commits have non-empty messages
3. ✅ Skip validation for develop/main (CI handles it)

**Example rejection:**

```
❌ INVALID BRANCH NAME: my-feature

Branch names must follow: <type>/<topic>
  - type: feature, fix, docs, refactor, test, chore, ci
  - topic: lowercase letters, numbers, and hyphens only

Examples:
  feature/saga-replay
  fix/storage-pool-leak
  docs/update-dev-guides
```

### Prepare Commit Message Hook

If your commit message is empty, the `prepare-commit-msg` hook adds a template comment to guide you:

```
# ============================================================================
# Commit Message Template
# ============================================================================
# <type>(<scope>): <subject>
#
# Allowed types: feat, fix, docs, refactor, test, perf, build, ci, chore, revert
# Scope examples: saga, dag, outbox, storage, cli, monitoring, etc.
#
# Examples:
#   feat(storage): add sqlite backend
#   fix(saga): handle concurrent execution
#   docs(cli): update installation guide
```

## CI Validation

### Commit Validation Workflow

A GitHub Actions workflow (`.github/workflows/validate-commits.yml`) runs on all:

- **Pull requests** - validates all commits to be merged
- **Pushes to feature branches** - validates before merge
- **Pushes to develop/main** - validates to prevent bad commits

**Checks:**
1. ✅ commitlint validation (type, scope, subject format)
2. ✅ Rejects empty commit messages
3. ✅ Validates branch names match `<type>/<topic>` pattern (PRs only)

If validation fails, the workflow will fail and block merging until issues are fixed.

## GitHub Branch Protection Rules

To enforce these rules at the GitHub level, configure:

### Settings → Branches → Develop Branch Rules

Create a branch protection rule for `develop` with:

- ✅ **Require pull request reviews before merging**
  - Dismiss stale pull request approvals when new commits are pushed
  
- ✅ **Require status checks to pass before merging**
  - Required checks:
    - `Validate Commit Messages` (commitlint)
    - `Validate Branch Name` (branch naming)
    - Any other required test/lint checks
  - Require branches to be up to date before merging
  
- ✅ **Require code reviews from code owners** (if CODEOWNERS file present)

- ✅ **Require conversation resolution before merging**

- ✅ **Do not allow bypassing the above settings**

### Enforce for All Branches

For all feature branches, create a fallback rule:

- Pattern: `*/[a-z0-9]*/[a-z0-9-]*` (matches `feature/`*, `fix/*`, etc.)
- Require status checks: `Validate Commit Messages`, `Validate Branch Name`

## Troubleshooting

### "Husky hooks not working"

If hooks aren't running on commit:

```bash
# Reinstall husky
npm run hooks:install

# Or manually:
npx husky install

# Verify hooks are installed
ls -la .husky/
```

### "My commit was rejected"

Check the error message. Common issues:

1. **Empty message** - Add a message with type and scope
2. **Invalid type** - Use one from: feat, fix, docs, refactor, test, perf, build, ci, chore, revert
3. **Invalid scope** - Check the approved scopes list above
4. **Invalid subject** - Keep lowercase, no trailing period, max 72 chars

### "Pre-push hook rejects my branch"

Example error:
```
❌ INVALID BRANCH NAME: my-feature
```

**Solution:** Delete and recreate with correct name:
```bash
git checkout -b feature/my-feature
git push origin feature/my-feature
```

### "Renovate bot commits blocked"

Renovate is configured to use `chore(deps): update ...` format. If PRs still have empty messages:

1. **Check renovate.json** is configured with `commitMessagePrefix`, `commitMessageAction`, `commitMessageTopic`
2. **Verify renovate settings** on GitHub (Settings → Integrations → Renovate)
3. **Manually add commit messages** if renovate generates empty ones

## Disabling Hooks (Not Recommended)

If you need to bypass hooks temporarily:

```bash
# Skip pre-commit hook
git commit --no-verify

# Skip pre-push hook
git push --no-verify
```

**Warning:** This bypasses validation. Only use if absolutely necessary and get review before merging.

## References

- [Conventional Commits](https://www.conventionalcommits.org/)
- [commitlint Documentation](https://commitlint.js.org/)
- [Husky](https://husky.dev/)
- [GitHub Branch Protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)
