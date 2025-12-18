#!/bin/bash
# =============================================================================
# Beatify - Run Tests for Changed Files Only
# =============================================================================
# Purpose: Fast feedback by running only tests affected by recent changes
# Usage: ./scripts/test-changed.sh
#
# Detects changes since last commit and runs related tests.
# Falls back to full test suite if detection fails.
# =============================================================================

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 Beatify - Selective Test Runner"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Get changed files
CHANGED_FILES=$(git diff --name-only HEAD~1 2>/dev/null || git diff --name-only HEAD 2>/dev/null || echo "")

if [ -z "$CHANGED_FILES" ]; then
    echo "No git changes detected (or not in a git repo)"
    echo "Running full test suite..."
    pytest tests/ -v --tb=short
    exit $?
fi

echo "Changed files:"
echo "$CHANGED_FILES" | sed 's/^/  - /'
echo ""

# Determine which tests to run based on changed files
RUN_UNIT=false
RUN_INTEGRATION=false
RUN_E2E=false

if echo "$CHANGED_FILES" | grep -qE "custom_components/beatify/(game|scoring|playlist)"; then
    echo "📦 Game logic changed → Running unit tests"
    RUN_UNIT=true
fi

if echo "$CHANGED_FILES" | grep -qE "custom_components/beatify/(server|services|config_flow)"; then
    echo "🔌 Server/services changed → Running integration tests"
    RUN_INTEGRATION=true
fi

if echo "$CHANGED_FILES" | grep -qE "custom_components/beatify/www/"; then
    echo "🌐 Frontend changed → Running E2E tests"
    RUN_E2E=true
fi

if echo "$CHANGED_FILES" | grep -qE "tests/"; then
    echo "🧪 Test files changed → Running all tests"
    RUN_UNIT=true
    RUN_INTEGRATION=true
    RUN_E2E=true
fi

# If no specific tests identified, run all
if [ "$RUN_UNIT" = false ] && [ "$RUN_INTEGRATION" = false ] && [ "$RUN_E2E" = false ]; then
    echo "No specific test category identified → Running all tests"
    pytest tests/ -v --tb=short
    exit $?
fi

echo ""
echo "Running selected tests..."
echo "────────────────────────────────────────────────────────────────────────────"

EXIT_CODE=0

if [ "$RUN_UNIT" = true ]; then
    echo "🧪 Unit tests..."
    pytest tests/unit/ -v --tb=short || EXIT_CODE=1
fi

if [ "$RUN_INTEGRATION" = true ]; then
    echo "🔌 Integration tests..."
    pytest tests/integration/ -v --tb=short || EXIT_CODE=1
fi

if [ "$RUN_E2E" = true ]; then
    echo "🌐 E2E tests..."
    pytest tests/e2e/ -v --tb=short || EXIT_CODE=1
fi

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Selected tests passed"
else
    echo "❌ Some tests failed"
fi

exit $EXIT_CODE
