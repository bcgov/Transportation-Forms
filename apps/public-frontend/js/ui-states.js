/*
 * UI state helpers — loading skeletons, alerts, empty state.
 * Implements US-006 AC1/2/3/5/6/7/11/13/14.
 */

import { ALERT_DISMISS_MS, PAGE_SIZE } from './constants.js';
import { escapeHtml } from './utils.js';

/* ─── Loading skeleton (US-006 AC1, AC11) ───────────────────────────────── */

export function showSkeleton(count = PAGE_SIZE) {
  const list = document.getElementById('resultsList');
  const region = document.getElementById('resultsRegion');
  if (!list || !region) return;
  region.setAttribute('aria-busy', 'true');
  let html = '';
  for (let i = 0; i < count; i++) html += '<li class="skeleton-card" aria-hidden="true"></li>';
  list.innerHTML = html;
  document.getElementById('emptyState')?.setAttribute('hidden', '');
}

export function clearBusy() {
  document.getElementById('resultsRegion')?.setAttribute('aria-busy', 'false');
}

/* ─── Empty state (US-006 AC3, AC4) ─────────────────────────────────────── */

export function showEmpty() {
  const list = document.getElementById('resultsList');
  if (list) list.innerHTML = '';
  document.getElementById('emptyState')?.removeAttribute('hidden');
  document.getElementById('paginator')?.setAttribute('hidden', '');
}

export function hideEmpty() {
  document.getElementById('emptyState')?.setAttribute('hidden', '');
}

/* ─── Bottom-pinned alert slot (US-006 AC5/AC6/AC7/AC13) ────────────────── */

let _activeAlert = null;
let _activeTimer = null;

export function showAlert(message, kind = 'danger', { dismissMs, retry } = {}) {
  const slot = document.getElementById('alertSlot');
  if (!slot) return;
  // AC13 — single alert, replace prior so screen readers don't double-announce.
  if (_activeAlert) _activeAlert.remove();
  if (_activeTimer) { clearTimeout(_activeTimer); _activeTimer = null; }

  const wrapper = document.createElement('div');
  wrapper.className = `alert alert-${kind} alert-dismissible`;
  wrapper.setAttribute('role', 'alert');
  const safe = escapeHtml(message);
  wrapper.innerHTML = `
    <span>${safe}</span>
    ${retry ? `<button type="button" class="btn btn-sm btn-link p-0 ms-2" data-action="retry">Try again</button>` : ''}
    <button type="button" class="btn-close" aria-label="Dismiss" data-action="dismiss"></button>
  `;
  wrapper.addEventListener('click', e => {
    const action = e.target.closest('[data-action]')?.dataset.action;
    if (action === 'dismiss') dismissAlert();
    else if (action === 'retry' && retry) retry();
  });
  slot.appendChild(wrapper);
  _activeAlert = wrapper;

  const ms = dismissMs ?? (kind === 'warning' ? ALERT_DISMISS_MS.RATE_LIMIT : ALERT_DISMISS_MS.ERROR);
  if (ms > 0) _activeTimer = setTimeout(dismissAlert, ms);
}

export function dismissAlert() {
  if (_activeTimer) { clearTimeout(_activeTimer); _activeTimer = null; }
  if (_activeAlert) { _activeAlert.remove(); _activeAlert = null; }
}

/**
 * Map an ApiError to a user-facing alert.
 * - 429 → warning, 5s autodismiss, no auto-retry but input still editable.
 * - 5xx → danger, 8s autodismiss, retry button.
 * - network → danger, manual dismiss only.
 * - abort → silent.
 */
export function showApiAlert(err, retry) {
  if (!err || err.kind === 'abort') return;
  if (err.kind === 'rate-limit') {
    showAlert("You're searching too fast — please wait a moment and try again.", 'warning',
      { dismissMs: ALERT_DISMISS_MS.RATE_LIMIT });
    return;
  }
  if (err.kind === 'network') {
    showAlert('You appear to be offline. Check your connection and try again.', 'danger',
      { dismissMs: 0, retry });
    return;
  }
  if (err.kind === 'server') {
    showAlert('Something went wrong loading forms. Please try again.', 'danger',
      { dismissMs: ALERT_DISMISS_MS.ERROR, retry });
    return;
  }
  showAlert(err.detail || err.message || 'Request failed.', 'danger',
    { dismissMs: ALERT_DISMISS_MS.ERROR, retry });
}
