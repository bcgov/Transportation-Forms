import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mockApi, LINK_FORM } from '../fixtures/mock-api';

/**
 * WCAG 2.1 AA checks (US-004 AC7 for the navbar; general regression guard).
 * Uses mocked data so the DOM is deterministic across environments.
 */

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

async function scan(page) {
  return new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
}

test('home view has no WCAG A/AA violations', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#resultsRegion')).toBeVisible();
  const results = await scan(page);
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
});

test('active CMS page + navbar have no WCAG A/AA violations', async ({ page }) => {
  await page.goto('/about');
  await expect(page.locator('#cmsNavList a.active')).toHaveCount(1);
  const results = await scan(page);
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
});

test('link-source detail view has no WCAG A/AA violations', async ({ page }) => {
  await page.goto(`/forms/${LINK_FORM.form_number}`);
  await expect(page.locator('#detailContent a.btn-download')).toHaveText(/Form Link/);
  const results = await scan(page);
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
});
