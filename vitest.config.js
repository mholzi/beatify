import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['custom_components/beatify/www/js/__tests__/**/*.test.js'],
    environment: 'node',
  },
});
