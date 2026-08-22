import {defineConfig, devices} from '@playwright/test';

export default defineConfig({
  testDir: './tests/visual',
  fullyParallel: false,
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  snapshotPathTemplate: '{testDir}/{testFilePath}-snapshots/{arg}-{projectName}{ext}',
  use: {
    baseURL: 'http://127.0.0.1:5010',
    reducedMotion: 'reduce',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {...devices['Desktop Chrome']},
    },
  ],
  webServer: {
    command: 'SECRET_KEY=visual_test_secret APP_ENV=testing SESSION_STORAGE=memory FLASK_PORT=5010 python app.py',
    url: 'http://127.0.0.1:5010/health',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
