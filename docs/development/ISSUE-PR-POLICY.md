# Issue-PR Relationship Policy

## Overview

This policy defines when issues should be created, how they relate to PRs, and what "closes/fixes/resolves" means in the context of our GitFlow workflow.

**Primary Goal**: Maintain a clean, actionable issue backlog while using PRs as the primary unit of work.

---

## When to Create an Issue

### ✅ Create an Issue For:

1. **Bug Reports**
   - User-facing or developer-facing bugs
   - Unexpected behavior or crashes
   - Security vulnerabilities
   - Performance regressions
   - Example: "Database connection pool exhaustion under load"

2. **Feature Requests**
   - New capabilities or enhancements
   - API improvements
   - Missing functionality
   - Example: "Add support for multi-region saga coordination"

3. **Technical Debt**
   - Code quality improvements
   - Refactoring needs
   - Architectural improvements
   - Documentation gaps
   - Example: "Refactor storage layer to reduce coupling"

4. **Discussions & Decisions**
   - Architectural decisions (ADRs)
   - Design reviews
   - API design discussions
   - Example: "ADR-019: Event sourcing as optional storage strategy"

### ❌ Do NOT Create an Issue For:

1. **Dependency Updates**
   - Renovate/Dependabot PRs auto-reference versions
   - No separate issue tracking needed
   - Exception: Major version updates with breaking changes (create issue for tracking)

2. **Repository Maintenance**
   - CI/CD workflow updates
   - GitHub Actions version bumps
   - Configuration file tweaks
   - Routine chore work
   - Example: "Update GitHub Actions to latest versions" → No issue needed

3. **Documentation-Only Changes**
   - README updates
   - Typo fixes
   - Comment improvements
   - **Exception**: If documenting a new feature/bug fix (link to parent issue instead)

4. **Trivial Fixes**
   - Single-line fixes
   - Test-only changes
   - Build process fixes
   - **Exception**: If fixing a reported bug (link to parent issue)

---

## Issue Reference in PRs

### Reference Types

#### 1. **"Closes" (default for most issues)**
Use when the PR **completely resolves** the issue:
```
Closes #123
```
- GitHub **automatically closes** the issue when PR merges
- Used for: Bug fixes, feature completion, task completion
- Guarantees: Issue is fully resolved, no follow-up work needed

#### 2. **"Fixes" (synonym for "Closes")**
Use interchangeably with "Closes":
```
Fixes #456
```
- GitHub **automatically closes** the issue when PR merges
- Semantically identical to "Closes"

#### 3. **"Resolves" (synonym for "Closes")**
Use interchangeably with "Closes":
```
Resolves #789
```
- GitHub **automatically closes** the issue when PR merges
- Semantically identical to "Closes"

#### 4. **"Relates to" or "Ref" (when NOT closing)**
Use when the PR is **related to but does NOT fully resolve** the issue:
```
Relates to #999
or
Ref: #999
```
- GitHub does **NOT** automatically close the issue
- Used for: Partial work, follow-up work, refactoring related to feature
- **Note**: Not validated by workflow (optional reference)
- Example: PR partially implements feature → "Relates to #999, see Phase 2"

#### 5. **No Reference (allowed for specific cases)**
When the PR is **completely self-contained** and does NOT relate to any issue:
- Use only for **explicitly exempt PR types** (see below)
- Example: Dependency update PR with "chore(deps): update node to v24"

---

## PR Categories & Issue Requirements

### Category 1: Feature PRs (feature/*)
**Issue Requirement**: ✅ **REQUIRED**
- Must use `Closes #<n>` or `Fixes #<n>` or `Resolves #<n>`
- Issue must be a feature request or epic
- Exception: If PR is a phase or subtask, use `Relates to #<n>` instead

