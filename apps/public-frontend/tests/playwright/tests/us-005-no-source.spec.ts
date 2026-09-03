import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mockApi } from '../fixtures/mock-api';

/**
 * US-005 — a form with neither a valid http(s) `url` nor positive file evidence
 * (a non-empty `file_type` with `form_source` != "URL") is "no source": the
 * file-type pill and the action control are hidden on the home cards (list and
 * grid) and on the detail view. Downloadable (US-003) and link-source (US-004)
 * affordances are preserved. Deterministic; the public API is mocked.
 */

// A downloadable file form (form_source "Download", non-empty file_type, no url).
const DOWNLOAD_FORM = {
  form_number: 'TF-DL-001',
  title: 'Downloadable Permit Form',
  description: 'A standard downloadable PDF form.',
  business_area: 'Permits',
  keywords: ['permit'],
  file_type: 'pdf',
  form_source: 'Download',
  effective_date: '2025-03-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
  url: null as string | null,
};

// A link-source form (form_source "URL", valid https url, no file).
const LINK_FORM = {
  form_number: 'TF-LINK-001',
  title: 'External Link Form',
  description: 'A form that links to an external destination.',
  business_area: 'Compliance',
  keywords: ['inspection'],
  file_type: null as string | null,
  form_source: 'URL',
  effective_date: '2025-01-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
  url: 'https://www2.gov.bc.ca/gov/content/transportation',
};

// A "no source" form: no valid url, no positive file evidence.
const NOSRC_FORM = {
  form_number: 'TF-NONE-001',
  title: 'Placeholder Form (coming soon)',
  description: 'A published form that has neither a file nor a link yet.',
  business_area: 'Licensing',
  keywords: ['placeholder'],
  file_type: null as string | null,
  form_source: null as string | null,
  effective_date: '2025-02-01T00:00:00Z',
  updated_at: '2026-04-01T00:00:00Z',
  url: null as string | null,
};

// "URL"-typed form with an unsafe javascript: url and no file -> no source (E13).
const UNSAFE_NOSRC_FORM = {
  form_number: 'TF-UNSAFE-001',
  title: 'Unsafe Link Form',
  description: 'A URL-typed form whose url uses a rejected scheme.',
  business_area: 'Licensing',
  keywords: ['test'],
  file_type: null as string | null,
  form_source: 'URL',
  effective_date: '2025-02-01T00:00:00Z',
  updated_at: '2026-04-02T00:00:00Z',
  url: 'javascript:alert(1)',
};

// "URL"-typed form with a relative (non-http) url and no file -> no source (E13).
const RELATIVE_NOSRC_FORM = {
  form_number: 'TF-REL-001',
  title: 'Relative Link Form',
  description: 'A URL-typed form whose url is a relative value.',
  business_area: 'Licensing',
  keywords: ['test'],
  file_type: null as string | null,
  form_source: 'URL',
  effective_date: '2025-02-01T00:00:00Z',
  updated_at: '2026-04-03T00:00:00Z',
  url: '/relative/path',
};

// "Download"-typed form with a lost/never-attached file (no file_type) -> no source (E12).
const DL_NOFILE_FORM = {
  form_number: 'TF-DLNOFILE-001',
  title: 'Download Form With Lost File',
  description: 'A download-typed form whose file is missing.',
  business_area: 'Permits',
  keywords: ['permit'],
  file_type: null as string | null,
  form_source: 'Download',
  effective_date: '2025-02-01T00:00:00Z',
  updated_at: '2026-04-04T00:00:00Z',
  url: null as string | null,
};

// Legacy row (form_source null) with lost file (no file_type) -> no source.
const NULL_NOFILE_FORM = {
  form_number: 'TF-NULLNOFILE-001',
  title: 'Legacy Form With Lost File',
  description: 'A legacy row whose file is missing.',
  business_area: 'Permits',
  keywords: ['permit'],
  file_type: null as string | null,
  form_source: null as string | null,
  effective_date: '2025-02-01T00:00:00Z',
  updated_at: '2026-04-05T00:00:00Z',
  url: null as string | null,
};

// Legacy row (form_source null) that still carries a non-empty file_type -> file-source (AC15/E11).
const LEGACY_FILE_FORM = {
  form_number: 'TF-LEGACY-001',
  title: 'Legacy Downloadable Form',
  description: 'A legacy row that still carries file metadata.',
  business_area: 'Permits',
  keywords: ['permit'],
  file_type: 'docx',
  form_source: null as string | null,
  effective_date: '2025-02-01T00:00:00Z',
  updated_at: '2026-04-06T00:00:00Z',
  url: null as string | null,
};

const cardFor = (page, num: string) =>
  page.locator(`article.form-card-v2:has(.form-num-link:text-is("${num}"))`);

/* ─── Home forms list (cards) ────────────────────────────────────────────── */

