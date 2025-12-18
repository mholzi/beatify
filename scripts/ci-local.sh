#!/bin/bash
# =============================================================================
# Beatify - Local CI Mirror
# =============================================================================
# Purpose: Run the same checks locally that CI runs
# Usage: ./scripts/ci-local.sh
#
# This mirrors the GitHub Actions pipeline for debugging CI failures locally.
# =============================================================================

set -e  # Exit on first error

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Beatify - Local CI Pipeline"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Stage 1: Lint
echo "📋 STAGE 1: Lint"
echo "────────────────────────────────────────────────────────────────────────────"
echo "Running ruff linter..."
ruff check . || { echo "❌ Lint failed"; exit 1; }
echo "Running ruff formatter check..."
ruff format --check . || { echo "❌ Format check failed"; exit 1; }
echo "✅ Lint passed"
echo ""

# Stage 2: Tests
echo "🧪 STAGE 2: Tests"
echo "────────────────────────────────────────────────────────────────────────────"
echo "Running unit tests..."
pytest tests/unit/ -v --tb=short || { echo "❌ Unit tests failed"; exit 1; }
echo "Running integration tests..."
pytest tests/integration/ -v --tb=short || { echo "❌ Integration tests failed"; exit 1; }
echo "✅ All tests passed"
echo ""

# Stage 3: Coverage
echo "📊 STAGE 3: Coverage"
echo "────────────────────────────────────────────────────────────────────────────"
pytest tests/ --cov=custom_components/beatify --cov-report=term-missing --cov-fail-under=80 || {
    echo "❌ Coverage below 80%"
    exit 1
}
echo "✅ Coverage check passed"
echo ""

# Stage 4: Burn-in (reduced iterations for local)
echo "🔥 STAGE 4: Burn-in (3 iterations)"
echo "────────────────────────────────────────────────────────────────────────────"
for i in {1..3}; do
    echo "🔥 Burn-in iteration $i/3"
    pytest tests/ -v --tb=short -q || {
        echo "❌ FLAKY TEST DETECTED on iteration $i"
        exit 1
    }
done
echo "✅ Burn-in passed (3/3 iterations)"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 Local CI Pipeline PASSED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
