/*
 * Public Forms Portal — entry point.
 *
 * Bootstrap sequence (DOMContentLoaded):
 *   1. register <form-card> custom element (side-effect import)
 *   2. render CMS-driven navbar (FEAT-0026 US-012) — fire-and-forget
 *   3. wire router (popstate + delegated link clicks)
 *   4. dispatch initial route
 *
 * The branded site header is static markup in index.html (FEAT-0028 US-001);
 * it is the sole authoritative public header and is never rendered at runtime.
 *
 * No new dependencies. Pure ES modules, served same-origin.
 */

import './components/form-card.js';
import { initRouter, dispatch, registerRoutes } from './router.js';
import { showHomeView } from './views/home.js';
import { showDetailView } from './views/detail.js';
import { showCmsPageView } from './views/cms-page.js';
import { showNotFoundView } from './views/not-found.js';
import { renderCmsNav, _markActive as _markCmsNavActive } from './components/cms-navbar.js';

function boot() {
  // 1. Wire route handlers
  registerRoutes({
    onHome: showHomeView,
    onDetail: showDetailView,
    onCmsPage: showCmsPageView,
    onNotFound: showNotFoundView,
  });

  // 2. Wire router-level events (popstate + delegated clicks)
  initRouter();

  // 3. Kick off the CMS navbar fetch (fire-and-forget; failure is silent).
  //    Then re-highlight the active link on every route change.
  renderCmsNav().catch(() => { /* handled inside */ });
  window.addEventListener('popstate', _markCmsNavActive);
  // Also refresh the active state after programmatic navigation.
  // A microtask fires after dispatch() has updated location.pathname.
  document.addEventListener('click', () => {
    queueMicrotask(_markCmsNavActive);
  }, true);

  // 4. Dispatch initial route
  dispatch();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}
