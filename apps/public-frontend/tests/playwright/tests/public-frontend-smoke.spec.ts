import { test, expect } from '@playwright/test';

/**
 * Broad public-frontend smoke suite. Runs against the LIVE deployment with no
 * API mocking to verify that every major element renders and works end-to-end
 * with real data. Assertions are tolerant of catalogue size (results OR empty
 * state) so the suite is stable across environments.
 *
 * NOTE: link-source "Form Link" behaviour is verified deterministically in
 * us-004-form-link.spec.ts (mocked), because the live API does not yet expose
 * the `url` field (that is FEAT-0029).
 */

test('home: header, hero, and search card render', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#siteHeader')).toBeVisible();
  await expect(page.locator('#siteHeader img.bcgov-header-logo')).toHaveAttribute(
    'alt',
    'BC Ministry of Transportation and Transit Public Forms',
  );
  await expect(page.locator('#siteHeader')).toContainText('Public Forms');
  await expect(page.locator('.hero-band')).toBeVisible();
  await expect(page.locator('#searchInput')).toBeVisible();
  await expect(page.locator('#filterBA')).toBeVisible();
  await expect(page.locator('#sortField')).toBeVisible();
  await expect(page.locator('#sortOrder')).toBeVisible();
});

test('home: results toolbar, results region, and view toggle work', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#resultsRegion')).toBeVisible();
  await expect(page.locator('.results-count-badge')).toBeVisible();

  // Either results or the empty state must be present.
  const cards = page.locator('article.form-card-v2');
  const empty = page.locator('#emptyState');
  await expect(cards.first().or(empty)).toBeVisible();

  // Presentational list/grid toggle must not throw and must switch layout class.
  await page.locator('#viewGridBtn').click();
  await expect(page.locator('#resultsList')).toHaveClass(/is-grid/);
  await expect(page.locator('#viewGridBtn')).toHaveAttribute('aria-pressed', 'true');
  await page.locator('#viewListBtn').click();
  await expect(page.locator('#resultsList')).not.toHaveClass(/is-grid/);
});

test('home: search input filters the catalogue', async ({ page }) => {
  await page.goto('/');
  await page.locator('#searchInput').fill('zzzzzznotarealform');
  // Debounced search should resolve to the empty state.
  await expect(page.locator('#emptyState')).toBeVisible();
  await page.locator('#clearFiltersBtn').click();
  await expect(page.locator('#searchInput')).toHaveValue('');
});

test('detail: navigating from a card opens the detail view and back returns home', async ({ page }) => {
  await page.goto('/');
  const firstNum = page.locator('article.form-card-v2 .form-num-link').first();
  const hasCards = await firstNum.count();
  test.skip(hasCards === 0, 'No forms in the live catalogue to open.');

  await firstNum.click();
  await expect(page.locator('#detailView')).toBeVisible();
  await expect(page.locator('#detailContent')).toBeVisible();

  await page.locator('#backLink').click();
  await expect(page.locator('#homeView')).toBeVisible();
});

test('404: an unknown form number renders a not-found state', async ({ page }) => {
  await page.goto('/forms/__definitely_not_a_real_form__');
  await expect(page.locator('#detailContent, #notFoundView')).toBeVisible();
  await expect(page.locator('body')).toContainText(/not be found|not found/i);
});

test('a11y plumbing: skip link is the first focusable element', async ({ page }) => {
  await page.goto('/');
  await page.keyboard.press('Tab');
  const active = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    return { text: el?.textContent?.trim() ?? '', href: el?.getAttribute('href') ?? '' };
  });
  expect(active.text).toMatch(/skip to main content/i);
  expect(active.href).toBe('#mainContent');
});

test('no severe console errors on home', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (err) => errors.push(String(err)));
  await page.goto('/');
  await expect(page.locator('#resultsRegion')).toBeVisible();
  // Ignore benign favicon / network-abort noise; fail on script errors.
  const severe = errors.filter(e => !/favicon|ERR_ABORTED|net::/i.test(e));
  expect(severe, severe.join('\n')).toHaveLength(0);
});
