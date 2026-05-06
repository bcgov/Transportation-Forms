/*
 * Detail view — US-003.
 *
 * Cache-first from history.state when navigated from the list (AC1).
 * Falls back to GET /forms/{form_number} on direct nav, refresh, or
 * mismatched state (AC2/AC3/AC15).
 */

import { fetchJson, ApiError, downloadFormFile } from '../api.js';
import { escapeHtml, formatDate, formatDateTime, formatFileType, truncate } from '../utils.js';
import { showApiAlert } from '../ui-states.js';

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
    <div class="skeleton-card" style="height:2rem;width:60%;"></div>
    <div class="skeleton-card" style="height:1rem;width:40%;"></div>
    <div class="skeleton-card" style="height:8rem;"></div>
  `;
}

function _render(article, f) {
  if (!f) return;

  // Per-page meta (AC5)
  const pageTitle = `${f.title} (${f.form_number}) — Public Forms — BC Government`;
  document.title = pageTitle;
  _setMeta('description', truncate(f.description || '', 160));
  _setLink('canonical', window.location.origin + `/forms/${encodeURIComponent(f.form_number)}`);
  _setOgMeta(f);
  _setJsonLd(f);

  const ft = formatFileType(f.file_type);
  const eff = formatDate(f.effective_date);
  const upd = formatDateTime(f.updated_at);

  const keywordChips = Array.isArray(f.keywords) && f.keywords.length
    ? `<p class="mt-3">${f.keywords.map(k => `<span class="keyword-chip">${escapeHtml(k)}</span>`).join('')}</p>`
    : '';

  article.innerHTML = `
    <header class="mb-3">
      <p class="text-muted mb-1">${escapeHtml(f.business_area || '')}</p>
      <h1 id="detailHeading" class="h2 mb-2">${escapeHtml(f.title || '')}</h1>
      <p class="mb-0">
        <span class="form-card__num">${escapeHtml(f.form_number || '—')}</span>
        ${ft ? `<span class="badge ms-2">${escapeHtml(ft)}</span>` : ''}
      </p>
    </header>

    ${f.description ? `<section><p>${escapeHtml(f.description)}</p></section>` : ''}

    ${keywordChips}

    <dl class="row mt-3">
      ${eff ? `<dt class="col-sm-3">Effective</dt><dd class="col-sm-9"><time datetime="${escapeHtml(f.effective_date || '')}">${escapeHtml(eff)}</time></dd>` : ''}
      ${upd ? `<dt class="col-sm-3">Last updated</dt><dd class="col-sm-9"><time datetime="${escapeHtml(f.updated_at || '')}">${escapeHtml(upd)}</time></dd>` : ''}
    </dl>

    <div class="mt-4">
      <button type="button" class="btn btn-primary" data-action="download" aria-label="Download ${escapeHtml(f.form_number || '')}${ft ? ` (${escapeHtml(ft)})` : ''}">
        Download form
      </button>
    </div>
  `;

  article.querySelector('[data-action="download"]')?.addEventListener('click', () => {
    if (f.form_number) downloadFormFile(f.form_number);
  }, { once: true });
}

function _render404(article, formNumber) {
  document.title = 'Form not found — Public Forms — BC Government';
  _setMeta('robots', 'noindex');
  article.innerHTML = `
    <h1>Form not found</h1>
    <p>The form ${escapeHtml(formNumber)} could not be found, or it is not currently published.</p>
    <p><a href="/" class="btn btn-primary">&larr; Back to all forms</a></p>
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
