import { test, expect } from '@playwright/test';
import { mockApi } from '../fixtures/mock-api';

/**
 * US-004 Defect A — the CMS navbar must highlight the current page, never the
 * previously visited link. Covers AC1-AC8.
 */

const NAV = '#cmsNav';
const NAV_LINK = '#cmsNavList a';

async function navLink(page, slug: string) {
  return page.locator(`#cmsNavList a[href="/${slug}"]`);
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test('AC1/AC5 - clicking a nav link marks the current page, clearing the previous one', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator(NAV)).toBeVisible();
  await expect(page.locator(NAV_LINK)).toHaveCount(2);

  const about = await navLink(page, 'about');
  const contact = await navLink(page, 'contact');

  await about.click();
  await expect(page.locator('#cmsPageView')).toBeVisible();
  await expect(about).toHaveClass(/active/);
  await expect(about).toHaveAttribute('aria-current', 'page');
  await expect(contact).not.toHaveClass(/active/);
  await expect(contact).not.toHaveAttribute('aria-current', 'page');

  // Navigate to the other CMS page: the previously visited link must clear.
  await contact.click();
  await expect(contact).toHaveClass(/active/);
  await expect(contact).toHaveAttribute('aria-current', 'page');
  await expect(about).not.toHaveClass(/active/);
  await expect(about).not.toHaveAttribute('aria-current', 'page');
});

test('AC2/AC7 - exactly one link is active and visual/aria state agree', async ({ page }) => {
  await page.goto('/about');
  await expect(page.locator(NAV)).toBeVisible();

  await expect(page.locator('#cmsNavList a.active')).toHaveCount(1);
  await expect(page.locator('#cmsNavList a[aria-current="page"]')).toHaveCount(1);

  const active = page.locator('#cmsNavList a.active');
  await expect(active).toHaveAttribute('href', '/about');
  await expect(active).toHaveAttribute('aria-current', 'page');
});

test('AC3 - deep link / reload marks the matching link on first paint', async ({ page }) => {
  await page.goto('/contact');
  const contact = await navLink(page, 'contact');
  await expect(contact).toHaveClass(/active/);

  await page.reload();
  await expect(await navLink(page, 'contact')).toHaveClass(/active/);
});

test('AC4 - back/forward updates the active link to the shown page', async ({ page }) => {
  await page.goto('/');
  await (await navLink(page, 'about')).click();
  await (await navLink(page, 'contact')).click();

  await page.goBack();
  await expect(await navLink(page, 'about')).toHaveClass(/active/);
  await expect(await navLink(page, 'contact')).not.toHaveClass(/active/);

  await page.goForward();
  await expect(await navLink(page, 'contact')).toHaveClass(/active/);
  await expect(await navLink(page, 'about')).not.toHaveClass(/active/);
});

test('AC6 - non-navbar views (home, detail, 404) leave no link active', async ({ page }) => {
  // Start on a CMS page so an active link exists, then leave the navbar pages.
  await page.goto('/about');
  await expect(await navLink(page, 'about')).toHaveClass(/active/);

  // Home
  await page.locator('#siteHeader a[href="/"]').first().click();
  await expect(page.locator('#homeView')).toBeVisible();
  await expect(page.locator('#cmsNavList a.active')).toHaveCount(0);
  await expect(page.locator('#cmsNavList a[aria-current="page"]')).toHaveCount(0);

  // Form detail
  await page.goto('/forms/TRAN0100');
  await expect(page.locator('#detailView')).toBeVisible();
  await expect(page.locator('#cmsNavList a.active')).toHaveCount(0);

  // 404 (unknown form)
  await page.goto('/forms/DOES-NOT-EXIST');
  await expect(page.locator('#cmsNavList a.active')).toHaveCount(0);
  await expect(page.locator('#cmsNavList a[aria-current="page"]')).toHaveCount(0);
});
