/*
 * FEAT-0026 US-011 + US-013 — Public CMS page view.
 *
 * Responsibilities:
 *   1. Resolve `/{slug}` against `GET /api/public/v1/pages/{slug}`.
 *   2. On 404, resolve against `GET /api/public/v1/redirects/{slug}`
 *      and navigate to the target (US-013 AC1-AC3).
 *   3. On both 404s, delegate to the shared 404 view (US-013 AC5).
 *   4. Set page `<title>`, `<meta name="description">`, and
 *      `<link rel="canonical">` from the page payload (US-011 AC4/AC5).
 *   5. Inject the server-sanitised `body_html` into the page container.
 *
 * Security notes:
 *   - `body_html` has been sanitised twice already (US-016: sanitiser
 *     runs at save AND at read). No client-side sanitiser is applied
 *     to keep bundle-size zero and to keep the sanitiser policy
 *     server-side. `<img>` is stripped upstream per FEAT-0026
 *     remediation plan v2 (2026-07-16).
 *   - The attempted slug is NEVER written to the DOM unescaped.
 *   - Meta tag values are set via `setAttribute` (no innerHTML).
 */

import { fetchCmsPage, fetchCmsRedirect } from '../api.js';
import { CMS_SLUG_RE, CMS_SLUG_MAX } from '../constants.js';
import { showNotFound } from '../router.js';

const CANONICAL_BASE = ''; // relative canonical — the edge sets the host
const PAGE_VIEW_ID = 'cmsPageView';
const PAGE_CONTENT_ID = 'cmsPageContent';
const HEADING_ID = 'cmsPageHeading';
const HERO_ID = 'cmsPageHero';
const BREADCRUMB_CURRENT_ID = 'cmsBreadcrumbCurrent';


/**
 * Entry point invoked by the router when the SPA lands on `/{slug}`.
 * Sequence:
 *   1. Validate slug syntax (fail-fast to a 404 without server round-trip).
 *   2. Fetch the page.
 *   3. On null, try a redirect.
 *   4. On null, show 404.
 *
 * @param {string} slug
 */
export async function showCmsPageView(slug) {
  const article = document.getElementById(PAGE_CONTENT_ID);
  if (!article) return;

  _resetPage(article);

  if (!_isSyntacticallyValidSlug(slug)) {
    // Do NOT round-trip: the backend enforces the same regex and would
    // return 404. Fail-close on the client so bogus URLs never even
    // hit rate-limited endpoints.
    await showNotFound();
    return;
  }

  article.setAttribute('aria-busy', 'true');
  article.innerHTML = _skeleton();

  let page;
  try {
    page = await fetchCmsPage(slug);
  } catch {
    if (!_isCurrentSlug(slug)) return;
    // Network / 5xx / rate-limit: treat as 404 so we never spin.
    article.setAttribute('aria-busy', 'false');
    await showNotFound();
    return;
  }

  if (!_isCurrentSlug(slug)) return;

  if (page) {
    _renderPage(page, article);
    article.setAttribute('aria-busy', 'false');
    return;
  }

  // 404 branch — try the redirect resolver (US-013).
  let target;
  try {
    target = await fetchCmsRedirect(slug);
  } catch {
    target = null;
  }
  if (!_isCurrentSlug(slug)) return;
  article.setAttribute('aria-busy', 'false');

  if (target && _isSyntacticallyValidSlug(target) && target !== slug) {
    // Client-side navigation to the new slug; use replaceState so the
    // legacy URL does not stay in browser history (US-013 AC1/AC2).
    window.history.replaceState(null, '', `/${target}`);
    // Recurse into the SPA dispatcher via a synthetic popstate event so
    // the router runs its full path (main.js listens on popstate).
    // We import dispatch lazily to avoid a circular import.
    const { dispatch } = await import('../router.js');
    await dispatch();
    return;
  }

  await showNotFound();
}


// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------

