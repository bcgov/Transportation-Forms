import type { Page, Route } from '@playwright/test';

/**
 * Deterministic API fixtures + a single route interceptor for the public API.
 *
 * The interceptor branches on the request pathname so every public endpoint the
 * SPA touches is served from static fixtures. This lets the US-004 specs verify
 * link-source ("Form Link") behaviour WITHOUT depending on FEAT-0029 exposing
 * the `url` field on the real backend.
 */

export interface CmsPageNavItem {
  slug: string;
  title: string;
  nav_order: number;
}

export interface CmsPageDetail extends CmsPageNavItem {
  meta_description: string;
  body_html: string;
  updated_at: string | null;
}

export const CMS_PAGES: CmsPageNavItem[] = [
  { slug: 'about', title: 'About', nav_order: 1 },
  { slug: 'contact', title: 'Contact', nav_order: 2 },
];

function cmsPageDetail(
  slug: string,
  pages: CmsPageNavItem[],
  details: Record<string, Partial<CmsPageDetail>>,
): CmsPageDetail | null {
  const page = pages.find(p => p.slug === slug);
  if (!page) return null;
  return {
    ...page,
    meta_description: `${page.title} page`,
    body_html: `<h1>${page.title}</h1><p>${page.title} content for testing.</p>`,
    updated_at: '2026-01-01T00:00:00Z',
    ...details[slug],
  };
}

// Link-source form (e.g. CVSE0001): non-empty http(s) url, no file.
export const LINK_FORM = {
  form_number: 'CVSE0001',
  title: 'Commercial Vehicle Inspection Report',
  description: 'A form that links to an external destination instead of a file.',
  business_area: 'Compliance',
  keywords: ['inspection', 'commercial'],
  file_type: null as string | null,
  effective_date: '2025-01-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
  url: 'https://www2.gov.bc.ca/gov/content/transportation',
};

// Downloadable file form: has file metadata, no url.
export const FILE_FORM = {
  form_number: 'TRAN0100',
  title: 'Transportation Permit Application',
  description: 'A standard downloadable PDF form.',
  business_area: 'Permits',
  keywords: ['permit'],
  file_type: 'pdf',
  effective_date: '2025-03-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
  url: null as string | null,
};

// Unsafe url form: value present but not http(s) -> must be rejected.
export const UNSAFE_FORM = {
  form_number: 'ZZZ0001',
  title: 'Form With Unsafe Link',
  description: 'A form whose url uses a rejected scheme.',
  business_area: 'Licensing',
  keywords: ['test'],
  file_type: 'pdf',
  effective_date: '2025-02-01T00:00:00Z',
  updated_at: '2026-04-01T00:00:00Z',
  url: 'javascript:alert(1)',
};

export const ALL_FORMS = [LINK_FORM, FILE_FORM, UNSAFE_FORM];

function toDetail(item: (typeof ALL_FORMS)[number]) {
  const hasFile = !!item.file_type && !item.url;
  return {
    form_number: item.form_number,
    title: item.title,
    description: item.description,
    business_area: item.business_area,
    keywords: item.keywords,
    file_type: item.file_type,
    form_source: (item as { form_source?: string | null }).form_source ?? null,
    effective_date: item.effective_date,
    updated_at: item.updated_at,
    url: item.url,
    file: hasFile
      ? { filename: `${item.form_number}.pdf`, size: 12345, content_type: item.file_type }
      : null,
  };
}

export interface MockOptions {
  forms?: Array<(typeof ALL_FORMS)[number]>;
  pages?: CmsPageNavItem[];
  cmsDetails?: Record<string, Partial<CmsPageDetail>>;
  cmsRedirects?: Record<string, string>;
}

export async function mockApi(page: Page, opts: MockOptions = {}): Promise<void> {
  const forms = opts.forms ?? ALL_FORMS;
  const pages = opts.pages ?? CMS_PAGES;
  const cmsDetails = opts.cmsDetails ?? {};
  const cmsRedirects = opts.cmsRedirects ?? {};

  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      headers: { 'Cache-Control': 'no-store' },
      body: JSON.stringify(body),
    });

  await page.route('**/api/public/v1/**', (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/\/$/, '');

    // CMS nav list
    if (path.endsWith('/pages')) {
      return json(route, pages);
    }
    // CMS page detail: /pages/{slug}
    const pageMatch = path.match(/\/pages\/([^/]+)$/);
    if (pageMatch) {
      const detail = cmsPageDetail(decodeURIComponent(pageMatch[1]), pages, cmsDetails);
      return detail ? json(route, detail) : json(route, { detail: 'Not found' }, 404);
    }
    // CMS legacy redirect resolver: /redirects/{slug}
    const redirectMatch = path.match(/\/redirects\/([^/]+)$/);
    if (redirectMatch) {
      const fromSlug = decodeURIComponent(redirectMatch[1]);
      const toSlug = cmsRedirects[fromSlug];
      return toSlug
        ? json(route, { from_slug: fromSlug, to_slug: toSlug })
        : json(route, { detail: 'Not found' }, 404);
    }
    // Form file download: /forms/{form_number}/file
    const fileMatch = path.match(/\/forms\/([^/]+)\/file$/);
    if (fileMatch) {
      return route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        headers: { 'Content-Disposition': `attachment; filename="${decodeURIComponent(fileMatch[1])}.pdf"` },
        body: '%PDF-1.4 test',
      });
    }
    // Form detail: /forms/{form_number}
    const detailMatch = path.match(/\/forms\/([^/]+)$/);
    if (detailMatch) {
      const num = decodeURIComponent(detailMatch[1]);
      const item = forms.find(f => f.form_number === num);
      return item ? json(route, toDetail(item)) : json(route, { detail: 'Not found' }, 404);
    }
    // Form list: /forms
    if (path.endsWith('/forms')) {
      return json(route, { total: forms.length, limit: 25, offset: 0, items: forms });
    }

    return route.continue();
  });
}
