#!/bin/bash
# Simple coverage runner - no parallel, no complications

set -e
cd "$(dirname "$0")/.."

echo "🧹 Cleaning up..."
rm -f .coverage .coverage.* coverage.json

echo "🧪 Running tests with coverage..."
pytest --cov=sagaz --cov-report=json:coverage.json --cov-report=term --tb=short -q

echo ""
echo "✅ Done! Results in coverage.json"
echo "📊 Analyze: ./scripts/coverage_analyzer.py coverage.json"
