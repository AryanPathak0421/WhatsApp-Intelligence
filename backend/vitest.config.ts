import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    globalSetup: ['tests/global-setup.ts'],
    setupFiles: ['tests/setup-env.ts'],
    testTimeout: 120_000,
    hookTimeout: 120_000,
    fileParallelism: false, // tests share one database
  },
});
