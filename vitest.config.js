import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['custom_components/beatify/www/js/__tests__/**/*.test.js'],
    environment: 'node',
    coverage: {
      // Coverage is opt-in via `npm run test:coverage` (and CI). The gate below
      // is a *floor* set well under the currently-measured numbers (#1582) so it
      // can only catch a regression, never flake CI on a small delta.
      provider: 'v8',
      reporter: ['text-summary', 'html'],
      include: ['custom_components/beatify/www/js/**/*.js'],
      exclude: [
        '**/__tests__/**',
        'custom_components/beatify/www/js/vendor/**',
        '**/*.min.js',
      ],
      thresholds: {
        // Measured 2026-06-25: lines/statements ~17.8%, functions ~29.4%,
        // branches ~66.1%. Floors sit a few points below to absorb v8 jitter.
        lines: 15,
        statements: 15,
        functions: 25,
        branches: 55,
      },
    },
  },
});
