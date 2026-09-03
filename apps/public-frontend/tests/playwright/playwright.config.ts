import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for the public-frontend E2E suite (FEAT-0028 US-004).
 *
 * Base URL is configurable via PLAYWRIGHT_BASE_URL; defaults to the local
 * deployment host. The US-004 specs mock the public API with page.route so
 * they are deterministic and do NOT depend on FEAT-0029 exposing the `url`
 * field. The smoke spec runs against the live deployment with no mocking.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://forms-public.localhost/';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 7_500 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
