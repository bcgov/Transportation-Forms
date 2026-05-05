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
