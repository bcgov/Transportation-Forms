/*
 * History API router for the public-frontend SPA.
 *
 * Routes:
 *   /                       → home view
 *   /forms/{form_number}    → detail view
 *   anything else           → 404 view (US-006 AC9)
 */

import { ROUTES } from './constants.js';

const VIEWS = ['homeView', 'detailView', 'notFoundView'];

function _hideAll() {
  for (const id of VIEWS) {
    const el = document.getElementById(id);
    if (el) el.setAttribute('hidden', '');
  }
}

function _show(id) {
  const el = document.getElementById(id);
  if (el) el.removeAttribute('hidden');
}

let _onHomeShow = null;
let _onDetailShow = null;
let _onNotFoundShow = null;

export function registerRoutes({ onHome, onDetail, onNotFound }) {
  _onHomeShow = onHome;
  _onDetailShow = onDetail;
  _onNotFoundShow = onNotFound;
}

/**
 * Match the current pathname and render the matching view.
 * Public so it can be triggered on popstate or after navigation.
 */
export async function dispatch() {
  const path = window.location.pathname;
  _hideAll();

  if (path === ROUTES.HOME) {
    _show('homeView');
    if (_onHomeShow) await _onHomeShow();
    return;
  }
  if (path.startsWith(ROUTES.FORM_DETAIL_PREFIX)) {
    const tail = path.slice(ROUTES.FORM_DETAIL_PREFIX.length);
    const formNumber = decodeURIComponent(tail).replace(/\/$/, '');
    if (!formNumber) {
      // /forms/  → redirect home (US-003 §Edge cases)
      window.history.replaceState(null, '', ROUTES.HOME);
      _show('homeView');
      if (_onHomeShow) await _onHomeShow();
      return;
    }
    _show('detailView');
    if (_onDetailShow) await _onDetailShow(formNumber);
    return;
  }

  _show('notFoundView');
  if (_onNotFoundShow) await _onNotFoundShow();
}

/**
 * Programmatic navigation. Use {state} to seed history.state so the
 * destination can render cache-first (US-003 AC1).
 */
export function navigateTo(path, { state = null, replace = false } = {}) {
  if (replace) window.history.replaceState(state, '', path);
  else window.history.pushState(state, '', path);
  dispatch();
}

/** Wire up popstate + delegated [data-route] / anchor interception. */
export function initRouter() {
  window.addEventListener('popstate', () => { dispatch(); });
  document.addEventListener('click', e => {
    const a = e.target.closest('a');
    if (!a) return;
    if (a.dataset.noRouter === '1') return;
    if (a.target && a.target !== '' && a.target !== '_self') return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    const href = a.getAttribute('href');
    if (!href || !href.startsWith('/')) return;
    if (href.startsWith('//')) return;
    // Skip anchors that explicitly leave the SPA (e.g. /api/, /vendor/).
    if (href.startsWith('/api/') || href.startsWith('/vendor/')) return;
    e.preventDefault();
    const stateAttr = a.dataset.routeState;
    let payload = null;
    if (stateAttr) {
      try { payload = JSON.parse(stateAttr); } catch { payload = null; }
    }
    navigateTo(href, { state: payload });
  });
}