**Example PR Title**: `feat(saga): add replay capability for saga execution`
**Example Reference**: `Closes #42` (where #42 is the feature request)

---

### Category 2: Bug Fix PRs (fix/*)
**Issue Requirement**: ✅ **REQUIRED**
- Must use `Closes #<n>` or `Fixes #<n>`
- Issue must be a bug report
- Exception: Obvious/trivial fix found during development → `Relates to #<n>`

**Example PR Title**: `fix(storage): resolve connection pool leak on disconnect`
**Example Reference**: `Closes #85` (where #85 is the bug report)

---

### Category 3: Documentation PRs (docs/*)
**Issue Requirement**: ⚠️ **DEPENDS ON SCOPE**

**Requires Issue** (`Closes #<n>`):
- Documentation for a new feature (link to feature PR/issue #)
- Architectural Decision Record (ADR)
- Significant documentation gap or overhaul

**No Issue Needed**:
- README typo fixes
- Comment improvements
- Minor clarifications
- Inline documentation updates
- Use commit message like: `docs(saga): clarify compensation semantics in docstring`

---

### Category 4: Refactoring PRs (refactor/*)
**Issue Requirement**: ⚠️ **DEPENDS ON SCOPE**

**Requires Issue** (`Closes #<n>` or `Relates to #<n>`):
- Large-scale refactoring (> several files)
- Architectural refactoring
- Major API changes
- Technical debt resolution (link to technical debt issue)

**No Issue Needed**:
- Small localized refactoring
- Improving a single function/module
- Comment message like: `refactor(monitoring): simplify metric registration pattern`

---

### Category 5: Test PRs (test/*)
**Issue Requirement**: ❌ **NEVER REQUIRED**
- Test improvements rarely warrant separate issues
- Use commit message: `test(saga): add comprehensive compensation testing`
- Exception: If testing recently merged work, can reference feature PR

---

### Category 6: Performance PRs (perf/*)
**Issue Requirement**: ⚠️ **DEPENDS ON CONTEXT**

**Requires Issue**:
- Performance regression fix (link to bug report)
- Optimization addressing performance target/quota
- Performance improvement project

**No Issue Needed**:
- Incidental optimization during feature work
- Use: `perf(storage): cache compiled queries for 10% throughput gain`

---

### Category 7: Build/CI PRs (build/*, ci/*)
**Issue Requirement**: ❌ **NEVER REQUIRED**
- CI flow updates
- Build tooling changes
- GitHub Actions updates
- Use: `ci(workflows): add performance regression detection to quality gates`

---

### Category 8: Chore PRs (chore/*)
**Issue Requirement**: ❌ **NEVER REQUIRED** (with exceptions)

**No Issue Needed** (most common):
- `chore(deps): update postgres docker tag to v18`
- `chore(repo): add .gitignore entry for local cache`
- `chore(release): bump version to 2.1.0`

**Requires Issue** (exceptions only):
- Major dependency migration (e.g., "chore(deps): migrate from asyncpg to psycopg3")
- Significant dependency security update

---

### Category 9: Revert PRs (revert/*)
**Issue Requirement**: ⚠️ **DEPENDS ON REASON**

**Requires Issue** (open new issue):
- Reverting due to bug/regression (create issue, link it)
- Use: `Relates to #xyz` (the problem found)

**No Issue Needed**:
- Reverting due to merge conflict or build issue
- Use: `revert: revert #456 due to unresolved build conflict`

---

### Category 10: Renovate/Dependabot PRs
**Issue Requirement**: ❌ **NEVER REQUIRED**
- Dependency update bot PRs are exempt
- Workflow automatically skips validation for `dependabot/` and `renovate/` branches
- Exception: Create issue for tracking major breaking changes separately

---

## Workflow Validation Rules

### Current Validation

The `require-issue` job in `gitflow-compliance.yml` validates:

```javascript
// Required reference patterns (case-insensitive):
/closes\s*:?\s+#\d+(?:[.,;!?]|\s|$)/
/fixes\s*:?\s+#\d+(?:[.,;!?]|\s|$)/
/resolves\s*:?\s+#\d+(?:[.,;!?]|\s|$)/
/relates\s+to\s*:?\s+#\d+(?:[.,;!?]|\s|$)/
/ref\s*:?\s+#\d+(?:[.,;!?]|\s|$)/
```

Both `Closes #123` and `closes: #123` are valid.

### PR Types Exempt From Validation

The following PR types do **NOT** require issue references (workflow checks are skipped):
- Test PRs (`test/` branches)
- CI PRs (`ci/` branches)
- Build PRs (`build/` branches)
- Chore PRs (`chore/` branches)
- Documentation PRs (`docs/` branches)
- Renovate PRs (`renovate/` branches)
- Dependabot PRs (`dependabot/` branches)

### PR Types Required to Have Issue References

Feature and fix PRs must include one of the reference patterns above.

---

## Best Practices

### 1. Link Issues BEFORE Creating PR
- Discuss large features/bugs in issues first
- Get feedback before starting implementation
- Reduces rework and conflicting implementations

### 2. Use Descriptive Issue Titles
Instead of: "Fix bug" → Use: "Database connection returns stale data under concurrent load"
- Makes issue backlog searchable
- Helps future developers understand context

### 3. One Primary Issue Per PR
- Avoid mixing multiple unrelated features in one PR
- If PR addresses multiple issues, use `Closes #123` for primary + `Relates to #456` for secondary
- Example:
  ```
  Closes #123
  Relates to #456
  ```

### 4. Close Issues Intentionally
- Only close when work is truly complete
- If partial/ongoing, use `Relates to #<n>` instead
- Reopened issues waste team visibility

### 5. Reference During PR Description
- Always include issue reference in PR body (not commit message)
- GitHub uses PR body for auto-closing on merge
- Example in PR body:
  ```markdown
  ## Changes
  - Added saga replay mechanism
  - Added replay tests
  - Updated docs
  
  Closes #42
  ```

### 6. Use Conventional Commits With Issue Numbers
**In commit messages** (optional, but recommended):
```bash
git commit -m "feat(saga): add replay capability (#42)

- Implement replay from checkpoint
- Add replay tests
- Update saga documentation"
```

This creates a commit reference to issue #42 in the GitHub UI.

---

## Issue Lifecycle

### Creation
1. **Reporter** creates issue with:
   - Clear title
   - Detailed description (if bug: reproduction steps)
   - Relevant labels (bug, feature, enhancement, etc.)
   - Optional: Assign to a developer or milestone

### Development
2. **Developer** creates PR that references the issue:
   ```
   Closes #<number>
   ```

### Completion
3. **Reviewer** approves PR
4. **Developer** merges PR
5. GitHub **automatically closes** the issue

### (Optional) Follow-Up
6. If issues remain, **create new issue** for next phase:
   ```
   Relates to #123 (original feature)
   ```

---

## Examples

### ✅ Good: Feature with Phases

**Issue #42**: "Implement multi-region saga coordination"
```
## Problem
Sagas currently only work within a single region.

## Solution
Implement cross-region coordination with eventual consistency.

## Phases
- Phase 1: Region registry and discovery (PR #100)
- Phase 2: Cross-region messaging (PR #101)
- Phase 3: Failover and recovery (PR #102)
```

PR #100 commit message:
```
feat(saga): implement region registry and discovery (#42)

Closes #42 (Phase 1 complete, phases 2-3 tracked separately)
```

---

### ✅ Good: Bug Fix

**Issue #87**: "Database connection returns stale data under concurrent load"
```
## Steps to Reproduce
1. Run 100 concurrent saga executions
2. Check event log
3. See 5-10% of events have stale data

## Expected
All events have current data

## Actual
5-10% have data from 1-2 seconds prior
```

PR #99 title: `fix(storage): add connection pool refresh on stale data detection`
```
Closes #87
```

---

### ✅ Good: Chore (No Issue)

PR title: `chore(deps): update postgres to v18`
```
No issue reference needed for routine dependency updates.
```

---

### ✅ Good: Documentation (No Issue)

PR title: `docs(saga): clarify compensation semantics in README`
```
No issue reference needed for documentation clarity updates.
```

---

### ❌ Bad: Create Issues for Everything

**Anti-Pattern**: Creating separate issues for:
- Each dependency update (Renovate handles this)
- Trivial typo fixes
- CI workflow tweaks
- Minor code cleanup

**Result**: Issue graveyard that no one reads

---

## FAQ

**Q: What if my PR doesn't fit neatly into one category?**
A: Use your best judgment. The intent is:
- **Bug fix?** → Use `Closes #<n>`
- **Feature?** → Use `Closes #<n>`
- **Chore/maintenance?** → No issue needed
- **Partial work?** → Use `Relates to #<n>`

**Q: Can I still create a PR without an issue?**
A: Yes, if your PR is in an exempt category (chore, ci, build, test, docs, etc.). The workflow will **not** block you. For feature/fix PRs, you must either:
1. Create a new issue first, or
2. Use an existing related issue

**Q: What if I fix multiple bugs in one PR?**
A: Create a commit for each bug (with the bug number in the message), but use `Closes #<n>` for the primary bug and `Relates to #<m>` for secondary bugs in the PR body:
```
Closes #100
Relates to #101, #102
```

**Q: Can I close an issue without a PR?**
A: Yes, you can close an issue directly if:
- It's a duplicate → Close with "Duplicate of #<n>"
- It's not reproducible → Close with explanation
- It was completed outside of GitHub → Close with comment linking external work

**Q: What does "Relates to" do?**
A: It creates a link in GitHub's UI but does NOT automatically close the issue. This is useful for:
- Feature phases/increments
- Related but not directly solving the issue
- Follow-up work

---

## Updating This Policy

To propose changes to this policy:
1. Open an issue describing the change
2. Discuss in the issue
3. Update this document via PR (`docs(ci): update issue-PR relationship policy`)
4. Update workflow validation rules if needed
5. Announce change to team

