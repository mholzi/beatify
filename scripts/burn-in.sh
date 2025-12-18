#!/bin/bash
# =============================================================================
# Beatify - Burn-In Test Script
# =============================================================================
# Purpose: Detect flaky/non-deterministic tests by running multiple iterations
# Usage: ./scripts/burn-in.sh [iterations]
#
# Default: 10 iterations
# Quick check: ./scripts/burn-in.sh 3
# Thorough: ./scripts/burn-in.sh 100
# =============================================================================

set -e

ITERATIONS=${1:-10}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔥 Beatify - Burn-In Test Loop"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Iterations: $ITERATIONS"
echo "Purpose: Detect non-deterministic (flaky) tests"
echo ""
echo "A test is considered STABLE if it passes $ITERATIONS/$ITERATIONS times."
echo "ANY failure indicates flakiness that must be fixed."
echo ""

FAILURES=0
START_TIME=$(date +%s)

for i in $(seq 1 $ITERATIONS); do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔥 Burn-in iteration $i/$ITERATIONS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if pytest tests/ -v --tb=short -q; then
        echo "✅ Iteration $i PASSED"
    else
        echo "❌ Iteration $i FAILED"
        FAILURES=$((FAILURES + 1))
        echo ""
        echo "⚠️  FLAKY TEST DETECTED!"
        echo "    Failure occurred on iteration $i of $ITERATIONS"
        echo "    Tests must pass 100% of iterations to be considered stable."
        echo ""
        echo "Next steps:"
        echo "  1. Review the failing test output above"
        echo "  2. Check for race conditions, timing issues, or shared state"
        echo "  3. Apply patterns from test-healing-patterns.md"
        echo "  4. Re-run burn-in after fixing"
        exit 1
    fi
    echo ""
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 BURN-IN COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Results:"
echo "  ✅ Passed: $ITERATIONS/$ITERATIONS iterations"
echo "  ❌ Failed: $FAILURES"
echo "  ⏱️  Duration: ${DURATION}s"
echo ""
echo "Conclusion: Tests are STABLE (no flakiness detected)"
echo ""
