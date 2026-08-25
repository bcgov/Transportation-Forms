/*
 * Detail view — US-003, redesigned by FEAT-0028 US-006.
 *
 * Cache-first from history.state when navigated from the list (AC1).
 * Falls back to GET /forms/{form_number} on direct nav, refresh, or
 * mismatched state (AC2/AC3/AC15).
 *
 * Layout: a static hero shell in index.html (US-006 P14) plus a two-column
 * lifted-card body rendered here — main card (description + keywords) and a
 * non-sticky metadata sidebar (CONFLICT-22) carrying the primary action and
 * the Share control.
 */

import { fetchJson, ApiError, downloadFormFile } from '../api.js';
import { escapeHtml, formatDate, formatDateTime, formatFileType, truncate,
         icon, fileTypeIcon, safeHttpUrl } from '../utils.js';
import { SITE_NAME, ALERT_DISMISS_MS } from '../constants.js';
import { showApiAlert, showAlert } from '../ui-states.js';

let _delegated = false;

export async function showDetailView(formNumber) {
  const article = document.getElementById('detailContent');
  if (!article) return;
  _wireOnce(article);
  article.setAttribute('aria-busy', 'true');
  article.innerHTML = _skeleton();
  _resetHero();

  // AC1 cache-first: history.state populated by the list page.
  const cached = _readState();
  if (cached && cached.form_number === formNumber) {
    _render(article, cached);
    article.setAttribute('aria-busy', 'false');
    // We still hydrate any missing fields (e.g., full keywords) in the background.
    _fetchFresh(formNumber, article);
    return;
  }

  await _fetchFresh(formNumber, article);
}

// Delegated once on the static container so a re-render (cache-first then
// fresh) can never double-bind or lose the handler.
function _wireOnce(article) {
  if (_delegated) return;
  _delegated = true;
  article.addEventListener('click', e => {
    const trigger = e.target.closest('[data-action]');
    if (!trigger) return;
    const num = trigger.dataset.formNumber || '';
    if (!num) return;
    if (trigger.dataset.action === 'download') downloadFormFile(num);
    else if (trigger.dataset.action === 'share') _handleShare(num);
  });
}

/* ─── Share (US-006 AC27/AC28) ─────────────────────────────────────────────
 * Mirrors the staff-portal share behaviour: canonical deep link with no query
 * string, then a manual-copy fallback so the action never fails silently.
 */

function _canonicalUrl(formNumber) {
  return `${window.location.origin}/forms/${encodeURIComponent(formNumber)}`;
}

async function _handleShare(formNumber) {
  const url = _canonicalUrl(formNumber);
  const clipboard = navigator.clipboard;
  if (clipboard && typeof clipboard.writeText === 'function') {
    try {
      await clipboard.writeText(url);
      showAlert('Link copied to clipboard', 'success', { dismissMs: ALERT_DISMISS_MS.SUCCESS });
      return;
    } catch {
      // Fall through to the manual-copy fallback (AC28).
    }
  }
  // dismissMs 0 keeps the URL on screen until the visitor dismisses it.
  showAlert(`Unable to copy link. Please copy manually: ${url}`, 'warning', { dismissMs: 0 });
}


function _readState() {
  const s = window.history.state;
  if (!s || typeof s !== 'object') return null;
  // Tolerate older / newer SPA versions: require at minimum form_number+title.
  if (!s.form_number || !s.title) return null;
  return s;
}

async function _fetchFresh(formNumber, article) {
  try {
    const { data } = await fetchJson(`/forms/${encodeURIComponent(formNumber)}`);
    _render(article, data);
    article.setAttribute('aria-busy', 'false');
    // Cache for future back-nav
    window.history.replaceState(data, '', window.location.pathname + window.location.search);
  } catch (err) {
    article.setAttribute('aria-busy', 'false');
    if (err instanceof ApiError && err.status === 404) {
      _render404(article, formNumber);
      return;
    }
    showApiAlert(err, () => _fetchFresh(formNumber, article));
  }
}

function _skeleton() {
  return `
    <div class="skeleton-card sk-title"></div>
    <div class="skeleton-card sk-subtitle"></div>
    <div class="skeleton-card sk-body"></div>
  `;
}

