/*
 * Reusable DOM / format / URL helpers. Single canonical copy.
 * Per FRONTEND.md — never redefine these in view modules.
 */

import { Q_MAX_LENGTH, SORT_FIELDS, SORT_ORDERS, DEFAULT_SORT_FIELD,
         DEFAULT_SORT_ORDER, FILE_TYPE_LABELS } from './constants.js';

/**
 * HTML-entity-escape a string before insertion into innerHTML.
 * MANDATORY for any value that originates from the API or user input
 * (US-002 AC10 / US-009 AC11). Numbers/booleans are coerced to string.
 */
export function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(value).replace(/[&<>"']/g, c => map[c]);
}

/** Format an ISO date as "Jan 15, 2026" using en-CA locale. (US-002 AC11) */
export function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = typeof iso === 'string' ? new Date(iso) : iso;
    if (isNaN(d.getTime())) return String(iso);
    return new Intl.DateTimeFormat('en-CA', { dateStyle: 'medium' }).format(d);
  } catch {
    return String(iso);
  }
}

/** Format an ISO datetime for "last updated" lines. */
export function formatDateTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return new Intl.DateTimeFormat('en-CA', { dateStyle: 'medium', timeStyle: 'short' }).format(d);
  } catch {
    return String(iso);
  }
}

/** File-type → human-readable badge label (US-002 AC8). */
export function formatFileType(ft) {
  if (!ft) return '';
  return FILE_TYPE_LABELS[String(ft).toLowerCase()] || String(ft).toUpperCase();
}

/** Truncate to N chars at the nearest word boundary, preserving full UTF-8. (US-002 AC9) */
export function truncate(text, max = 160) {
  if (!text) return '';
  const s = String(text);
  if (s.length <= max) return s;
  const slice = s.slice(0, max);
  const lastSpace = slice.lastIndexOf(' ');
  return (lastSpace > max * 0.6 ? slice.slice(0, lastSpace) : slice).trimEnd() + '…';
}

/**
 * Parse + normalise the URL search params into the SPA state shape.
 * Invalid values are dropped (US-005 AC13 — gracefully degrades).
 * Returns { q, f, s, o, p, view }.
 */
export function parseQuery(searchString) {
  const u = new URLSearchParams(searchString || '');
  let q = (u.get('q') || '').trim();
  if (q.length === 0) q = '';
  if (q.length > Q_MAX_LENGTH) q = q.slice(0, Q_MAX_LENGTH);

  let f = (u.get('f') || '').trim();
  let s = (u.get('s') || '').trim();
  if (!SORT_FIELDS.includes(s)) s = '';
  let o = (u.get('o') || '').trim();
  if (!SORT_ORDERS.includes(o)) o = '';
  const pRaw = parseInt(u.get('p') || '', 10);
  const p = (Number.isFinite(pRaw) && pRaw >= 1) ? pRaw : 1;
  const view = u.get('view') === 'all' ? 'all' : '';

  return { q, f, s, o, p, view };
}

/**
 * Build a URL search string from the SPA state.
 * Empty / default values are omitted to keep the URL clean.
 */
export function buildQuery(state) {
  const u = new URLSearchParams();
  if (state.q) u.set('q', state.q);
  if (state.f) u.set('f', state.f);
  if (state.s && state.s !== DEFAULT_SORT_FIELD) u.set('s', state.s);
  if (state.o && state.o !== DEFAULT_SORT_ORDER) u.set('o', state.o);
  if (state.p && state.p !== 1) u.set('p', String(state.p));
  if (state.view === 'all') u.set('view', 'all');
  const s = u.toString();
  return s ? `?${s}` : '';
}

/** Compute byte length of a JSON-serialisable value. (US-003 AC15 cap check) */
export function byteLength(value) {
  try {
    return new Blob([JSON.stringify(value)]).size;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

/** Make a single-element creator with attribute spread. */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v === null || v === undefined) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return node;
}

/**
 * Accept a destination URL only when it is a non-empty http(s) value.
 * Any other scheme (e.g. `javascript:`) returns '' so a hostile or future
 * value can never reach an href. (FEAT-0028 US-004 BR-006 / US-006 VR-002)
 */
export function safeHttpUrl(url) {
  if (!url || typeof url !== 'string') return '';
  const trimmed = url.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : '';
}

/* ─── Inline SVG icons (Bootstrap Icons path data; no icon-font dependency) ── */

const _FILE_BASE = '<path d="M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5z"/>';

