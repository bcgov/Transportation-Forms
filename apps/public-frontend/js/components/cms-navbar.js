/*
 * FEAT-0026 US-012 — CMS-driven public navbar.
 *
 * Fetches nav-visible CMS pages from `GET /api/public/v1/pages` on
 * boot and renders them into the `#cmsNavList` container as a
 * Bootstrap nav-pill list. Filtering (`show_in_nav = true`) and
 * ordering are already applied by the backend view (see
 * ``public_cms_pages_v`` + the route's ``nav_order ASC NULLS LAST,
 * title ASC`` sort), so this module only escapes and renders.
 *
 * Behaviour on failure: the navbar stays hidden. We do not surface an
 * alert — the CMS is optional decoration on top of the forms catalogue
 * and must never block the primary flow.
 */

import { fetchCmsNavPages } from '../api.js';
import { escapeHtml } from '../utils.js';

const NAV_ID = 'cmsNav';
const LIST_ID = 'cmsNavList';

/**
 * Fetch and render the CMS nav pages into the shared header nav.
 * Safe to call more than once; each call replaces the current
 * contents (no incremental updates).
 */
export async function renderCmsNav() {
  const nav = document.getElementById(NAV_ID);
  const list = document.getElementById(LIST_ID);
  if (!nav || !list) return;

  let pages;
  try {
    pages = await fetchCmsNavPages();
  } catch {
    // Fail-quiet: the CMS is decorative for the portal.
    nav.setAttribute('hidden', '');
    list.innerHTML = '';
    return;
  }

  if (!pages.length) {
    nav.setAttribute('hidden', '');
    list.innerHTML = '';
    return;
  }

  const items = pages
    .map(p => {
      const slug = typeof p.slug === 'string' ? p.slug : '';
      const title = typeof p.title === 'string' ? p.title : '';
      if (!slug || !title) return '';
      const safeSlug = escapeHtml(slug);
      const safeTitle = escapeHtml(title);
      return (
        `<li class="nav-item">` +
        `<a class="nav-link" href="/${safeSlug}">${safeTitle}</a>` +
        `</li>`
      );
    })
    .join('');

  list.innerHTML = items;
  nav.removeAttribute('hidden');
  _markActive();
}

/**
 * Toggle the ``active`` class on the link whose ``href`` matches the
 * current location. Called on route change so the navbar always
 * reflects the visible page.
 */
export function _markActive() {
  const list = document.getElementById(LIST_ID);
  if (!list) return;
  const here = window.location.pathname.replace(/\/$/, '') || '/';
  list.querySelectorAll('a').forEach(a => {
    const target = (a.getAttribute('href') || '').replace(/\/$/, '') || '/';
    if (target === here) a.classList.add('active');
    else a.classList.remove('active');
  });
}
