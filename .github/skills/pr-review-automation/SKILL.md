---
name: pr-review-automation
description: "Automate PR review workflows: fetch and apply Copilot review suggestions, check/fix broken guard checks (commitlint, PR validation, branch policies), and apply test recommendations."
---

# PR Review & Guard Check Automation

## Overview

This skill automates the common workflow of:
1. **Fetching AI code review** — Pull Copilot review suggestions from active/open PRs
2. **Applying suggestions** — Implement suggested changes with proper testing
3. **Fixing broken guards** — Diagnose and fix commitlint, branch validation, PR title format, and other checks
4. **Validating changes** — Re-run guards to ensure everything passes

**Typical workflow:**
```
gh pr view 161 --json comments  [fetch Copilot review]
  ↓
[Analyze suggestions + implement changes]
  ↓
git commit + git push  [push changes]
  ↓
gh pr view 161 --json statusCheckRollup  [verify all checks pass]
```

---

## Key Operations

### 1. Fetch Copilot Code Review Comments

**Goal**: Retrieve AI-generated review suggestions from open PR

**Command**: 
```bash
gh pr view <NUMBER> --json comments --jq '.comments[] | select(.author.login | contains("copilot")) | {body, url, state}'
```

**Also check**: Review comments (line-level suggestions), not just PR-level comments
```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '.[] | select(.user.login | contains("copilot"))'
```

**Output to check**:
- Comment author is `copilot-*` bot
- Comment contains `// suggestion:` or similar marker
- Line references specific code location
- Suggestion includes rationale

---

### 2. Detect & Fix Broken Guard Checks

**Common guard checks that fail**:

| Guard | Failure Message | Fix |
|-------|-----------------|-----|
| **Commitlint** | "type must be one of..." | Update commit message type (feat/fix/docs/etc) |
| **Validate PR Title** | "PR title must match pattern" | Update PR title format (`type(scope): subject`) |
| **Require Issue Reference** | "No issue linked" | Link issue in PR description or commit |
| **Branch Naming** | "Branch must follow pattern" | Rename branch (feature/, fix/, docs/, etc) |
| **Prevent Direct Push** | "Branch is protected" | Use PR instead of direct push |

**Detection strategy**:
```bash
# Get failed status checks
gh pr view <NUMBER> --json statusCheckRollup --jq '.statusCheckRollup[] | select(.conclusion != "SUCCESS" and .conclusion != "SKIPPED")'

# Or get logs (if available)
gh run list --status failure --branch <branch> --limit 1 --json databaseId,conclusion
```

**Fix strategies**:

#### Commitlint Fix
```bash
# Check what failed
git log --oneline HEAD~3..HEAD | head -1  # See last commit

# Amend if type is wrong
git commit --amend --message "fix(scope): new message"  # Change type: style→fix, wrong scope, etc
git push --force-with-lease
```

#### PR Title Format
```bash
# Update PR title (requires PR number)
gh pr edit <NUMBER> --title "feat(scope): description here"
```

#### Link Issue
```bash
# Add issue to PR description or use CLI
gh pr edit <NUMBER> --add-assignee @me
# Or edit description manually to add "Closes #<issue>" or "Related to #<issue>"
```

---

### 3. Apply Copilot Suggestions

**Workflow**:

1. **Parse suggestion** from comment
   - Extract code location (file, line range)
   - Extract intended change
   - Identify type (assert strengthening, mock improvement, documentation, etc)

2. **Apply programmatically** or **manually**
   ```bash
   # For straightforward suggestions: edit file directly
   git checkout <BRANCH>
   # Make changes
   git add .
   git commit -m "review(scope): apply Copilot suggestion — [brief description]"
   git push
   ```

3. **Test & validate**
   ```bash
   pytest tests/...  # Run affected tests
   ruff check .      # Lint
   mypy .            # Type check
   ```

4. **Verify guard checks pass**
   ```bash
   gh pr view <NUMBER> --json statusCheckRollup --jq '.statusCheckRollup[] | select(.conclusion != "SUCCESS" and .conclusion != "SKIPPED")'
   # Should return empty if all pass
   ```

---

## Execution Checklist

