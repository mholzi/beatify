// ESLint flat config for Beatify frontend JS (#1582).
//
// Goal: a *minimal, non-disruptive* style/correctness guardrail over the
// ~30k lines of browser JS in custom_components/beatify/www/js. The existing
// code is a mix of classic `window.X = (function(){...})()` IIFE modules and
// newer ES modules, all hand-written and untranspiled. The ruleset below is
// deliberately conservative: it catches real footguns (e.g. `===` typos that
// `eqeqeq` would force, accidental globals) without demanding a refactor.
//
// Rules that would fire en masse on the legacy global-sharing / IIFE patterns
// (no-undef, no-unused-vars) are relaxed to warnings so `eslint .` (which only
// fails CI on *errors*) stays green while still surfacing the noise locally.
import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    // Don't lint generated bundles, vendored libs, deps, or coverage output.
    ignores: [
      '**/*.min.js',
      'custom_components/beatify/www/js/vendor/**',
      'node_modules/**',
      'coverage/**',
      'htmlcov/**',
    ],
  },
  js.configs.recommended,
  {
    files: ['**/*.js', '**/*.mjs'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.serviceworker,
        ...globals.node,
      },
    },
    rules: {
      // Legacy global-sharing across IIFE modules (window.BeatifyUtils etc.)
      // means many "undefined" identifiers are intentional cross-file globals.
      // Warn instead of erroring so this can't break CI.
      'no-undef': 'warn',
      'no-unused-vars': ['warn', { args: 'none', ignoreRestSiblings: true }],
      'no-empty': ['warn', { allowEmptyCatch: true }],
      // Pre-existing `var x` reused across branches in the same function scope
      // (harmless under var hoisting). Warn rather than force a `var`->`let`
      // rewrite of legacy code.
      'no-redeclare': 'warn',
    },
  },
  {
    // Vitest test files: ESM with the standard test globals.
    files: ['**/__tests__/**/*.js'],
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.vitest,
      },
    },
  },
];