test.describe('Home cards — no-source hides pill + action', () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, { forms: [DOWNLOAD_FORM, LINK_FORM, NOSRC_FORM] });
  });

  test('TC1.1/TC1.2/TC1.3 - no-source card has no pill and no action (list + grid)', async ({ page }) => {
    await page.goto('/');
    const card = cardFor(page, NOSRC_FORM.form_number);
    await expect(card).toBeVisible();

    // TC1.1/TC1.3 — no file-type pill at all (not even a neutral/link pill).
    await expect(card.locator('.file-type-pill:not(.file-date)')).toHaveCount(0);
    // TC1.2 — no action control: no Download button, no Form Link, no disabled control.
    await expect(card.locator('.btn-download')).toHaveCount(0);
    await expect(card.locator('button[disabled]')).toHaveCount(0);

    // Grid view: the same holds after the presentational toggle (no re-fetch).
    await page.locator('#viewGridBtn').click();
    await expect(page.locator('#resultsList')).toHaveClass(/is-grid/);
    const gcard = cardFor(page, NOSRC_FORM.form_number);
    await expect(gcard.locator('.file-type-pill:not(.file-date)')).toHaveCount(0);
    await expect(gcard.locator('.btn-download')).toHaveCount(0);
  });

  test('TC1.4 - no-source card keeps all other elements and alignment', async ({ page }) => {
    await page.goto('/');
    const card = cardFor(page, NOSRC_FORM.form_number);
    await expect(card.locator('.form-num-link')).toHaveText(NOSRC_FORM.form_number);
    await expect(card.locator('.ba-badge')).toHaveText(NOSRC_FORM.business_area);
    await expect(card.locator('h2')).toHaveText(NOSRC_FORM.title);
    await expect(card.locator('.card-desc')).toHaveText(NOSRC_FORM.description);
    await expect(card.locator('.card-date')).toContainText('Updated');
    await expect(card.locator('.file-date')).toBeVisible();            // effective date pill remains
    await expect(card.locator('.btn-view-more')).toHaveText(/View details/);
  });

  test('TC1.5 - mixed set shows correct affordance per card (no cross-contamination)', async ({ page }) => {
    await page.goto('/');
    // Downloadable
    await expect(cardFor(page, DOWNLOAD_FORM.form_number).locator('button.btn-download')).toHaveText(/Download/);
    await expect(cardFor(page, DOWNLOAD_FORM.form_number).locator('.file-type-pill.pdf')).toBeVisible();
    // Link-source
    await expect(cardFor(page, LINK_FORM.form_number).locator('a.btn-download')).toHaveText(/Form Link/);
    await expect(cardFor(page, LINK_FORM.form_number).locator('.file-type-pill.link')).toBeVisible();
    // No source
    await expect(cardFor(page, NOSRC_FORM.form_number).locator('.btn-download')).toHaveCount(0);
    await expect(cardFor(page, NOSRC_FORM.form_number).locator('.file-type-pill:not(.file-date)')).toHaveCount(0);
  });
});

/* ─── Form detail view ───────────────────────────────────────────────────── */

test('TC2.1/TC2.2 - no-source detail hides file-type + action, keeps other elements', async ({ page }) => {
  await mockApi(page, { forms: [NOSRC_FORM] });
  await page.goto(`/forms/${NOSRC_FORM.form_number}`);

  await expect(page.locator('#detailHeading')).toHaveText(NOSRC_FORM.title);
  // No file-type pill and no primary action.
  await expect(page.locator('#detailContent .file-type-pill')).toHaveCount(0);
  await expect(page.locator('#detailContent button[data-action="download"]')).toHaveCount(0);
  await expect(page.locator('#detailContent a.btn-download')).toHaveCount(0);
  // Other elements remain: hero form number, description, back link.
  await expect(page.locator('#detailContent .form-card__num')).toHaveText(NOSRC_FORM.form_number);
  await expect(page.locator('#detailContent')).toContainText(NOSRC_FORM.description);
  await expect(page.locator('#backLink')).toBeVisible();
});

/* ─── Preserved (regression) behaviour ──────────────────────────────────── */

test('TC3.1 - downloadable form unchanged (card + detail, issues file request)', async ({ page }) => {
  await mockApi(page, { forms: [DOWNLOAD_FORM] });
  await page.goto('/');
  const btn = cardFor(page, DOWNLOAD_FORM.form_number).locator('button.btn-download[data-action="download"]');
  await expect(btn).toHaveText(/Download/);
  const reqP = page.waitForRequest(`**/forms/${DOWNLOAD_FORM.form_number}/file`);
  await btn.click();
  await reqP;

  await page.goto(`/forms/${DOWNLOAD_FORM.form_number}`);
  await expect(page.locator('#detailContent button[data-action="download"]')).toHaveText(/Download/);
  await expect(page.locator('#detailContent .file-type-pill')).toHaveText(/PDF/i);
});

test('TC3.2 - link-source form unchanged (card + detail)', async ({ page }) => {
  await mockApi(page, { forms: [LINK_FORM] });
  await page.goto('/');
  await expect(cardFor(page, LINK_FORM.form_number).locator('a.btn-download')).toHaveText(/Form Link/);

  await page.goto(`/forms/${LINK_FORM.form_number}`);
  const action = page.locator('#detailContent a.btn-download');
  await expect(action).toHaveText(/Form Link/);
  await expect(action).toHaveAttribute('href', LINK_FORM.url as string);
  await expect(action).toHaveAttribute('target', '_blank');
});

