import {defineConfig, devices} from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5010',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {...devices['Desktop Chrome']},
    },
    {
      name: 'firefox',
      testMatch: '**/ux.spec.js',
      use: {...devices['Desktop Firefox']},
    },
    {
      name: 'webkit',
      testMatch: '**/ux.spec.js',
      use: {...devices['Desktop Safari']},
    },
    {
      name: 'mobile-chromium',
      use: {...devices['Pixel 7']},
    },
  ],
  webServer: {
    command: 'SECRET_KEY=playwright_test_secret APP_ENV=testing SESSION_STORAGE=memory FLASK_PORT=5010 python app.py',
    url: 'http://127.0.0.1:5010/health',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