function _render(article, f) {
  if (!f) return;

  // Per-page meta (AC5) + US-005 tab-title format.
  // Format: `<form_number>: <form_title> | <site_name>`.
  // Fallback when the form title is missing/whitespace: `<form_number> | <site_name>`
  // (US-005 AC4). We NEVER emit "undefined" / "null" / stray separators.
  const rawTitle = typeof f.title === 'string' ? f.title.trim() : '';
  const num = f.form_number || '';
  const pageTitle = num
    ? (rawTitle ? `${num}: ${rawTitle} | ${SITE_NAME}` : `${num} | ${SITE_NAME}`)
    : (rawTitle ? `${rawTitle} | ${SITE_NAME}` : SITE_NAME);
  document.title = pageTitle;
  _setMeta('description', truncate(f.description || '', 160));
  _setLink('canonical', window.location.origin + `/forms/${encodeURIComponent(f.form_number)}`);
  _setOgMeta(f);
  _setJsonLd(f);

  const ft = formatFileType(f.file_type);
  const ftKey = String(f.file_type || '').toLowerCase();
  const eff = formatDate(f.effective_date);
  const upd = formatDateTime(f.updated_at);
  const linkUrl = safeHttpUrl(f.url);
  // US-005 P7/BR-007 — positive file evidence: a non-empty file_type on a row
  // that is not link-source ("URL"). Covers form_source "Download" and legacy
  // null rows carrying file metadata (FEAT-0029 E2). A "no source" form (no
  // valid url and no positive file evidence) hides both the file-type display
  // and the primary action (AC6/AC7); the unsafe-url/file case still downloads.
  const isUrlSource = (f.form_source || '').trim().toUpperCase() === 'URL';
  const hasFileEvidence = !!(f.file_type && String(f.file_type).trim()) && !isUrlSource;

  _fillHero(f);

  // Main card — Description and Keywords only (US-006 AC14 / CONFLICT-17).
  // Each section is omitted whole when its value is absent (AC15).
  const descSection = f.description
    ? `<section>
         <h2 class="detail-section-title h5">Description</h2>
         <p class="detail-description">${escapeHtml(f.description)}</p>
       </section>`
    : '';
  const keywords = Array.isArray(f.keywords) ? f.keywords.filter(Boolean) : [];
  const keywordSection = keywords.length
    ? `<section class="mt-4">
         <h2 class="detail-section-title h5">Keywords</h2>
         <p class="mb-0">${keywords.map(k => `<span class="keyword-chip">${escapeHtml(k)}</span>`).join('')}</p>
       </section>`
    : '';

  // Sidebar file-type row — mirrors the card treatment (US-004 AC16/BR-007):
  // the chain-link pill marks a link-source form, the typed pill a file-source
  // form, and a "no source" form shows none at all (US-005 AC6).
  let pill = '';
  if (linkUrl) {
    pill = `<span class="file-type-pill link">${icon('link')} Link</span>`;
  } else if (hasFileEvidence) {
    pill = `<span class="file-type-pill ${escapeHtml(ftKey)}">${fileTypeIcon(ftKey)} ${escapeHtml(ft || 'FILE')}</span>`;
  }

  // Primary action — label matches the results card exactly (AC22/AC23).
  let action = '';
  if (linkUrl) {
    action = `<a class="btn-download btn-download--block" href="${escapeHtml(linkUrl)}" target="_blank"
                 rel="noopener noreferrer" data-no-router="1"
                 aria-label="Open link for ${escapeHtml(num)} (opens in new tab)">${icon('externalLink')} Form Link</a>`;
  } else if (hasFileEvidence && num) {
    action = `<button type="button" class="btn-download btn-download--block" data-action="download"
                 data-form-number="${escapeHtml(num)}"
                 aria-label="Download ${escapeHtml(num)}${ft ? ` (${escapeHtml(ft)})` : ''}">${icon('download')} Download</button>`;
  }
  const share = num
    ? `<button type="button" class="btn btn-outline-secondary w-100 d-flex align-items-center justify-content-center gap-2 rounded-3 fw-semibold"
                 data-action="share" data-form-number="${escapeHtml(num)}"
                 aria-label="Copy the link to ${escapeHtml(num)}">${icon('share')} Share this form</button>`
    : '';

  article.innerHTML = `
    <div class="row g-4">
      <div class="col-lg-8">
        <div class="detail-main-card">
          ${descSection}
          ${keywordSection}
        </div>
      </div>
      <div class="col-lg-4">
        <aside class="detail-sidebar-card" aria-label="Form details">
          <p class="detail-sidebar-title">${icon('infoCircle')} Form details</p>
          <dl class="meta-list">
            ${_metaRow('Form number', num ? `<span class="form-card__num">${escapeHtml(num)}</span>` : '', 'meta-num')}
            ${_metaRow('Business area', f.business_area
              ? `<span class="ba-badge" title="Business Area: ${escapeHtml(f.business_area)}">${escapeHtml(f.business_area)}</span>`
              : '')}
            ${_metaRow('File type', pill)}
            ${_metaRow('Effective date', eff
              ? `<time datetime="${escapeHtml(f.effective_date || '')}">${escapeHtml(eff)}</time>` : '')}
            ${_metaRow('Last updated', upd
              ? `<time datetime="${escapeHtml(f.updated_at || '')}">${escapeHtml(upd)}</time>` : '')}
          </dl>
          ${action || share ? `<div class="detail-actions">${action}${share}</div>` : ''}
        </aside>
      </div>
    </div>
  `;
}

