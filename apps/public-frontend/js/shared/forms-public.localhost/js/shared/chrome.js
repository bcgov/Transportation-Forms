/*
 * public-frontend/js/shared/chrome.js
 *
 * MIRROR of frontend/js/shared/chrome.js — keep byte-identical.
 * See that file for design notes (US-010 AC1).
 

const HEADER_HTML = `
  <a class="visually-hidden-focusable skip-link" href="#mainContent">Skip to main content</a>
  <div class="bcgov-header" role="banner">
    <div class="container d-flex align-items-center py-2">
      <a href="/" class="d-flex align-items-center text-decoration-none" aria-label="BC Government — home">
        <img src="/assets/bc-gov-transportation-logo.png" alt="" width="auto" height="50px">
        <span class="visually-hidden">BC Transportation and Transit Public Forms</span>
      </a>
      <span class="ms-3 fs-5 ministry-name d-none d-sm-inline">__APP_NAME__</span>
    </div>
  </div>
`;

/**
 * Render the shared header into a target element.
 * @param {HTMLElement} target
 * @param {object} [opts]
 * @param {string} [opts.appName]

export function renderHeader(target, opts = {}) {
  if (!target) return;
  const appName = (opts.appName || 'BC Ministry of Transportation').replace(/[<>&"]/g, c => ({
    '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;',
  })[c]);
  target.innerHTML = HEADER_HTML.replace('__APP_NAME__', appName);
}

export default { renderHeader };
*/