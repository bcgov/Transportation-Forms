import { test, expect } from '@playwright/test';
import { mockApi, LINK_FORM, FILE_FORM, UNSAFE_FORM } from '../fixtures/mock-api';

/**
 * US-004 Defect B — link-source forms present a "Form Link" action with the
 * external-link icon (not "Download"/"Link", not the chain/download icon), on
 * both the home cards and the detail view. Covers AC9-AC21.
 */

const cardFor = (page, num: string) =>
  page.locator(`article.form-card-v2:has(.form-num-link:text-is("${num}"))`);

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test('AC9/AC10 - link-source card action reads "Form Link" with the external-link icon (list + grid)', async ({ page }) => {
  await page.goto('/');
  const card = cardFor(page, LINK_FORM.form_number);
  await expect(card).toBeVisible();

  const action = card.locator('a.btn-download');
  await expect(action).toHaveText(/Form Link/);
  await expect(action).not.toHaveText(/Download/);
  // External-link icon present; chain-link/download path data absent in the action.
  await expect(action.locator('svg.bi')).toBeVisible();
  await expect(action.locator('svg')).toHaveCount(1);

  // Grid view: same action text/icon after presentational toggle (no re-fetch).
  await page.locator('#viewGridBtn').click();
  await expect(page.locator('#resultsList')).toHaveClass(/is-grid/);
  await expect(cardFor(page, LINK_FORM.form_number).locator('a.btn-download')).toHaveText(/Form Link/);
});

test('AC11 - "Form Link" opens the destination in a new tab and issues no download', async ({ page }) => {
  await page.goto('/');
  const action = cardFor(page, LINK_FORM.form_number).locator('a.btn-download');

  await expect(action).toHaveAttribute('href', LINK_FORM.url);
  await expect(action).toHaveAttribute('target', '_blank');
  await expect(action).toHaveAttribute('rel', /noopener/);
  await expect(action).toHaveAttribute('rel', /noreferrer/);
  await expect(action).toHaveAttribute('data-no-router', '1');

  // Stub the external destination so the popup resolves offline.
  await page.context().route('https://www2.gov.bc.ca/**', (r) =>
    r.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>ok</title>' }),
  );

  let fileRequested = false;
  page.on('request', (r) => { if (/\/file$/.test(new URL(r.url()).pathname)) fileRequested = true; });
  const popupP = page.waitForEvent('popup');
  await action.click();
  const popup = await popupP;
  expect(new URL(popup.url()).host).toContain('www2.gov.bc.ca');
  await popup.close();
  expect(fileRequested).toBe(false);
});

test('AC12 - "Form Link" has an accessible name conveying a new-tab external link and is keyboard-focusable', async ({ page }) => {
  await page.goto('/');
  const action = cardFor(page, LINK_FORM.form_number).locator('a.btn-download');
  await expect(action).toHaveAttribute('aria-label', /Open link for CVSE0001 \(opens in new tab\)/);
  await action.focus();
  await expect(action).toBeFocused();
});

test('AC13 - downloadable-file card keeps the "Download" button and download action', async ({ page }) => {
  await page.goto('/');
  const card = cardFor(page, FILE_FORM.form_number);
  const btn = card.locator('button.btn-download[data-action="download"]');
  await expect(btn).toHaveText(/Download/);
  await expect(btn).not.toHaveText(/Form Link/);

  const reqP = page.waitForRequest(`**/forms/${FILE_FORM.form_number}/file`);
  await btn.click();
  await reqP;
});

test('AC14/AC16 - unsafe url is rejected: no "Form Link", falls back to Download, no unsafe href', async ({ page }) => {
  await page.goto('/');
  const card = cardFor(page, UNSAFE_FORM.form_number);
  await expect(card.locator('button.btn-download[data-action="download"]')).toHaveText(/Download/);
  await expect(card.locator('a.btn-download')).toHaveCount(0);
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
});

test('AC15 - mixed result set shows the correct action per card', async ({ page }) => {
  await page.goto('/');
  await expect(cardFor(page, LINK_FORM.form_number).locator('a.btn-download')).toHaveText(/Form Link/);
  await expect(cardFor(page, FILE_FORM.form_number).locator('button.btn-download')).toHaveText(/Download/);
});

test('AC16 (pill) - the link-source file-type pill keeps its chain-link "Link" treatment', async ({ page }) => {
  await page.goto('/');
  const card = cardFor(page, LINK_FORM.form_number);
  // The pill is unchanged (label "Link", class .link) and is distinct from the action.
  await expect(card.locator('.file-type-pill.link')).toHaveText(/Link/);
  await expect(card.locator('.file-type-pill.link')).not.toHaveText(/Form Link/);
});

test('AC17/AC20 - detail view shows a "Form Link" action for link-source forms', async ({ page }) => {
  await page.goto(`/forms/${LINK_FORM.form_number}`);
  const action = page.locator('#detailContent a.btn-download');
  await expect(action).toHaveText(/Form Link/);
  await expect(action).toHaveAttribute('href', LINK_FORM.url);
  await expect(action).toHaveAttribute('target', '_blank');
  await expect(action).toHaveAttribute('rel', /noopener/);
  await expect(action).toHaveAttribute('aria-label', /opens in new tab/);
  await expect(page.locator('#detailContent button[data-action="download"]')).toHaveCount(0);
  await action.focus();
  await expect(action).toBeFocused();
});

test('AC18 - detail view keeps the Download button for file forms', async ({ page }) => {
  await page.goto(`/forms/${FILE_FORM.form_number}`);
  const btn = page.locator('#detailContent button[data-action="download"]');
  await expect(btn).toHaveText(/Download/);
  await expect(page.locator('#detailContent a.btn-download')).toHaveCount(0);
});

test('AC19 - detail view rejects an unsafe url and does not render a Form Link', async ({ page }) => {
  await page.goto(`/forms/${UNSAFE_FORM.form_number}`);
  await expect(page.locator('#detailContent a[href^="javascript:"]')).toHaveCount(0);
  // Unsafe url + file present -> falls back to the Download button.
  await expect(page.locator('#detailContent button[data-action="download"]')).toHaveText(/Download/);
});
