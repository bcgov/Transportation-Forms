/*
 * Detail view — US-003.
 *
 * Cache-first from history.state when navigated from the list (AC1).
 * Falls back to GET /forms/{form_number} on direct nav, refresh, or
 * mismatched state (AC2/AC3/AC15).
 */

import { fetchJson, ApiError, downloadFormFile } from '../api.js';
import { escapeHtml, formatDate, formatDateTime, truncate } from '../utils.js';
import { SITE_NAME } from '../constants.js';
import { showApiAlert, showAlert } from '../ui-states.js';
import { baInfo, fileTypeInfo } from '../components/card.js';
import { showNotFoundView } from './not-found.js';

export async function showDetailView(formNumber) {
  const article = document.getElementById('detailContent');
  if (!article) return;
  article.setAttribute('aria-busy', 'true');
  article.innerHTML = _skeleton();

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

  const ft = fileTypeInfo(f.file_type);
  const ba = baInfo(f.business_area);
  const eff = formatDate(f.effective_date);
  const upd = formatDateTime(f.updated_at);
  const numDisplay = f.form_number || '—';

  const keywordChips = Array.isArray(f.keywords) && f.keywords.length
    ? `<h2 class="detail-section-title">Keywords</h2>
       <p class="mb-0">${f.keywords.map(k => `<span class="keyword-chip-v2"><i class="bi bi-tag" aria-hidden="true"></i> ${escapeHtml(k)}</span>`).join('')}</p>`
    : '';

  article.innerHTML = `
    <div class="detail-hero">
      <div class="container">
        <a class="back-link" href="/"><i class="bi bi-arrow-left" aria-hidden="true"></i> Back to results</a>
        <p class="detail-num">${escapeHtml(numDisplay)}</p>
        <h1 id="detailHeading">${escapeHtml(f.title || '')}</h1>
      </div>
    </div>

    <div class="detail-content-wrap">
      <div class="container">
        <div class="row g-4">
          <div class="col-lg-8">
            <div class="detail-main-card">
              <h2 class="detail-section-title">Description</h2>
              <p class="mb-0">${f.description ? escapeHtml(f.description) : '<span class="text-muted">No description is available for this form.</span>'}</p>
              ${keywordChips}
              <div class="detail-help-notice">
                <i class="bi bi-info-circle" aria-hidden="true"></i>
                <span>Download the form, complete it, and submit it as directed in the form’s instructions. Contact the responsible office if you need assistance.</span>
              </div>
            </div>
          </div>

          <aside class="col-lg-4">
            <div class="detail-sidebar-card">
              <p class="sidebar-title">Form details</p>
              <div class="meta-row">
                <span class="meta-key">Form number</span>
                <span class="meta-val form-num">${escapeHtml(numDisplay)}</span>
              </div>
              ${f.business_area ? `<div class="meta-row">
                <span class="meta-key">Business area</span>
                <span class="meta-val"><span class="ba-badge ${ba.badgeClass} ba-badge-lg"><i class="bi ${ba.icon}" aria-hidden="true"></i> ${escapeHtml(ba.label)}</span></span>
              </div>` : ''}
              <div class="meta-row">
                <span class="meta-key">File type</span>
                <span class="meta-val"><span class="file-type-pill${ft.cls ? ` ${ft.cls}` : ''}"><i class="bi ${ft.icon}" aria-hidden="true"></i> ${escapeHtml(ft.label)}</span></span>
              </div>
              ${eff ? `<div class="meta-row">
                <span class="meta-key">Effective date</span>
                <span class="meta-val"><time datetime="${escapeHtml(f.effective_date || '')}">${escapeHtml(eff)}</time></span>
              </div>` : ''}
              ${upd ? `<div class="meta-row">
                <span class="meta-key">Last updated</span>
                <span class="meta-val"><time datetime="${escapeHtml(f.updated_at || '')}">${escapeHtml(upd)}</time></span>
              </div>` : ''}
              <hr class="detail-divider">
              ${f.form_number ? `<button type="button" class="btn-download-lg" data-action="download" aria-label="Download ${escapeHtml(numDisplay)}${ft.label ? ` (${escapeHtml(ft.label)})` : ''}">
                <i class="bi bi-download" aria-hidden="true"></i> Download form
              </button>` : ''}
              <button type="button" class="btn btn-outline-secondary detail-share-btn" data-action="share">
                <i class="bi bi-share" aria-hidden="true"></i> Share link
              </button>
            </div>
          </aside>
        </div>
      </div>
    </div>
  `;

  article.querySelector('[data-action="download"]')?.addEventListener('click', () => {
    if (f.form_number) downloadFormFile(f.form_number);
  });

  article.querySelector('[data-action="share"]')?.addEventListener('click', () => {
    _shareLink();
  });
}

/** Copy the current detail URL to the clipboard (US-010). */
async function _shareLink() {
  const url = window.location.href;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(url);
      showAlert('Link copied to clipboard', 'success', { dismissMs: 3000 });
      return;
    }
    throw new Error('clipboard unavailable');
  } catch {
    // Fallback: surface the URL so the user can copy it manually.
    showAlert(`Copy this link: ${url}`, 'info', { dismissMs: 8000 });
  }
}

function _render404(article, formNumber) {
  // US-009 AC12 / US-011 BR-002 — reuse the shared 404 view rather than a
  // form-specific message embedded in the detail container.
  document.getElementById('detailView')?.setAttribute('hidden', '');
  const nf = document.getElementById('notFoundView');
  if (nf) nf.removeAttribute('hidden');
  showNotFoundView();
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
