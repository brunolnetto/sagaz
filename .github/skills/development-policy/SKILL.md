---
name: development-policy
description: "Use when applying or reminding about PR-based feature work, test regression thresholds, commitlint rules, and TDD workflow."
---

# Development Policy

- Any new feature must be assigned to a PR; do not publish directly to `main`.
- New work should be implemented on a dedicated feature branch and reviewed via PR before merging.
- Regression-sensitive features must preserve coverage at or above `95%` relative to `main`.
- Follow TDD with a red-green-refactor cycle: write failing tests first, then implement code to pass them.
- Keep unit, integration, end-to-end, and performance tests clearly separated.
- Use lightweight testcontainers or ephemeral container fixtures when available.
- Commits must follow conventional commit style and the repository's commitlint rules:
  - `type` must be one of `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `chore`, `revert`
  - `scope` must be present and non-empty
  - `subject` must not use sentence case, start case, or pascal case
  - `subject` must not end with a full stop
- When repo-specific `scope` values are defined, use the approved scope list:
  `saga`, `dag`, `outbox`, `storage`, `strategies`, `monitoring`, `cli`, `execution`,
  `triggers`, `visualization`, `integrations`, `sagaz`, `docs`, `ci`, `deps`, `tests`

## Branch Naming

Branches must follow `<type>/<topic>` where type is one of:
`feature`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`

Examples: `feature/saga-replay`, `docs/refactor-dev-guides`, `fix/storage-pool-leak`
