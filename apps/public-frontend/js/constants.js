/*
 * Single source of truth for magic strings + numbers.
 * Per FRONTEND.md — never hardcode these in view modules.
 */

export const API_BASE = '/api/public/v1';

export const ROUTES = {
  HOME: '/',
  FORM_DETAIL_PREFIX: '/forms/',
};

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
};

export const FILE_TYPE_LABELS = {
  pdf: 'PDF', docx: 'DOCX', xlsx: 'XLSX', xls: 'XLS', doc: 'DOC',
  pptx: 'PPTX', ppt: 'PPT', txt: 'TXT', csv: 'CSV',
};
