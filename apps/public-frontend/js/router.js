/*
 * History API router for the public-frontend SPA.
 *
 * Routes:
 *   /                       → home view
 *   /forms/{form_number}    → detail view
 *   /{slug}                 → CMS page view (FEAT-0026 US-011),
 *                             falls back to redirect + 404 (US-013)
 *   unmatched / bogus       → 404 view (US-006 AC9)
 *
 * The CMS catch-all is registered LAST and only fires for paths whose
 * leading segment is not in ``CMS_RESERVED_TOP_SEGMENTS``.
 */

import { ROUTES, CMS_RESERVED_TOP_SEGMENTS } from './constants.js';

const VIEWS = ['homeView', 'detailView', 'cmsPageView', 'notFoundView'];

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

/**
 * Public: switch the visible section to the 404 view and fire the
 * registered not-found handler. Used by ``views/cms-page.js`` when a
 * slug does not match a page or a redirect. Does NOT change the URL —
 * the address bar keeps the attempted path so the visitor can see it.
 */
export async function showNotFound() {
  _hideAll();
  _show('notFoundView');
  if (_onNotFoundShow) await _onNotFoundShow();
}

let _onHomeShow = null;
let _onDetailShow = null;
let _onCmsPageShow = null;
let _onNotFoundShow = null;

export function registerRoutes({ onHome, onDetail, onCmsPage, onNotFound }) {
  _onHomeShow = onHome;
  _onDetailShow = onDetail;
  _onCmsPageShow = onCmsPage;
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

  // FEAT-0026 US-011 catch-all: /{slug} for CMS pages.
  // Only single-segment lowercase kebab-case paths are eligible; the
  // CMS page view itself re-validates via CMS_SLUG_RE before hitting
  // the network.
  const cmsSlug = _extractCmsSlugCandidate(path);
  if (cmsSlug) {
    _show('cmsPageView');
    if (_onCmsPageShow) await _onCmsPageShow(cmsSlug);
    return;
  }

  _show('notFoundView');
  if (_onNotFoundShow) await _onNotFoundShow();
}

/**
 * Return the candidate slug for a path like ``/{slug}`` or
 * ``/{slug}/`` when its leading segment is not reserved and there is
 * no second segment. Returns ``null`` otherwise.
 */
function _extractCmsSlugCandidate(path) {
  if (!path || path === '/' || !path.startsWith('/')) return null;
  const trimmed = path.replace(/\/+$/, ''); // drop trailing slash
  if (!trimmed) return null;
  const rest = trimmed.slice(1); // drop leading /
  if (rest.includes('/')) return null; // multi-segment paths are not CMS pages
  if (CMS_RESERVED_TOP_SEGMENTS.has(rest)) return null;
  try {
    return decodeURIComponent(rest);
  } catch {
    return null;
  }
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
