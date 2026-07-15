import {defineConfig} from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['tests/js/**/*.test.js'],
    clearMocks: true,
    restoreMocks: true,
    coverage: {
      enabled: false,
    },
  },
});
