import { test, expect } from '@playwright/test';
import { mockApi } from '../fixtures/mock-api';

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mockApi(page, {
    pages: [{ slug: 'faq', title: 'FAQ', nav_order: 1 }],
    cmsDetails: {
      faq: {
        body_html: '<a href="#last">Scroll below</a>'
          + '<h1>First</h1><br>'.repeat(24)
          + '<h2 id="last">Last section</h2>',
      },
    },
  });
});

test('fragment click scrolls without refetching the CMS page', async ({ page }) => {
  let detailRequests = 0;
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/public/v1/pages/faq') detailRequests += 1;
  });

  await page.goto('/faq');
  await expect(page.locator('#last')).toBeAttached();
  expect(detailRequests).toBe(1);

  await page.getByRole('link', { name: 'Scroll below' }).click();
  await expect(page).toHaveURL(/\/faq#last$/);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  await expect(page.locator('#last')).toBeInViewport();
  expect(detailRequests).toBe(1);
});

test('direct fragment URL scrolls after the CMS page loads', async ({ page }) => {
  await page.goto('/faq#last');

  await expect(page.locator('#last')).toBeAttached();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  await expect(page.locator('#last')).toBeInViewport();
});