function _renderPage(page, article) {
  const title = typeof page.title === 'string' ? page.title : '';
  const meta = typeof page.meta_description === 'string' ? page.meta_description : '';
  const slug = typeof page.slug === 'string' ? page.slug : '';
  // body_html is server-sanitised; injection is safe.
  const body = typeof page.body_html === 'string' ? page.body_html : '';

  // Document metadata — set via safe DOM APIs, never innerHTML.
  document.title = title
    ? `${title} — BC Government`
    : 'Public Forms — BC Government';
  _setMeta('description', meta);
  _setMeta('robots', ''); // clear any leftover noindex from 404 view
  _setLink('canonical', `${CANONICAL_BASE}/${slug}`);
  _setProp('og:type',        'article');
  _setProp('og:title',       title);
  _setProp('og:description', meta);
  _setProp('og:url',         `${CANONICAL_BASE}/${slug}`);

  const heading = document.getElementById(HEADING_ID);
  const breadcrumbCurrent = document.getElementById(BREADCRUMB_CURRENT_ID);
  const hero = document.getElementById(HERO_ID);
  if (heading) heading.textContent = title;
  if (breadcrumbCurrent) breadcrumbCurrent.textContent = title;
  if (hero) hero.removeAttribute('hidden');

  const bodyElement = document.createElement('div');
  bodyElement.className = 'cms-body';
  bodyElement.innerHTML = body;

  const footnote = document.createElement('div');
  footnote.className = 'cms-footnote';
  const backLink = document.createElement('a');
  backLink.className = 'btn btn-outline-primary btn-sm';
  backLink.href = '/';
  backLink.innerHTML = '<svg class="bi" viewBox="0 0 16 16" fill="currentColor" width="1em" height="1em" aria-hidden="true"><path fill-rule="evenodd" d="M15 8a.5.5 0 0 0-.5-.5H2.707l3.147-3.146a.5.5 0 1 0-.708-.708l-4 4a.5.5 0 0 0 0 .708l4 4a.5.5 0 0 0 .708-.708L2.707 8.5H14.5A.5.5 0 0 0 15 8"/></svg> Back to forms';
  footnote.append(backLink);
  article.replaceChildren(bodyElement, footnote);

  // Move keyboard focus to the heading so screen-readers announce the
  // new page (mirrors the pattern used by home.js / detail.js).
  if (heading) {
    heading.setAttribute('tabindex', '-1');
    heading.focus({ preventScroll: false });
  }
}

function _resetPage(article) {
  const heading = document.getElementById(HEADING_ID);
  const breadcrumbCurrent = document.getElementById(BREADCRUMB_CURRENT_ID);
  const hero = document.getElementById(HERO_ID);
  if (heading) heading.textContent = '';
  if (breadcrumbCurrent) breadcrumbCurrent.textContent = '';
  if (hero) hero.removeAttribute('hidden');
  article.setAttribute('aria-busy', 'true');
  article.innerHTML = _skeleton();
}

function _isCurrentSlug(slug) {
  const currentPath = window.location.pathname.replace(/\/+$/, '');
  return currentPath === `/${slug}`;
}

function _skeleton() {
  return (
    `<div class="placeholder-glow" aria-hidden="true">` +
    `<h1 class="placeholder col-6"></h1>` +
    `<p class="placeholder col-9"></p>` +
    `<p class="placeholder col-8"></p>` +
    `<p class="placeholder col-5"></p>` +
    `</div>`
  );
}


// ---------------------------------------------------------------------------
// Slug validation — mirrors public-backend/routes/cms.py::_slug_is_safe
// ---------------------------------------------------------------------------

function _isSyntacticallyValidSlug(slug) {
  if (typeof slug !== 'string') return false;
  if (slug.length < 1 || slug.length > CMS_SLUG_MAX) return false;
  return CMS_SLUG_RE.test(slug);
}


// ---------------------------------------------------------------------------
// SEO meta helpers (mirrors home.js so behaviour is consistent)
// ---------------------------------------------------------------------------

function _setMeta(name, value) {
  let el = document.head.querySelector(`meta[name="${name}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute('name', name);
    document.head.appendChild(el);
  }
  el.setAttribute('content', value || '');
}

function _setProp(prop, value) {
  let el = document.head.querySelector(`meta[property="${prop}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute('property', prop);
    document.head.appendChild(el);
  }
  el.setAttribute('content', value || '');
}

function _setLink(rel, href) {
  let el = document.head.querySelector(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement('link');
    el.setAttribute('rel', rel);
    document.head.appendChild(el);
  }
  el.setAttribute('href', href || '');
}
