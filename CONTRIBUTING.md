# Contributing to Beatify

Thanks for your interest in improving Beatify! Whether you're fixing a bug,
adding a translation, submitting a playlist, or building a feature — this guide
gets you from clone to pull request.

Beatify is a [Home Assistant](https://www.home-assistant.io/) custom
integration. The backend is Python (running inside Home Assistant) and the
frontend is vanilla JS/CSS served by the integration's own web views. There is
no separate web server or build server — everything lives in this repo.

---

## Table of contents

- [Ways to contribute](#ways-to-contribute)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Running tests](#running-tests)
- [Linting & formatting](#linting--formatting)
- [Building frontend assets](#building-frontend-assets)
- [Coding conventions](#coding-conventions)
- [Translations](#translations)
- [Submitting a pull request](#submitting-a-pull-request)
- [PR checklist](#pr-checklist)

---

## Ways to contribute

- **Bug fixes** — pick up an [open issue](https://github.com/mholzi/beatify/issues),
  ideally a [good first issue](https://github.com/mholzi/beatify/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
- **Features** — open an issue first to discuss the idea before investing in code.
- **Translations** — add or correct a language (see [Translations](#translations)).
- **Playlists** — request or submit a playlist through the Admin UI; you don't
  need to touch code for that.

---

## Repository layout

```
custom_components/beatify/      The Home Assistant integration
├── www/                        Frontend assets served to browsers
│   ├── js/                     Readable JS sources (edit these)
│   │   ├── *.js                Per-page scripts (admin, dashboard, ...)
│   │   ├── *.min.js            Minified bundles served to clients (generated)
│   │   └── __tests__/          Frontend unit tests (vitest)
│   ├── css/                    Stylesheets (+ generated *.min.css)
│   ├── *.html                  Page templates (cache-busters templated server-side)
│   └── sw.js                   Service worker
├── translations/               HA config-flow strings (de/en/es/fr/nl)
└── manifest.json               Integration metadata + version

tests/
├── unit/                       Python unit tests (pytest)
└── integration/               Python integration tests (pytest)

scripts/build.mjs               Frontend build (esbuild) — single source of truth
.github/workflows/              CI: test.yml (lint/test/build) + validate.yml (HACS/hassfest)
```

---

## Prerequisites

- **Python 3.12 or 3.13** (CI runs both; 3.13 is the primary target)
- **Node.js 22+** (only needed if you touch frontend assets)
- **git**

You do **not** need a running Home Assistant instance to run the test suite —
the tests stub out the HA runtime.

---

## Setup

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-user>/beatify.git
cd beatify

# 2. (Recommended) create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install Python test dependencies
pip install -r requirements_test.txt
pip install ruff==0.15.7         # linter/formatter (matches CI)

# 4. If you'll touch frontend assets, install the JS toolchain
npm install
```

---

## Running tests

### Python (pytest)

```bash
# All unit tests
pytest tests/unit/ -v

# All tests with coverage (mirrors CI)
pytest tests/unit/ tests/integration/ \
  --cov=custom_components/beatify --cov-report=term-missing
```

`pytest.ini` already sets `pythonpath = .` and `asyncio_mode = auto`, so no
extra env setup is needed. CI currently enforces a baseline of
`--cov-fail-under=25`; please don't lower coverage.

### Frontend (vitest)

```bash
npm test            # run once
npm run test:watch  # watch mode
```

Frontend tests live under `custom_components/beatify/www/js/__tests__/`.

---

## Linting & formatting

Python code must pass `ruff` (both lint and format checks run in CI):

```bash
ruff check .          # lint
ruff format --check . # formatting (drop --check to auto-format)
```

CI also runs a **flaky-test burn-in** (10 iterations) on PRs to `main`, so make
sure your tests are deterministic.

---

## Building frontend assets

**Never hand-edit a `.min.js` file.** Edit the readable `.js` source under
`custom_components/beatify/www/js/`, then rebuild the minified bundle:

```bash
npm run build         # regenerate all .min.js bundles from source
npm run build:check   # verify committed bundles match source (this is what CI runs)
```

The build (`scripts/build.mjs`, esbuild) is the single source of truth for the
served bundles. CI's **frontend build check** fails the PR if any committed
`.min.js` has drifted from its `.js` source — this guards against the class of
bug where a source edit never reaches the bundle the browser actually loads.

Notes:
- HTML cache-busters (`?v={{ASSET_VER}}`) and the service worker's
  `CACHE_VERSION` are templated by the integration at serve time — you do **not**
  edit `?v=` values or `CACHE_VERSION` by hand. A CI guard
  (`tests/unit/test_asset_cachebuster.py::TestNoHardcodedCacheBusters`) fails the
  PR if a hardcoded literal is ever pasted back into a template, so the
  rc8→rc14-style drift can't regress.
- When you change a `.js`, commit both the source **and** the regenerated
  `.min.js` in the same PR.

---

## Coding conventions

- **Python:** follow `ruff`'s defaults (lint + format). Keep changes focused;
  match the style of the surrounding code.
- **Frontend:** vanilla JS, no framework. Edit `.js` sources, never `.min.js`.
- **UI/visual changes:** read [`DESIGN.md`](DESIGN.md) first. Fonts, colors,
  spacing, and aesthetic direction are defined there — don't deviate without
  discussing it in the issue.
- **Scope:** make the smallest change that solves the problem. Don't refactor
  unrelated code or expand scope inside a bug-fix PR.
- **Tests:** add or update tests for any behavior you change.

---

## Translations

Config-flow / setup strings live in `custom_components/beatify/translations/`
(`de`, `en`, `es`, `fr`, `nl`). The in-app UI strings live in
`custom_components/beatify/www/i18n/<locale>.json` (one file per locale:
`en.json`, `de.json`, `es.json`, `fr.json`, `nl.json`). `en.json` is the
canonical source — add new keys there first, then mirror them into every other
locale, keeping the exact same key structure and nesting across all languages.
No build step is required for these JSON files; they are loaded at runtime.

---

## Submitting a pull request

1. Create a topic branch off `main`:
   ```bash
   git checkout -b fix/short-description
   ```
2. Make your change, add tests, and run the relevant checks locally
   (see the [PR checklist](#pr-checklist)).
3. Commit with a clear message and push to your fork.
4. Open a PR against `mholzi/beatify`'s `main` branch. Describe **what** changed
   and **why**, and link the issue it closes (`Closes #NNN`).
5. CI (lint, tests, frontend build check, HACS/hassfest validation) must pass.

---

## PR checklist

Before opening your PR, confirm:

- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `pytest tests/unit/ tests/integration/` passes (and you added/updated tests)
- [ ] If you touched frontend `.js`: `npm test` passes and `npm run build:check`
      is clean (regenerated `.min.js` committed)
- [ ] If you touched the UI: changes follow [`DESIGN.md`](DESIGN.md)
- [ ] Translations updated/kept in sync if you changed user-facing strings
- [ ] PR description explains the change and links the related issue
- [ ] Change is focused — no unrelated refactors

Thanks for contributing! 🎉
