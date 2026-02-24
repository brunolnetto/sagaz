#!/bin/bash
# Run tests with accurate coverage - single-threaded for reliability

set -e

cd "$(dirname "$0")/.."

echo "======================================"
echo "Sagaz Test Coverage (Accurate Mode)"
echo "======================================"
echo ""

# Clean up
echo "🧹 Cleaning up old coverage files..."
rm -f .coverage .coverage.* coverage.json

# Exclude slow/problematic tests
EXCLUDE_ARGS=""
if [ "$1" = "--fast" ]; then
    EXCLUDE_ARGS="--ignore=tests/integration --ignore=tests/performance"
    echo "⚡ Running in FAST mode (excluding integration/performance tests)"
else
    echo "🐢 Running ALL tests (including integration/performance)"
fi

echo ""
echo "🧪 Running tests..."
echo ""

# Run single-threaded for accurate coverage
pytest \
  --cov=sagaz \
  --cov-report=json:coverage.json \
  --cov-report=term \
  --cov-report=html:htmlcov \
  $EXCLUDE_ARGS \
  --tb=short \
  -q

echo ""
echo "======================================"
echo "✅ Coverage complete!"
echo "======================================"
echo ""
echo "📊 JSON report: coverage.json"
echo "📈 HTML report: htmlcov/index.html"
echo "🔍 Analyzer: ./scripts/coverage_analyzer.py coverage.json"