test('TC3.3 - legacy null with file_type still downloads (AC15/E11)', async ({ page }) => {
  await mockApi(page, { forms: [LEGACY_FILE_FORM] });
  await page.goto('/');
  await expect(cardFor(page, LEGACY_FILE_FORM.form_number).locator('button.btn-download')).toHaveText(/Download/);
  await expect(cardFor(page, LEGACY_FILE_FORM.form_number).locator('.file-type-pill.docx')).toBeVisible();

  await page.goto(`/forms/${LEGACY_FILE_FORM.form_number}`);
  await expect(page.locator('#detailContent button[data-action="download"]')).toHaveText(/Download/);
});

/* ─── Edge cases, accessibility, scope ──────────────────────────────────── */

test('TC4.1 - unsafe/relative url with no file is no-source; unsafe value never in DOM', async ({ page }) => {
  await mockApi(page, { forms: [UNSAFE_NOSRC_FORM, RELATIVE_NOSRC_FORM] });
  await page.goto('/');

  for (const f of [UNSAFE_NOSRC_FORM, RELATIVE_NOSRC_FORM]) {
    const card = cardFor(page, f.form_number);
    await expect(card.locator('.btn-download')).toHaveCount(0);
    await expect(card.locator('.file-type-pill:not(.file-date)')).toHaveCount(0);
  }
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
  await expect(page.locator('a[href="/relative/path"]')).toHaveCount(0);

  // Detail view of the unsafe form: no action, no unsafe href.
  await page.goto(`/forms/${UNSAFE_NOSRC_FORM.form_number}`);
  await expect(page.locator('#detailContent a.btn-download')).toHaveCount(0);
  await expect(page.locator('#detailContent button[data-action="download"]')).toHaveCount(0);
  await expect(page.locator('#detailContent a[href^="javascript:"]')).toHaveCount(0);
});

test('TC4.2 - no-source card/detail leave no dangling focusable control + no axe violations', async ({ page }) => {
  await mockApi(page, { forms: [DOWNLOAD_FORM, LINK_FORM, NOSRC_FORM] });

  await page.goto('/');
  const card = cardFor(page, NOSRC_FORM.form_number);
  // No focusable download/link control inside the no-source card footer.
  await expect(card.locator('.card-footer-row button, .card-footer-row a.btn-download')).toHaveCount(0);
  const homeAxe = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(homeAxe.violations, JSON.stringify(homeAxe.violations, null, 2)).toEqual([]);

  await page.goto(`/forms/${NOSRC_FORM.form_number}`);
  // The Share control (FEAT-0028 US-006 AC26) is expected; no source affordance is.
  await expect(page.locator('#detailContent [data-action="download"], #detailContent a.btn-download')).toHaveCount(0);
  await expect(page.locator('#detailContent [data-action="share"]')).toHaveCount(1);
  const detailAxe = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(detailAxe.violations, JSON.stringify(detailAxe.violations, null, 2)).toEqual([]);
});

test('TC4.3 - no page-level horizontal overflow at 320/768/1280 px', async ({ page }) => {
  await mockApi(page, { forms: [DOWNLOAD_FORM, LINK_FORM, NOSRC_FORM] });
  for (const width of [320, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    await expect(cardFor(page, NOSRC_FORM.form_number)).toBeVisible();
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(overflow, `home overflow @ ${width}px`).toBe(false);

    await page.goto(`/forms/${NOSRC_FORM.form_number}`);
    await expect(page.locator('#detailHeading')).toBeVisible();
    const dOverflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(dOverflow, `detail overflow @ ${width}px`).toBe(false);
  }
});

test('TC4.4 - scope guard: no file request issued for a no-source form', async ({ page }) => {
  await mockApi(page, { forms: [NOSRC_FORM] });
  let fileRequested = false;
  page.on('request', (r) => { if (/\/file$/.test(new URL(r.url()).pathname)) fileRequested = true; });
  await page.goto('/');
  await expect(cardFor(page, NOSRC_FORM.form_number)).toBeVisible();
  await page.goto(`/forms/${NOSRC_FORM.form_number}`);
  await expect(page.locator('#detailHeading')).toBeVisible();
  expect(fileRequested).toBe(false);
});

test('TC4.5 - Download-typed / legacy-null with no file_type is no-source (card + detail)', async ({ page }) => {
  await mockApi(page, { forms: [DL_NOFILE_FORM, NULL_NOFILE_FORM] });
  await page.goto('/');
  for (const f of [DL_NOFILE_FORM, NULL_NOFILE_FORM]) {
    const card = cardFor(page, f.form_number);
    await expect(card.locator('.btn-download')).toHaveCount(0);
    await expect(card.locator('.file-type-pill:not(.file-date)')).toHaveCount(0);
  }

  await page.goto(`/forms/${DL_NOFILE_FORM.form_number}`);
  await expect(page.locator('#detailContent button[data-action="download"]')).toHaveCount(0);
  await expect(page.locator('#detailContent .file-type-pill')).toHaveCount(0);
});
