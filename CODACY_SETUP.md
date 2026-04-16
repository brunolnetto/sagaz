# Codacy Integration Guide

## 📋 Overview

This project uses **Codacy** for continuous code quality analysis. Codacy automatically reviews pull requests and generates quality reports.

## 🚀 Setup Steps

### 1. Add Repository to Codacy

**First time only:**

1. Go to [app.codacy.com](https://app.codacy.com)
2. Log in with your GitHub account
3. Click **Add Repository** (or Dashboard → Repositories → Add)
4. Find **brunolnetto/sagaz** in the list
5. Click **Add Repository**
6. Wait for initial analysis to complete (usually 1-2 minutes)

### 2. Create Project API Token

1. In Codacy dashboard, go to **Settings** → **Integrations** (or Organization settings)
2. Look for **API Tokens** or **Project Tokens**
3. Create a new project API token
4. Copy the token

### 3. Configure GitHub Secret

Set the token in GitHub:

```bash
gh secret set CODACY_PROJECT_TOKEN --body "your-token-from-step-2"
```

Or via GitHub web UI:
- Go to **Settings** → **Secrets and variables** → **Actions**
- Click **New repository secret**
- Name: `CODACY_PROJECT_TOKEN`
- Value: Your Codacy token

### 4. Merge CI Workflow

PR #216 adds Codacy to the CI pipeline. Once merged, Codacy analysis will run on every PR.

```bash
# Merge PR #216 to main
gh pr merge 216
```

## 📊 Using Codacy

### Automatic: GitHub Integration

Once set up, Codacy will:
- ✅ Review every pull request
- ✅ Comment with issues found
- ✅ Add quality checks to PR status

### Manual: Fetch Issues

**Fetch issues locally:**

```bash
export CODACY_PROJECT_TOKEN=your-token
python3 scripts/fetch_codacy_issues.py --severity Error
```

**Fetch via GitHub Actions:**

1. Go to **Actions** → **Fetch Codacy Issues**
2. Click **Run workflow**
3. Select filter options (Error, Warning, Info, All)
4. Results saved as artifact

**Alternative: Use local analysis (offline):**

```bash
python3 scripts/analyze_quality_local.py
```

## 🔑 API Keys & Tokens

### Token Types

| Type | Usage | Format |
|------|-------|--------|
| **Project Token** | Fetching issues, PR comments | 20 alphanumeric chars |
| **Organization Token** | Managing projects, teams | Different format |
| **Personal Token** | User account access | Different format |

**For this project:** Use **Project API Token**

### Where to Find Token

1. Codacy Dashboard → Settings
2. Look for: **API Tokens** → **Project Tokens**
3. Should start with something like: `d6nWhqQSmJLTCR9UPvtS`

## 📁 Files

| File | Purpose |
|------|---------|
| `.github/workflows/fetch-codacy-issues.yml` | GitHub Actions to fetch issues |
| `.github/workflows/quality-gates.yml` | CI job that runs Codacy analysis |
| `scripts/fetch_codacy_issues.py` | Python CLI to fetch issues |
| `scripts/analyze_quality_local.py` | Local quality analysis (offline) |
| `CODACY_SETUP.md` | This file |

## 🐛 Troubleshooting

### API Returns 404

**Problem:** `The requested resource could not be found`

**Solution:**
1. ✅ Ensure repository is added to Codacy (Step 1 above)
2. ✅ Wait for initial analysis to complete
3. ✅ Verify token is correct
4. ✅ Check token is for correct project (not organization)

### Workflow Doesn't Run

**Problem:** Codacy job doesn't execute

**Solution:**
1. ✅ Ensure CODACY_PROJECT_TOKEN secret is set
2. ✅ Check PR #216 is merged (adds job to workflow)
3. ✅ Manually trigger: **Actions** → **Quality Gates** → **Run workflow**

### Secret Not Available

**Problem:** `CODACY_PROJECT_TOKEN is not set`

**Solution:**
```bash
# Verify secret is set
gh secret list | grep CODACY

# Re-set if missing
gh secret set CODACY_PROJECT_TOKEN --body "your-token"
```

## 📚 References

- [Codacy Documentation](https://docs.codacy.com)
- [Codacy API](https://docs.codacy.com/api/)
- [GitHub Secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets)

## 🔄 Next Steps

1. ✅ Add repository to Codacy (if not done)
2. ✅ Create project API token in Codacy
3. ✅ Set `CODACY_PROJECT_TOKEN` in GitHub secrets
4. ✅ Merge PR #216 to enable Codacy in CI
5. ✅ Create pull request to trigger first Codacy analysis

## ✨ After Setup

- Codacy will review all PRs automatically
- Issues will appear as GitHub checks
- Code quality badge displays on README
- Historical trends tracked in Codacy dashboard

---

**Current Status:**
- Repository token: ✅ Set (d6nWhqQSmJLTCR9UPvtS)
- GitHub secret: ✅ Configured
- CI integration: ⏳ PR #216 (pending merge)
- Local analysis tools: ✅ Available
