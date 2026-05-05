/*
 * URL-driven SPA state + scroll memory + aria-live announcer.
 *
 * The URL is the source of truth (US-001 BR-003). This module provides
 * helpers to read / update the URL without duplicating logic across views.
 */

import { parseQuery, buildQuery } from './utils.js';

/** Current state derived from window.location.search. */
export function getState() {
  return parseQuery(window.location.search);
}

/**
 * Update URL query string in place (replaceState by default — does not
 * push a new history entry). Use `mode='push'` when the change should be
 * back-button-able (e.g. opening the detail page).
 */
export function setUrl(state, mode = 'replace') {
  const qs = buildQuery(state);
  const newUrl = window.location.pathname + qs;
  if (mode === 'push') window.history.pushState(null, '', newUrl);
  else window.history.replaceState(null, '', newUrl);
}

/* ─── Scroll memory (US-001 AC7 / US-003 AC9) ───────────────────────────── */

const _scrollByRoute = new Map();

export function rememberScroll(key) {
  _scrollByRoute.set(key, window.scrollY || 0);
}
export function restoreScroll(key) {
  const y = _scrollByRoute.get(key);
  if (typeof y === 'number') {
    requestAnimationFrame(() => { window.scrollTo({ top: y, behavior: 'auto' }); });
  }
}

/* ─── Aria-live announcer (US-001 AC3 / US-005 AC14) ────────────────────── */

let _liveEl = null;
let _announceTimer = null;
const ANNOUNCE_DEBOUNCE_MS = 100; // US-007 edge case: prevent double-announce on rapid calls

function _ensureLive() {
  if (_liveEl) return _liveEl;
  _liveEl = document.getElementById('resultsCount');
  return _liveEl;
}

export function announce(message) {
  const el = _ensureLive();
  if (!el) return;
  if (_announceTimer) clearTimeout(_announceTimer);
  _announceTimer = setTimeout(() => {
    el.textContent = message;
    _announceTimer = null;
  }, ANNOUNCE_DEBOUNCE_MS);
}
