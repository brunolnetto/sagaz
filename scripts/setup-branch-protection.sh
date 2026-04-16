#!/bin/bash
# Configure GitHub branch protection rules via API
# Usage: ./scripts/setup-branch-protection.sh [token]

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <github-token>"
  echo ""
  echo "Personal access token should have 'admin:repo_hook' and 'repo' scopes"
  exit 1
fi

TOKEN="$1"
REPO="brunolnetto/sagaz"  # Update this with your repo
OWNER="brunolnetto"
REPO_NAME="sagaz"

echo "Configuring branch protection rules for $REPO..."
echo ""

# Function to configure branch protection
configure_branch() {
  local branch=$1
  local description=$2
  
  echo "📋 Configuring: $branch ($description)"
  
  # Update branch protection rule
  curl -X PUT \
    -H "Accept: application/vnd.github.v3+json" \
    -H "Authorization: token $TOKEN" \
    "https://api.github.com/repos/$REPO/branches/$branch/protection" \
    -d '{
      "required_status_checks": {
        "strict": true,
        "contexts": [
          "Validate Commit Messages",
          "Validate Branch Name",
          "tests",
          "lint",
          "coverage"
        ]
      },
      "enforce_admins": true,
      "required_pull_request_reviews": {
        "dismiss_stale_reviews": true,
        "require_code_owner_reviews": false,
        "required_approving_review_count": 1
      },
      "restrictions": null,
      "required_linear_history": false,
      "allow_force_pushes": false,
      "allow_deletions": false,
      "required_conversation_resolution": true
    }' > /dev/null 2>&1
  
  if [ $? -eq 0 ]; then
    echo "  ✅ Branch protection configured"
  else
    echo "  ❌ Failed to configure (check token and API access)"
  fi
}

# Configure main branch  
configure_branch "develop" "Main development branch"

# Configure main if it exists
configure_branch "main" "Production branch" 2>/dev/null || true

echo ""
echo "✅ Branch protection rules configured!"
echo ""
echo "Configuration summary:"
echo "  - Require commit status checks to pass"
echo "  - Dismiss stale reviews on new commits"
echo "  - Enforce admins to follow rules"
echo "  - Require conversation resolution before merge"
echo "  - Prevent force pushes and deletions"
echo ""
echo "⚠️  Note: You can also configure these rules manually in GitHub:"
echo "   Settings → Branches → Branch Protection Rules"
