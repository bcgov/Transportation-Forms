/*
 * Public Forms Portal — entry point.
 *
 * Bootstrap sequence (DOMContentLoaded):
 *   1. render CMS-driven navbar (FEAT-0026 US-012) — fire-and-forget
 *   2. wire router (popstate + delegated link clicks)
 *   3. dispatch initial route
 *
 * The branded site header is static markup in index.html (FEAT-0028 US-001);
 * it is the sole authoritative public header and is never rendered at runtime.
 * FEAT-0028 US-003 — result cards are rendered directly as <article.form-card-v2>
 * by the home view; the legacy <form-card> custom element is no longer used or
 * registered (AC11).
 *
 * No new dependencies. Pure ES modules, served same-origin.
 */

import { initRouter, dispatch, registerRoutes } from './router.js';
import { showHomeView } from './views/home.js';
import { showDetailView } from './views/detail.js';
import { showCmsPageView } from './views/cms-page.js';
import { showNotFoundView } from './views/not-found.js';
import { renderCmsNav, _markActive as _markCmsNavActive } from './components/cms-navbar.js';

function boot() {
  // 1. Wire route handlers. Each is wrapped so the CMS navbar active link is
  //    recomputed AFTER the route has rendered and window.location.pathname is
  //    already up to date. This fixes the stale-highlight defect where the
  //    previously visited link stayed active because marking ran before the
  //    router updated the path (US-004 AC1-AC7).
  registerRoutes({
    onHome: _withNavHighlight(showHomeView),
    onDetail: _withNavHighlight(showDetailView),
    onCmsPage: _withNavHighlight(showCmsPageView),
    onNotFound: _withNavHighlight(showNotFoundView),
  });

  // 2. Wire router-level events (popstate + delegated clicks)
  initRouter();

  // 3. Kick off the CMS navbar fetch (fire-and-forget; failure is silent).
  //    renderCmsNav marks the active link itself once the links exist, which
  //    covers deep-link / first paint (US-004 AC3).
  renderCmsNav().catch(() => { /* handled inside */ });

  // 4. Dispatch initial route
  dispatch();
}

// Recompute the CMS navbar active link after the wrapped route handler runs.
// dispatch() reads location.pathname before invoking the handler, so by the
// time we mark here the current path is authoritative (US-004 AC1-AC7).
function _withNavHighlight(handler) {
  return async (...args) => {
    try {
      return await handler(...args);
    } finally {
      _markCmsNavActive();
    }
  };
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}