// AC21 — an absent value omits the whole row, leaving no orphaned label.
function _metaRow(label, valueHtml, valueClass = '') {
  if (!valueHtml) return '';
  return `<div class="meta-row">
      <dt class="meta-key">${escapeHtml(label)}</dt>
      <dd class="meta-val${valueClass ? ` ${valueClass}` : ''}">${valueHtml}</dd>
    </div>`;
}

// AC2/AC6 — fill the static hero shell; an absent value hides its element.
function _fillHero(f) {
  document.getElementById('detailHero')?.removeAttribute('hidden');
  const numEl = document.getElementById('detailFormNumber');
  if (numEl) {
    numEl.textContent = f.form_number || '';
    numEl.toggleAttribute('hidden', !f.form_number);
  }
  const titleEl = document.getElementById('detailHeading');
  if (titleEl) {
    const title = typeof f.title === 'string' ? f.title.trim() : '';
    titleEl.textContent = title;
    titleEl.toggleAttribute('hidden', !title);
  }
}

// Clear the hero while loading so a previously viewed form is never shown
// against the incoming one.
function _resetHero() {
  _fillHero({});
}

function _render404(article, formNumber) {
  document.title = 'Form not found — Public Forms — BC Government';
  _setMeta('robots', 'noindex');
  // AC32 — hide the hero so no stale number/title from a prior form remains.
  document.getElementById('detailHero')?.setAttribute('hidden', '');
  article.innerHTML = `
    <div class="detail-main-card">
      <h1>Form not found</h1>
      <p>The form ${escapeHtml(formNumber)} could not be found, or it is not currently published.</p>
      <p class="mb-0"><a href="/" class="btn btn-primary">&larr; Back to all forms</a></p>
    </div>
  `;
}

function _setMeta(name, content) {
  let el = document.head.querySelector(`meta[name="${name}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute('name', name);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content || '');
}

function _setOgMeta(f) {
  const url = window.location.origin + `/forms/${encodeURIComponent(f.form_number)}`;
  const desc = truncate(f.description || '', 160);
  _setProp('og:title', f.title || '');
  _setProp('og:description', desc);
  _setProp('og:type', 'website');
  _setProp('og:url', url);
  _setProp('og:site_name', 'BC Government Public Forms');
  _setMeta('twitter:card', 'summary');
  _setMeta('twitter:title', f.title || '');
  _setMeta('twitter:description', desc);
}

function _setProp(prop, content) {
  let el = document.head.querySelector(`meta[property="${prop}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute('property', prop);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content || '');
}

function _setLink(rel, href) {
  let el = document.head.querySelector(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement('link');
    el.setAttribute('rel', rel);
    document.head.appendChild(el);
  }
  el.setAttribute('href', href);
}

function _setJsonLd(f) {
  // AC14 — never include internal identifiers.
  const payload = {
    '@context': 'https://schema.org',
    '@type': 'DigitalDocument',
    name: f.title || '',
    description: truncate(f.description || '', 280),
    identifier: f.form_number || '',   // US-008 AC8
    dateModified: f.updated_at || '',
    inLanguage: 'en-CA',
    url: window.location.origin + `/forms/${encodeURIComponent(f.form_number)}`,
  };
  let el = document.head.querySelector('script[type="application/ld+json"][data-page="detail"]');
  if (!el) {
    el = document.createElement('script');
    el.type = 'application/ld+json';
    el.dataset.page = 'detail';
    document.head.appendChild(el);
  }
  // Neutralise </ inside JSON-LD content (defence-in-depth, mirrors backend OG).
  el.textContent = JSON.stringify(payload).replace(/<\//g, '<\\/');
}