const ICON_PATHS = {
  calendar: '<path d="M3.5 0a.5.5 0 0 1 .5.5V1h8V.5a.5.5 0 0 1 1 0V1h1a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2h1V.5a.5.5 0 0 1 .5-.5M1 4v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V4z"/>',
  eye: '<path d="M16 8s-3-5.5-8-5.5S0 8 0 8s3 5.5 8 5.5S16 8 16 8M1.173 8a13 13 0 0 1 1.66-2.043C4.12 4.668 5.88 3.5 8 3.5s3.879 1.168 5.168 2.457A13 13 0 0 1 14.828 8q-.086.13-.195.288c-.335.48-.83 1.12-1.465 1.755C11.879 11.332 10.119 12.5 8 12.5s-3.879-1.168-5.168-2.457A13 13 0 0 1 1.172 8z"/><path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5M4.5 8a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0"/>',
  download: '<path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5"/><path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z"/>',
  link: '<path d="M4.715 6.542 3.343 7.914a3 3 0 1 0 4.243 4.243l1.828-1.829A3 3 0 0 0 8.586 5.5L8 6.086a1 1 0 0 0-.154.199 2 2 0 0 1 .861 3.337L6.88 11.45a2 2 0 1 1-2.83-2.83l.793-.792a4 4 0 0 1-.128-1.287z"/><path d="M6.586 4.672A3 3 0 0 0 7.414 9.5l.775-.776a2 2 0 0 1-.896-3.346L9.12 3.55a2 2 0 1 1 2.83 2.83l-.793.792c.112.42.155.855.128 1.287l1.372-1.372a3 3 0 1 0-4.243-4.243z"/>',
  externalLink: '<path fill-rule="evenodd" d="M8.636 3.5a.5.5 0 0 0-.5-.5H1.5A1.5 1.5 0 0 0 0 4.5v10A1.5 1.5 0 0 0 1.5 16h10a1.5 1.5 0 0 0 1.5-1.5V7.864a.5.5 0 0 0-1 0V14.5a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-10a.5.5 0 0 1 .5-.5h6.636a.5.5 0 0 0 .5-.5"/><path fill-rule="evenodd" d="M16 .5a.5.5 0 0 0-.5-.5h-5a.5.5 0 0 0 0 1h3.793L6.146 9.146a.5.5 0 1 0 .708.708L15 1.707V5.5a.5.5 0 0 0 1 0z"/>',
  chevronLeft: '<path d="M11.354 1.646a.5.5 0 0 1 0 .708L5.707 8l5.647 5.646a.5.5 0 0 1-.708.708l-6-6a.5.5 0 0 1 0-.708l6-6a.5.5 0 0 1 .708 0"/>',
  chevronRight: '<path d="M4.646 1.646a.5.5 0 0 1 .708 0l6 6a.5.5 0 0 1 0 .708l-6 6a.5.5 0 0 1-.708-.708L10.293 8 4.646 2.354a.5.5 0 0 1 0-.708"/>',
  chevronDoubleLeft: '<path d="M8.354 1.646a.5.5 0 0 1 0 .708L2.707 8l5.647 5.646a.5.5 0 0 1-.708.708l-6-6a.5.5 0 0 1 0-.708l6-6a.5.5 0 0 1 .708 0"/><path d="M12.354 1.646a.5.5 0 0 1 0 .708L6.707 8l5.647 5.646a.5.5 0 0 1-.708.708l-6-6a.5.5 0 0 1 0-.708l6-6a.5.5 0 0 1 .708 0"/>',
  chevronDoubleRight: '<path d="M3.646 1.646a.5.5 0 0 1 .708 0l6 6a.5.5 0 0 1 0 .708l-6 6a.5.5 0 0 1-.708-.708L9.293 8 3.646 2.354a.5.5 0 0 1 0-.708"/><path d="M7.646 1.646a.5.5 0 0 1 .708 0l6 6a.5.5 0 0 1 0 .708l-6 6a.5.5 0 0 1-.708-.708L13.293 8 7.646 2.354a.5.5 0 0 1 0-.708"/>',
  arrowLeft: '<path fill-rule="evenodd" d="M15 8a.5.5 0 0 0-.5-.5H2.707l3.147-3.146a.5.5 0 1 0-.708-.708l-4 4a.5.5 0 0 0 0 .708l4 4a.5.5 0 0 0 .708-.708L2.707 8.5H14.5A.5.5 0 0 0 15 8"/>',
  share: '<path d="M13.5 1a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3M11 2.5a2.5 2.5 0 1 1 .603 1.628l-6.718 3.12a2.5 2.5 0 0 1 0 1.504l6.718 3.12a2.5 2.5 0 1 1-.488.876l-6.718-3.12a2.5 2.5 0 1 1 0-3.256l6.718-3.12A2.5 2.5 0 0 1 11 2.5m-8.5 4a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3m11 5.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3"/>',
  infoCircle: '<path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14m0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16"/><path d="m8.93 6.588-2.29.287-.082.38.45.083c.294.07.352.176.288.469l-.738 3.468c-.194.897.105 1.319.808 1.319.545 0 1.178-.252 1.465-.598l.088-.416c-.2.176-.492.246-.686.246-.275 0-.375-.193-.304-.533zM9 4.5a1 1 0 1 1-2 0 1 1 0 0 1 2 0"/>',
  filePdf: _FILE_BASE + '<path d="M4.603 12.087a.8.8 0 0 1-.438-.42c-.195-.388-.13-.776.08-1.102.198-.307.526-.568.897-.787a7.7 7.7 0 0 1 1.482-.645 20 20 0 0 0 1.062-2.227 7.3 7.3 0 0 1-.43-1.295c-.086-.4-.119-.796-.046-1.136.075-.354.274-.672.65-.823.192-.077.4-.12.602-.077a.7.7 0 0 1 .477.365c.088.164.12.356.127.538.007.187-.012.395-.047.614-.084.51-.27 1.134-.52 1.794a11 11 0 0 0 .98 1.686 5.8 5.8 0 0 1 1.334.05c.364.066.734.195.96.465.12.144.193.32.2.518.007.192-.047.382-.138.563a1.04 1.04 0 0 1-.354.416.86.86 0 0 1-.51.138c-.331-.014-.654-.196-.933-.417a5.7 5.7 0 0 1-.911-.95 11.6 11.6 0 0 0-1.997.406 11.3 11.3 0 0 1-1.02 1.51c-.292.35-.609.656-.927.787a.8.8 0 0 1-.58.029m1.379-1.901q-.25.115-.459.238c-.328.194-.541.383-.647.547-.094.145-.096.25-.04.361.01.022.02.036.026.044a.27.27 0 0 0 .035-.012c.137-.056.355-.235.635-.572a8 8 0 0 0 .45-.606zm1.64-1.33a13 13 0 0 1 1.01-.193 12 12 0 0 1-.51-.858 21 21 0 0 1-.5 1.05zm2.446.45q.226.244.435.41c.24.19.407.253.498.256a.1.1 0 0 0 .07-.015.3.3 0 0 0 .094-.125.44.44 0 0 0 .059-.2.1.1 0 0 0-.026-.063c-.052-.062-.2-.152-.518-.209a4 4 0 0 0-.585-.041zM8.078 5.8a7 7 0 0 0 .2-.828q.046-.282.038-.465a.6.6 0 0 0-.032-.198.5.5 0 0 0-.145.04c-.087.035-.158.106-.196.283-.04.192-.03.469.046.822q.036.167.09.35z"/>',
  fileWord: _FILE_BASE + '<path d="M5.485 7.879a.5.5 0 1 0-.97.242l1.5 6a.5.5 0 0 0 .967.01L8 10.402l1.018 3.73a.5.5 0 0 0 .967-.01l1.5-6a.5.5 0 0 0-.97-.242l-1.036 4.144-.997-3.655a.5.5 0 0 0-.964 0l-.997 3.655z"/>',
  fileExcel: _FILE_BASE + '<path d="M5.884 7.68a.5.5 0 1 0-.768.64L7.349 11l-2.233 2.68a.5.5 0 0 0 .768.64L8 12.281l2.116 2.54a.5.5 0 0 0 .768-.641L8.651 11l2.233-2.68a.5.5 0 0 0-.768-.64L8 9.719 5.884 7.68z"/>',
  fileText: _FILE_BASE + '<path d="M5 12a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1h-5A.5.5 0 0 1 5 12m0-2a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1h-5A.5.5 0 0 1 5 10m0-2a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1h-5A.5.5 0 0 1 5 8m0-2a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 0 1h-2A.5.5 0 0 1 5 6"/>',
  file: _FILE_BASE,
};

/** Render a named inline icon as a decorative SVG string. */
export function icon(name) {
  const paths = ICON_PATHS[name];
  if (!paths) return '';
  return `<svg class="bi" viewBox="0 0 16 16" fill="currentColor" width="1em" height="1em" aria-hidden="true">${paths}</svg>`;
}

/** Map a file-type value to its icon; unknown types fall back to a generic file. */
export function fileTypeIcon(ft) {
  switch (String(ft || '').toLowerCase()) {
    case 'pdf': return icon('filePdf');
    case 'doc':
    case 'docx': return icon('fileWord');
    case 'xls':
    case 'xlsx':
    case 'csv': return icon('fileExcel');
    case 'txt': return icon('fileText');
    default: return icon('file');
  }
}
