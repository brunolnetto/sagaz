#!/bin/bash
# Run tests with coverage - handles parallel execution properly

set -e

cd "$(dirname "$0")/.."

echo "======================================"
echo "Running Sagaz Test Coverage"
echo "======================================"
echo ""

# Clean up old coverage data
echo "🧹 Cleaning up old coverage files..."
rm -f .coverage .coverage.* coverage.json

# Run tests with proper coverage collection for parallel execution
echo "🧪 Running tests with coverage..."
echo ""

# Use pytest-cov with --cov-append for parallel execution
# This prevents the database corruption issue
pytest \
  --cov=sagaz \
  --cov-report=json:coverage.json \
  --cov-report=term-missing \
  --cov-append \
  -n auto \
  --quiet \
  --tb=short \
  "$@"

echo ""
echo "======================================"
echo "✅ Coverage collection complete!"
echo "======================================"
echo ""
echo "📊 Results saved to: coverage.json"
echo "📈 Run analyzer with: ./scripts/coverage_analyzer.py coverage.json"
