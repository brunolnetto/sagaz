# Branch Naming Convention

## Pattern

`<type>/<topic>`

Where:

- **type** — category of the change (see table below)
- **topic** — short hyphen-separated description

## Allowed Types

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feature/` | New functionality | `feature/saga-replay` |
| `fix/` | Bug fixes | `fix/storage-pool-leak` |
| `docs/` | Documentation updates | `docs/refactor-dev-guides` |
| `refactor/` | Code restructuring without behaviour change | `refactor/outbox-worker` |
| `test/` | Tests only | `test/dag-parallel-ordering` |
| `chore/` | Maintenance (deps, tooling, CI) | `chore/update-commitlint` |
| `ci/` | CI/CD workflow changes | `ci/add-branch-validation` |

## Recommendations

- Use lowercase letters only
- Use hyphens (`-`) to separate words — no underscores, no spaces
- Keep names concise and descriptive
- Scope to a single concern per branch

## Enforcement

The `validate-branch-flow` CI workflow rejects PRs whose head branch does not match the allowed pattern.
