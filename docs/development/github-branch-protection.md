# GitHub Branch Protection Setup

This guide explains how to configure GitHub branch protection rules to enforce gitflow compliance.

## Quick Setup (Manual)

1. **Go to Repository Settings**
   - Navigate to `https://github.com/pingu/sagaz/settings/branches`

2. **Add Branch Protection Rule**
   - Click "Add rule"
   - Branch name pattern: `develop`
   - Click "Create"

3. **Configure Protection Settings**

### Required Settings

#### ✅ Require pull request reviews before merging
- **Number of approving reviews**: 1
- ☑️ Dismiss stale pull request approvals when new commits are pushed
- ☑️ Require review from Code Owners (if CODEOWNERS file exists)

#### ✅ Require status checks to pass before merging
- ☑️ Require branches to be up to date before merging

**Required status checks:**
- `Validate Commit Messages` (commitlint validation)
- `Validate Branch Name` (branch naming validation)
- Any other required checks (tests, linting, coverage, etc.)

#### ✅ Require conversation resolution before merging
- ☑️ All conversations must be resolved before merge is allowed

#### ✅ Require a linear history
- ☐ Keep disabled (allows merge commits and squash merges)

#### ✅ Restrict who can push to matching branches
- Leave unset (allow all)

#### ✅ Additional restrictions
- ☑️ Enforce all the above settings for administrators
- ☑️ Allow force pushes: Disabled
- ☑️ Allow deletions: Disabled

## Automated Setup (via Script)

If you have GitHub CLI access, run:

```bash
# Install gh if needed: https://cli.github.com
gh auth login

# Make script executable
chmod +x scripts/setup-branch-protection.sh

# Run setup (requires GitHub token with repo access)
scripts/setup-branch-protection.sh $GITHUB_TOKEN
```

## For All Feature Branches

Create a second rule for all feature branches:

1. **Branch name pattern**: `feature/*`
2. **Status checks**:
   - Require: `Validate Commit Messages`
   - Require: `Validate Branch Name`
3. **Dismiss stale reviews on new commits**: ✅

Repeat for other branch patterns:
- `fix/*`
- `docs/*`
- `ci/*`
- `chore/*`

## Verification

After configuration, verify that:

1. **Feature branch PRs are blocked** until:
   - ✅ At least 1 approval from code owner
   - ✅ All status checks pass (commitlint, tests, etc.)
   - ✅ All conversations are resolved

2. **Admins cannot bypass** the protection rules

3. **Force pushes are disabled**

4. **Branch deletion is prevented**

## Testing the Rules

### Test 1: Empty commit message (should fail)

```bash
# Clone a feature branch
git checkout -b test/empty-commit

# Try to make a commit with empty message
echo "test" > test.txt
git add test.txt
git commit -m ""  # Empty message
# This should be rejected by the commit-msg hook

# Try to push anyway (bypassing hook)
git push origin test/empty-commit --no-verify
# This will fail at GitHub with status check failure
```

### Test 2: Invalid branch name (should fail at push)

```bash
# Create branch with invalid name
git checkout -b my-feature  # Missing type/

# Try to push
git push origin my-feature
# pre-push hook should reject this
```

### Test 3: Valid commit (should succeed)

```bash
git checkout -b feature/test-validation

echo "test" > test.txt
git add test.txt
git commit -m "feat(test): validate commit message format"
git push origin feature/test-validation
# This should succeed and create a PR
```

## Troubleshooting

### "Branch protection rule not working"

If commits are still allowed without status checks:

1. Verify the rule is **not disabled**
2. Check that status checks are actually **required** (not just recommended)
3. Make sure the workflow file (`.github/workflows/validate-commits.yml`) is:
   - In the default branch (develop)
   - Properly formatted YAML
   - Triggering on the right events

### "Status check is missing"

If a status check isn't showing up:

1. Run the workflow manually: `gh workflow run validate-commits.yml`
2. Wait for the workflow to complete (it must run at least once)
3. The status should then appear in the branch protection UI

### "Admins can still bypass"

If admins can bypass protection:

1. Uncheck "Allow administrators to bypass required status checks"
2. Save the rule
3. Now admins are also bound by the rules

## References

- [GitHub Branch Protection Rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)
- [GitHub Status Checks](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories/about-status-checks)
- [GitHub CLI](https://cli.github.com)
