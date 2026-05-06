/*
 * frontend/js/shared/chrome.js
 *
 * Single source of truth for the BC Gov header used by:
 *   - frontend/index.html              (the internal authenticated SPA)
 *   - public-frontend/index.html       (the anonymous public portal)
 *
 * IMPORTANT — keep this file in sync with public-frontend/js/shared/chrome.js.
 * Both apps are built and served from separate Pods (US-015, US-016) so a
 * runtime cross-origin import is impossible. The file is committed twice
 * with identical content; the build pipeline (or a CI guard, see
 * 06-release-ops.md) verifies they remain byte-identical.
 *
 * Per US-010:
 *   - AC1: shared module exists at frontend/js/shared/chrome.js
 *   - AC2: visually identical across both apps
 *   - AC3: includes a "Skip to main content" link
 *   - AC11: works without JS — the host index.html may render a static
 *           fallback header that this module replaces in-place when JS runs.
 */

const HEADER_HTML = `
  <a class="visually-hidden-focusable skip-link" href="#mainContent">Skip to main content</a>
  <div class="bcgov-header" role="banner">
    <div class="container d-flex align-items-center py-2">
      <a href="/" class="d-flex align-items-center text-decoration-none" aria-label="BC Government — home">
        <img src="/vendor/bc-gov-logo.svg" alt="" width="155" height="42" class="me-3">
        <span class="visually-hidden">BC Government</span>
      </a>
      <span class="ms-3 fs-5 ministry-name d-none d-sm-inline">__APP_NAME__</span>
    </div>
  </div>
`;

/**
 * Render the shared header into a target element.
 * @param {HTMLElement} target - the element to replace innerHTML of (e.g. <header id="siteHeader">)
 * @param {object} [opts]
 * @param {string} [opts.appName] - human-readable app label shown next to the logo
 */
export function renderHeader(target, opts = {}) {
  if (!target) return;
  const appName = (opts.appName || 'BC Government').replace(/[<>&"]/g, c => ({
    '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;',
  })[c]);
  target.innerHTML = HEADER_HTML.replace('__APP_NAME__', appName);
}

export default { renderHeader };
