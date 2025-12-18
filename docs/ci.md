# Beatify CI/CD Pipeline

This document describes the CI/CD pipeline for Beatify, including how to run tests locally, debug CI failures, and maintain pipeline health.

## Pipeline Overview

The Beatify CI pipeline runs on **GitHub Actions** and consists of four stages:

```
┌─────────┐     ┌─────────┐     ┌──────────┐
│  Lint   │ ──► │  Test   │ ──► │ Burn-in  │
│  <1min  │     │  <5min  │     │  <15min  │
└─────────┘     └─────────┘     └──────────┘
```

| Stage | Purpose | Runs On |
|-------|---------|---------|
| **Lint** | Code quality (ruff) | Every push/PR |
| **Test** | Unit + integration tests with coverage | Every push/PR |
| **Burn-in** | Flaky test detection (10 iterations) | PRs to main, weekly |

## Running Locally

### Quick Test Run

```bash
# Install dependencies
pip install -r requirements_test.txt

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=custom_components/beatify --cov-report=html
```

### Mirror CI Locally

Run the exact same checks that CI runs:

```bash
./scripts/ci-local.sh
```

This runs:
1. Lint (ruff check + format)
2. Unit tests
3. Integration tests
4. Coverage check (≥80%)
5. Burn-in (3 iterations)

### Selective Testing

Run only tests affected by your changes:

```bash
./scripts/test-changed.sh
```

### Burn-In Testing

Detect flaky tests by running multiple iterations:

```bash
# Quick check (3 iterations)
./scripts/burn-in.sh 3

# Standard (10 iterations - same as CI)
./scripts/burn-in.sh 10

# Thorough (100 iterations)
./scripts/burn-in.sh 100
```

## Pipeline Stages

### Stage 1: Lint

**Checks:**
- `ruff check .` - Linting errors
- `ruff format --check .` - Formatting consistency

**Fix lint errors:**
```bash
# Auto-fix linting issues
ruff check . --fix

# Auto-format code
ruff format .
```

### Stage 2: Test

**Checks:**
- Unit tests (`tests/unit/`)
- Integration tests (`tests/integration/`)
- Coverage ≥80%

**Test markers:**
```bash
# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration

# E2E tests only (requires Playwright)
pytest -m e2e
```

**Coverage report:**
```bash
pytest tests/ --cov=custom_components/beatify --cov-report=html
open htmlcov/index.html
```

### Stage 3: Burn-in

**Purpose:** Detect non-deterministic (flaky) tests

**When it runs:**
- PRs targeting `main` branch
- Weekly on Monday at 6 AM UTC

**How it works:**
1. Runs all tests 10 times
2. If ANY iteration fails → pipeline fails
3. Tests must pass 10/10 to be considered stable

**If burn-in fails:**
1. Check the failed iteration output
2. Look for race conditions, timing issues, or shared state
3. Apply fixes from `test-healing-patterns.md`
4. Re-run burn-in locally: `./scripts/burn-in.sh 10`

## Debugging CI Failures

### Download Artifacts

When tests fail in CI, artifacts are uploaded:
1. Go to the failed workflow run
2. Scroll to "Artifacts" section
3. Download `coverage-report` or `burn-in-failures`

### Common Issues

**Issue:** Lint fails
```bash
# Fix: Run auto-fix locally
ruff check . --fix
ruff format .
git commit -am "style: fix linting errors"
```

**Issue:** Coverage below 80%
```bash
# Check which lines are uncovered
pytest tests/ --cov=custom_components/beatify --cov-report=term-missing

# Add tests for uncovered code
```

**Issue:** Burn-in detects flaky test
```bash
# Run locally to reproduce
./scripts/burn-in.sh 10

# Check for:
# - time.sleep() or hardcoded delays
# - Shared state between tests
# - Race conditions in async code
# - External service dependencies
```

**Issue:** Import errors
```bash
# Ensure PYTHONPATH includes project root
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

## Workflow File

The CI configuration is in `.github/workflows/test.yml`.

**Triggers:**
- `push` to `main` or `develop`
- `pull_request` to `main` or `develop`
- Weekly schedule (Monday 6 AM UTC)

**Concurrency:**
- Cancels in-progress runs when new commits are pushed
- Prevents resource waste on rapid commits

## Performance Targets

| Stage | Target | Actual |
|-------|--------|--------|
| Lint | <1 min | ~30s |
| Test | <5 min | ~2-3 min |
| Burn-in | <15 min | ~10-12 min |
| **Total** | <20 min | ~15 min |

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `PYTHON_VERSION` | Python version for CI | 3.11 |

## Future Enhancements

### Home Assistant Validation (Optional)

Uncomment the `ha-validation` job in `test.yml` to enable:
- HACS validation
- hassfest validation

Requires HA dev environment setup.

### Codecov Integration

Coverage is uploaded to Codecov when configured:
1. Add repository to Codecov
2. Add `CODECOV_TOKEN` secret (for private repos)

---

## Quick Reference

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=custom_components/beatify

# Mirror CI locally
./scripts/ci-local.sh

# Burn-in test (detect flaky)
./scripts/burn-in.sh 10

# Selective testing
./scripts/test-changed.sh

# Fix lint errors
ruff check . --fix && ruff format .
```

---

**Generated by:** BMad TEA Agent (Murat)
**Date:** 2025-12-18
