import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mockApi, type CmsPageNavItem } from '../fixtures/mock-api';

const PAGES: CmsPageNavItem[] = [
  { slug: 'article-a', title: 'About <Public> & Forms', nav_order: 1 },
  { slug: 'article-b', title: 'Contact', nav_order: 2 },
];

const DETAILS = {
  'article-a': {
    meta_description: 'Article A metadata',
    body_html: [
      '<p class="lead">Distinctive article A content.</p>',
      '<h1>Authored heading remains H1</h1>',
      '<h2>Services</h2>',
      '<ul><li>Permits</li><li>Inspections</li></ul>',
      '<blockquote><p>Published guidance.</p></blockquote>',
      '<p>Use <code>FORM-001</code> or <a href="https://example.gov.bc.ca">read guidance</a>.</p>',
      '<hr>',
      '<table><thead><tr><th scope="col">State</th></tr></thead><tbody><tr><td>Published</td></tr></tbody></table>',
    ].join(''),
  },
  'article-b': {
    meta_description: 'Article B metadata',
    body_html: '<p>Distinctive article B content.</p>',
  },
};

test.beforeEach(async ({ page }) => {
  await mockApi(page, {
    pages: PAGES,
    cmsDetails: DETAILS,
    cmsRedirects: { 'old-article': 'article-a' },
  });
});

test('renders only the Implementation 1 hero and API-driven lifted card', async ({ page }) => {
  let pageDetailRequests = 0;
  page.on('request', request => {
    if (new URL(request.url()).pathname.endsWith('/pages/article-a')) pageDetailRequests += 1;
  });

  await page.goto('/article-a');

  await expect(page.locator('#cmsPageHero')).toBeVisible();
  await expect(page.locator('#cmsPageHeading')).toHaveText('About <Public> & Forms');
  await expect(page.locator('#cmsBreadcrumbCurrent')).toHaveText('About <Public> & Forms');
  await expect(page.locator('#cmsPageContent.cms-card .cms-body')).toContainText('Distinctive article A content.');
  await expect(page.locator('#cmsPageContent .cms-footnote a')).toHaveText(/Back to forms/);
  await expect(page.locator('.mockup-tabs, .contact-tile, .cms-sidebar-card, .variant')).toHaveCount(0);
  await expect(page.locator('#cmsPageHeading script')).toHaveCount(0);
  expect(pageDetailRequests).toBe(1);
});

test('preserves authored rich-text semantics without table transformation', async ({ page }) => {
  await page.goto('/article-a');

  const body = page.locator('#cmsPageContent .cms-body');
  await expect(body.locator('h1')).toHaveText('Authored heading remains H1');
  await expect(body.locator('h2')).toHaveText('Services');
  await expect(body.locator('li')).toHaveCount(2);
  await expect(body.locator('blockquote')).toContainText('Published guidance.');
  await expect(body.locator('code')).toHaveText('FORM-001');
  await expect(body.locator('table th')).toHaveAttribute('scope', 'col');
  await expect(body.locator('.cms-table-scroll')).toHaveCount(0);
  const tableIsWrapped = await body.locator('table')
    .evaluate(element => element.parentElement?.classList.contains('cms-table-scroll'));
  expect(tableIsWrapped).toBe(false);
});

test('replaces page content and uses SPA navigation for CMS and home links', async ({ page }) => {
  await page.goto('/article-a');
  await page.locator('#cmsNavList a[href="/article-b"]').click();

  await expect(page).toHaveURL(/\/article-b$/);
  await expect(page.locator('#cmsPageHeading')).toHaveText('Contact');
  await expect(page.locator('#cmsPageContent')).toContainText('Distinctive article B content.');
  await expect(page.locator('#cmsPageContent')).not.toContainText('Distinctive article A content.');

  await page.getByRole('link', { name: 'Back to forms' }).click();
  await expect(page.locator('#homeView')).toBeVisible();
});

test('preserves metadata, focus, and legacy redirect behavior', async ({ page }) => {
  await page.goto('/old-article');

  await expect(page).toHaveURL(/\/article-a$/);
  await expect(page.locator('#cmsPageHeading')).toBeFocused();
  await expect(page).toHaveTitle('About <Public> & Forms — BC Government');
  await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', 'Article A metadata');
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', '/article-a');
  await expect(page.locator('meta[property="og:title"]')).toHaveAttribute('content', 'About <Public> & Forms');
});

test('uses the shared 404 view for unknown pages without a stale CMS shell', async ({ page }) => {
  await page.goto('/article-a');
  await page.goto('/unknown-page');

  await expect(page.locator('#notFoundView')).toBeVisible();
  await expect(page.locator('#cmsPageView')).toBeHidden();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex');
});

test('is responsive and accessible in the integrated-browser viewports', async ({ page }) => {
  for (const width of [320, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/article-a');
    await expect(page.locator('#cmsPageHero')).toBeVisible();
    await expect(page.locator('#cmsPageContent')).toBeVisible();
    const widths = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
    }));
    expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  }

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
});

test('applies the shared reduced-motion override', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/article-a');

  const transitionDuration = await page.getByRole('link', { name: 'Back to forms' })
    .evaluate(element => getComputedStyle(element).transitionDuration);
  expect(Number.parseFloat(transitionDuration)).toBeLessThanOrEqual(0.01);
});