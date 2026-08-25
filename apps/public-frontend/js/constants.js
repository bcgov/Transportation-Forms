/*
 * Single source of truth for magic strings + numbers.
 * Per FRONTEND.md — never hardcode these in view modules.
 */

export const API_BASE = '/api/public/v1';

/**
 * Public site brand string. Used for the `<title>` chunk after the form
 * identifier (US-005) and shared with existing SEO metadata so the tab
 * title never drifts from the site brand.
 */
export const SITE_NAME = 'Transportation Forms — BC Government';

export const ROUTES = {
  HOME: '/',
  FORM_DETAIL_PREFIX: '/forms/',
};

// FEAT-0026 US-011 / US-013 — SPA catch-all reserved paths.
// Any path that matches one of these prefixes is claimed by an
// existing view and must NOT be dispatched to the CMS catch-all.
// A slug is only a candidate for a CMS page when its leading segment
// is not in this list. Keep in sync with any new top-level route.
export const CMS_RESERVED_TOP_SEGMENTS = new Set([
  'forms',
  'assets',
  'css',
  'js',
  'fonts',
  'api',
  'vendor',
  'robots.txt',
  'sitemap.xml',
]);

// Slug syntax (must match apps/public-backend/routes/cms.py::_slug_is_safe).
// Lowercase kebab-case, 1..80 chars, no leading/trailing hyphen, no "--".
export const CMS_SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const CMS_SLUG_MAX = 80;

export const PAGE_SIZE = 25;             // US-005 BR-001 / US-001 A2
export const VIEW_ALL_CAP = 500;         // US-005 BR-002 / A3
export const SEARCH_DEBOUNCE_MS = 300;   // US-001 BR-002 / A1
export const HISTORY_STATE_CAP_BYTES = 64 * 1024; // US-003 A6
export const Q_MAX_LENGTH = 100;         // US-014 / US-001 §Data validation

export const SORT_FIELDS = ['title', 'form_number', 'effective_date', 'updated_at'];
export const SORT_ORDERS = ['asc', 'desc'];

// Default first-paint sort (US-001 BR-001).
// On a search-active page, default falls back to title/asc per US-005 BR-003,
// but the URL is the source of truth so home.js handles that.
export const DEFAULT_SORT_FIELD = 'updated_at';
export const DEFAULT_SORT_ORDER = 'desc';

export const ALERT_DISMISS_MS = {
  RATE_LIMIT: 5000,    // US-006 BR-006
  ERROR: 8000,
  SUCCESS: 4000,       // FEAT-0028 US-006 AC27 — Share confirmation
};

export const FILE_TYPE_LABELS = {
  pdf: 'PDF', docx: 'DOCX', xlsx: 'XLSX', xls: 'XLS', doc: 'DOC',
  pptx: 'PPTX', ppt: 'PPT', txt: 'TXT', csv: 'CSV',
};