### Before applying suggestions:
- [ ] Fetch all Copilot comments from PR
- [ ] Verify each suggestion makes sense in context
- [ ] Identify dependencies between suggestions (apply in order)
- [ ] Check if test modifications require coverage verification

### During implementation:
- [ ] Use atomic commits (one suggestion = one commit when practical)
- [ ] Commit message: `review(scope): apply Copilot suggestion — <brief desc>`
- [ ] Follow project commitlint rules (`type(scope): subject`)
- [ ] Run local tests before pushing

### After pushing:
- [ ] Wait for CI to complete
- [ ] Check for remaining guard failures
- [ ] If failures detected, diagnose and fix immediately
- [ ] Re-verify all guards pass

### For guard check failures:
- [ ] Identify which guard failed (commitlint, title format, branch name, etc)
- [ ] Read failure message carefully
- [ ] Fix at source (commit message, PR title, branch name, issue link)
- [ ] Verify fix before next push (local validation where possible)
- [ ] Force-push if needed (`git push --force-with-lease`)

---

## Example: Complete Workflow

### Scenario: PR #161 with 3 Copilot suggestions + commitlint failure

**Step 1: Fetch suggestions**
```bash
gh pr view 161 --json comments,reviews \
  --jq '.reviews[] | select(.author.login | contains("copilot"))'
```

**Step 2: Identify guard failure**
```bash
gh pr view 161 --json statusCheckRollup \
  --jq '.statusCheckRollup[] | select(.conclusion != "SUCCESS" and .conclusion != "SKIPPED")'
# Output: Commitlint failed
```

**Step 3: Fix commitlint**
```bash
git log --oneline -1  # See what's wrong
git commit --amend --message "test(sagaz): apply Copilot suggestion — strengthen assertions"
git push --force-with-lease
```

**Step 4: Apply suggestions (3 separate commits)**
```bash
# Suggestion 1: Add type check to test_redis_storage_no_url_uses_default
git add tests/...
git commit -m "review(tests): add Redis type validation to default URL test"

# Suggestion 2: Add assertion to test_redis_storage_empty_url_skips_default  
git add tests/...
git commit -m "review(tests): assert InMemorySagaStorage on empty URL fallback"

# Suggestion 3: Fix comment accuracy
git add tests/...
git commit -m "review(tests): clarify _parse_storage_url behavior in test docstring"

git push
```

**Step 5: Verify all checks pass**
```bash
# Wait for CI, then verify
gh pr view 161 --json statusCheckRollup | grep -c "SUCCESS"
# Should show all checks passing
```

---

## Anti-Patterns to Avoid

❌ **Don't**:
- Apply suggestions without reading them carefully (may be incorrect context)
- Mix multiple unrelated suggestions in one commit
- Ignore commitlint failures (signal of bigger PR mismatch)
- Force-push without `--force-with-lease` (risky in team settings)
- Apply test suggestions without running full test suite

✅ **Do**:
- Review each Copilot suggestion in context before applying
- Use atomic, well-described commits for traceability
- Fix guard checks immediately when they fail
- Always test locally before pushing
- Use `--force-with-lease` when amending committed work

---

## Related PR Policies

This skill complements the **development-policy** skill:
- Commitlint types must be from approved list: `feat|fix|docs|refactor|test|perf|build|ci|chore|revert`
- PR titles must match `type(scope): subject` format
- Scope must be non-empty and match approved project scopes
- Subject must not use sentence case or end with period
- Issues must be referenced in PR description or commit message

See `.github/skills/development-policy/SKILL.md` for full policy.

---

## Quick Reference Commands

```bash
# Fetch all Copilot review comments on PR
gh pr view <NUMBER> --json comments --jq '.comments[] | select(.author.login | contains("copilot"))'

# Check failed guard checks
gh pr view <NUMBER> --json statusCheckRollup --jq '.statusCheckRollup[] | select(.conclusion != "SUCCESS" and .conclusion != "SKIPPED")'

# See commit history (for checking commitlint compliance)
git log --format="%h %s" | head -10

# Amend last commit (for fixing commitlint/PR title issues)
git commit --amend --message "fix(scope): corrected message"

# Safe force push (protects against concurrent changes)
git push --force-with-lease

# Run local tests before pushing
pytest tests/ -x  # Stop on first failure
ruff check .      # Lint
