/*
 * Home view — US-001 (search + recent feed) + US-005 (filter/sort/page/view-all)
 *           + US-006 (loading/empty/error/rate-limit states).
 */

import { fetchJson, ApiError, downloadFormFile } from '../api.js';
import {
  PAGE_SIZE, VIEW_ALL_CAP, SEARCH_DEBOUNCE_MS, Q_MAX_LENGTH,
  DEFAULT_SORT_FIELD, DEFAULT_SORT_ORDER, HISTORY_STATE_CAP_BYTES,
} from '../constants.js';
import { escapeHtml, formatDate, formatFileType, byteLength,
         icon as _icon, fileTypeIcon as _fileTypeIcon, safeHttpUrl as _safeUrl } from '../utils.js';
import { getState, setUrl, rememberScroll, restoreScroll, announce } from '../state.js';
import { showSkeleton, clearBusy, showEmpty, hideEmpty, showApiAlert } from '../ui-states.js';

let _wired = false;
let _debounceTimer = null;
let _abortCtl = null;
let _baCacheLoaded = false;

export async function showHomeView() {
  document.title = 'Public Forms — BC Government';
  _resetHomeMeta();
  if (!_wired) _wireOnce();
  await _loadBusinessAreas();
  _hydrateControls();
  await _refresh({ replaceUrl: false });
  restoreScroll('home');
}

/**
 * Restore the home-page SEO meta tags that detail.js may have overridden.
 * Canonical points to bare `/`; OG/Twitter carry the static home description.
 * US-008 AC4/AC6/AC10.
 */
function _resetHomeMeta() {
  _setMeta('description', 'Browse and download BC Government transportation forms.');
  _setMeta('robots', '');        // remove noindex if coming from a 404
  _setLink('canonical', '/');
  _setProp('og:type',        'website');
  _setProp('og:title',       'Public Forms — BC Government');
  _setProp('og:description', 'Browse and download BC Government transportation forms.');
  _setProp('og:url',         '/');
  _setProp('og:site_name',   'BC Government Public Forms');
  _setMeta('twitter:card',        'summary');
  _setMeta('twitter:title',       'Public Forms — BC Government');
  _setMeta('twitter:description', 'Browse and download BC Government transportation forms.');
  // Remove per-page JSON-LD injected by the detail view.
  document.head.querySelector('script[type="application/ld+json"][data-page="detail"]')?.remove();
}

function _wireOnce() {
  _wired = true;

  const input = document.getElementById('searchInput');
  if (input) {
    input.addEventListener('input', () => {
      if (_debounceTimer) clearTimeout(_debounceTimer);
      _debounceTimer = setTimeout(() => _applySearch(input), SEARCH_DEBOUNCE_MS);
    });
    // US-002 AC4/E1 — Enter runs the search immediately, cancelling any
    // pending debounce so exactly one refresh performs the submitted term.
    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      if (_debounceTimer) { clearTimeout(_debounceTimer); _debounceTimer = null; }
      _applySearch(input);
    });
  }

  document.getElementById('filterBA')?.addEventListener('change', (e) => {
    const state = getState();
    state.f = e.target.value || '';
    state.p = 1;
    setUrl(state, 'replace');
    _refresh();
  });

  document.getElementById('sortField')?.addEventListener('change', (e) => {
    const state = getState();
    state.s = e.target.value || '';
    state.p = 1;
    setUrl(state, 'replace');
    _refresh();
  });

  document.getElementById('sortOrder')?.addEventListener('change', (e) => {
    const state = getState();
    state.o = e.target.value || '';
    state.p = 1;
    setUrl(state, 'replace');
    _refresh();
  });

  document.getElementById('viewAllToggle')?.addEventListener('click', () => {
    const state = getState();
    state.view = state.view === 'all' ? '' : 'all';   // US-005 AC9/AC11
    state.p = 1;
    setUrl(state, 'replace');
    _hydrateControls();   // US-003 AC2 — sync the toggle's aria-pressed to state
    _refresh();
  });

  document.getElementById('clearFiltersBtn')?.addEventListener('click', () => {
    setUrl({ q: '', f: '', s: '', o: '', p: 1, view: '' }, 'replace');
    _hydrateControls();
    _refresh();
  });

  document.getElementById('pagerList')?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-page]');
    if (!btn) return;
    e.preventDefault();
    const p = parseInt(btn.dataset.page, 10);
    if (!Number.isFinite(p) || p < 1) return;
    rememberScroll('home');
    const state = getState();
    state.p = p;
    setUrl(state, 'replace');
    _refresh();
  });

  // US-003 AC4-AC10 — presentational-only list/grid toggle. Switching view
  // never touches URL state, storage, or the API; it only toggles a layout
  // class on #resultsList and the active/aria-pressed state of the buttons.
  document.getElementById('viewListBtn')?.addEventListener('click', () => _setViewMode('list'));
  document.getElementById('viewGridBtn')?.addEventListener('click', () => _setViewMode('grid'));

  // US-003 AC17 — delegated Download handler for the redesigned cards. The
  // form-number link and "View details" link are native <a href="/forms/…">
  // anchors handled by the global SPA router; only the Download <button>
  // (which is not an anchor) is intercepted here.
  document.getElementById('resultsList')?.addEventListener('click', (e) => {
    const dl = e.target.closest('button[data-action="download"]');
    if (!dl || dl.disabled) return;
    e.preventDefault();
    const num = dl.dataset.formNumber;
    if (num) downloadFormFile(num);
  });
}

/**
 * Toggle the results layout between single-column list and responsive grid
 * (US-003 AC5-AC10). Presentational only: no re-fetch, no URL/storage change.
 * Not persisted — every page load and re-render defaults to list view.
 */
function _setViewMode(mode) {
  const isGrid = mode === 'grid';
  document.getElementById('resultsList')?.classList.toggle('is-grid', isGrid);
  const listBtn = document.getElementById('viewListBtn');
  const gridBtn = document.getElementById('viewGridBtn');
  listBtn?.classList.toggle('active', !isGrid);
  gridBtn?.classList.toggle('active', isGrid);
  listBtn?.setAttribute('aria-pressed', String(!isGrid));
  gridBtn?.setAttribute('aria-pressed', String(isGrid));
}

/**
 * Apply the current search-input value to URL state and refresh (US-002 AC4/AC5).
 * Shared by the debounced input handler and the Enter-key handler so both paths
 * behave identically. Blank/whitespace-only input clears the term and restores
 * the default sort (US-005 BR-003).
 */
function _applySearch(input) {
  const state = getState();
  state.q = (input.value || '').trim().slice(0, Q_MAX_LENGTH);
  state.p = 1;                            // US-005 AC12
  // After a search, default sort flips to title/asc (US-005 BR-003)
  if (state.q && !state.s) { state.s = 'title'; state.o = 'asc'; }
  if (!state.q) { state.s = ''; state.o = ''; }   // back to default
  setUrl(state, 'replace');
  _refresh({ replaceUrl: false });
}

function _hydrateControls() {
  const state = getState();
  const input = document.getElementById('searchInput');
  if (input && document.activeElement !== input) input.value = state.q;
  const filterBA = document.getElementById('filterBA');
  if (filterBA) {
    filterBA.value = state.f || '';
    // US-002 AC13 — an unknown/stale business-area value must not remain
    // selected nor leave the control in a blank (selectedIndex -1) state;
    // fall back to the leading "Business Areas:" option.
    if (filterBA.selectedIndex === -1) filterBA.value = '';
  }
  const sf = document.getElementById('sortField');
  if (sf) sf.value = state.s || DEFAULT_SORT_FIELD;
  const so = document.getElementById('sortOrder');
  if (so) so.value = state.o || DEFAULT_SORT_ORDER;
  const toggle = document.getElementById('viewAllToggle');
  if (toggle) toggle.setAttribute('aria-pressed', state.view === 'all' ? 'true' : 'false');
}

async function _loadBusinessAreas() {
  if (_baCacheLoaded) return;
  const select = document.getElementById('filterBA');
  if (!select) return;
  try {
    const { data } = await fetchJson('/business-areas');
    const items = (data && data.items) || [];
    if (items.length === 0) {
      // US-002 AC12 — hide the control (and its divider) when no areas exist.
      select.disabled = true;
      select.hidden = true;
      const divider = select.nextElementSibling;
      if (divider && divider.classList.contains('filter-divider')) divider.hidden = true;
      return;
    }
    items.sort((a, b) => String(a.name).localeCompare(String(b.name), 'en-CA'));
    for (const ba of items) {
      const opt = document.createElement('option');
      opt.value = ba.name;
      opt.textContent = ba.name;
      select.appendChild(opt);
    }
    _baCacheLoaded = true;
    _hydrateControls();    // re-apply current state.f selection
  } catch (err) {
    // Soft-fail: filter remains unpopulated; user can still search/sort.
    if (err && err.kind !== 'abort') {
      // Don't pop a banner for this background fetch; log to console only.
      // eslint-disable-next-line no-console
      console.warn('Failed to load business areas:', err.message);
    }
  }
}

async function _refresh() {
  if (_abortCtl) _abortCtl.abort();
  _abortCtl = new AbortController();

  const state = getState();
  const isViewAll = state.view === 'all';
  const limit = isViewAll ? VIEW_ALL_CAP : PAGE_SIZE;
  const offset = isViewAll ? 0 : (state.p - 1) * PAGE_SIZE;

  // Apply effective sort (default updated_at/desc on first paint).
  const effS = state.s || DEFAULT_SORT_FIELD;
  const effO = state.o || DEFAULT_SORT_ORDER;

  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  if (state.f) params.set('f', state.f);
  params.set('s', effS);
  params.set('o', effO);
  params.set('limit', String(limit));
  params.set('offset', String(offset));

  showSkeleton(Math.min(limit, PAGE_SIZE));
  try {
    const { data } = await fetchJson(`/forms?${params.toString()}`, { signal: _abortCtl.signal });
    _renderList(data, { state, limit, offset, isViewAll });
  } catch (err) {
    clearBusy();
    if (err instanceof ApiError && err.kind === 'abort') return;
    // US-001 AC9 — keep prior cards rendered if any.
    showApiAlert(err, () => _refresh());
  }
}

function _renderList(data, { state, limit, offset, isViewAll }) {
  clearBusy();
  const total = (data && data.total) || 0;
  const items = (data && data.items) || [];

  // US-005 AC8 — out-of-range page falls back to last page.
  if (!isViewAll && total > 0 && offset >= total) {
    const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const s = getState();
    s.p = lastPage;
    setUrl(s, 'replace');
    return _refresh();
  }

  const list = document.getElementById('resultsList');
  if (!list) return;

  if (items.length === 0) {
    showEmpty();
    announce(state.q ? `Showing 0 results for "${state.q}"` : 'Showing 0 results');
    document.getElementById('paginator')?.setAttribute('hidden', '');
    document.getElementById('viewAllNotice')?.setAttribute('hidden', '');
    return;
  }
  hideEmpty();

  // US-003 AC11 — cards are standard <article.form-card-v2> rendered directly
  // by the view logic (the <form-card> custom element is no longer used).
  list.innerHTML = items.map((item, i) => _cardHtml(item, i)).join('');

  announce(state.q
    ? `Showing ${items.length} of ${total} results for "${state.q}", page ${state.p}`
    : `Showing ${items.length} of ${total} results, page ${state.p}`);

  // View-all overflow notice (US-005 AC10)
  const notice = document.getElementById('viewAllNotice');
  if (notice) {
    if (isViewAll && total > VIEW_ALL_CAP) {
      notice.textContent = `Showing the first ${VIEW_ALL_CAP} of ${total} results. Refine your search to see more.`;
      notice.removeAttribute('hidden');
    } else {
      notice.setAttribute('hidden', '');
    }
  }

  if (isViewAll) {
    document.getElementById('paginator')?.setAttribute('hidden', '');
  } else {
    _renderPager(state.p, total);
  }
}

function _renderPager(currentPage, total) {
  const pager = document.getElementById('paginator');
  const list = document.getElementById('pagerList');
  if (!pager || !list) return;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (lastPage <= 1) { pager.setAttribute('hidden', ''); return; }

  pager.removeAttribute('hidden');
  const items = [];

  // Numbered page link — the digit is the visible + accessible text.
  function pageLink(page, label, { active = false } = {}) {
    const cls = `page-item${active ? ' active' : ''}`;
    return `<li class="${cls}">
      <a class="page-link" href="?p=${page}" data-page="${page}" data-no-router="1"
         ${active ? 'aria-current="page"' : ''}>${escapeHtml(label)}</a>
    </li>`;
  }

  // US-003 AC21 — First/Prev/Next/Last controls use chevron icons in place of
  // the «/‹/›/» glyphs. The icon is decorative; the accessible name is carried
  // by aria-label, and the disabled state is preserved at the extremes.
  function navLink(page, iconName, ariaLabel, { disabled = false } = {}) {
    const cls = `page-item${disabled ? ' disabled' : ''}`;
    return `<li class="${cls}">
      <a class="page-link" href="?p=${page}" data-page="${page}" data-no-router="1"
         aria-label="${escapeHtml(ariaLabel)}"${disabled ? ' aria-disabled="true"' : ''}>${_icon(iconName)}</a>
    </li>`;
  }

  items.push(navLink(1, 'chevronDoubleLeft', 'First page', { disabled: currentPage === 1 }));
  items.push(navLink(currentPage - 1, 'chevronLeft', 'Previous page', { disabled: currentPage === 1 }));

  // Window of 5 page links
  const start = Math.max(1, currentPage - 2);
  const end = Math.min(lastPage, start + 4);
  for (let p = start; p <= end; p++) {
    items.push(pageLink(p, String(p), { active: p === currentPage }));
  }

  items.push(navLink(currentPage + 1, 'chevronRight', 'Next page', { disabled: currentPage === lastPage }));
  items.push(navLink(lastPage, 'chevronDoubleRight', 'Last page', { disabled: currentPage === lastPage }));

  list.innerHTML = items.join('');
}

/* ─── Card rendering (US-003 AC11-AC19) ──────────────────────────────────── */

const _CARD_FIELDS = [
  'form_number', 'title', 'description', 'business_area',
  'file_type', 'form_source', 'effective_date', 'updated_at', 'keywords', 'url',
];

// Allow-list project the API item — never read/render anything else (AC3/AC18).
function _safeForm(item) {
  const safe = {};
  for (const k of _CARD_FIELDS) safe[k] = (item && item[k] != null) ? item[k] : null;
  return safe;
}

// Cache the record in history.state for cache-first detail render; bail if the
// payload is too large (mirrors the prior form-card behaviour).
function _stateForDetail(f) {
  const rec = { ...f };
  delete rec.url;
  if (byteLength(rec) > HISTORY_STATE_CAP_BYTES) return null;
  return rec;
}

// AC16b/BR-008 — a form is treated as a hyperlink only when it exposes a
// non-empty http(s) destination URL. The shared `safeHttpUrl` helper rejects
// any other scheme (e.g. javascript:) so an unsafe link can never be produced.

function _cardHtml(item, index) {
  const f = _safeForm(item);
  const hasNumber = !!f.form_number;
  const num = f.form_number || '—';
  const title = f.title || '';
  const desc = f.description || '';
  const ba = f.business_area || '';
  const ft = (f.file_type || '').toLowerCase();
  const ftLabel = formatFileType(f.file_type);
  const eff = formatDate(f.effective_date);
  const updated = formatDate(f.updated_at);
  const url = _safeUrl(f.url);
  // US-005 P7/BR-007 — positive file evidence: a non-empty file_type that is
  // NOT a link-source ("URL") row. Covers form_source "Download" and legacy
  // null rows carrying file metadata (FEAT-0029 E2). Absent both a valid url
  // and positive file evidence, the form is "no source": no pill, no action.
  const isUrlSource = (f.form_source || '').trim().toUpperCase() === 'URL';
  const hasFileEvidence = !!ft && !isUrlSource;
  const titleId = `card-${index}-title`;
  const href = hasNumber ? `/forms/${encodeURIComponent(f.form_number)}` : '';
  const routeState = hasNumber ? escapeHtml(JSON.stringify(_stateForDetail(f))) : '';

  // Meta row: form-number link, business-area badge, right-aligned "Updated".
  const formNumberEl = hasNumber
    ? `<a class="form-num-link" href="${href}" data-route-state='${routeState}'
          aria-label="Open details for form ${escapeHtml(num)}">${escapeHtml(num)}</a>`
    : `<span class="form-num-link" aria-label="Form number not assigned">${escapeHtml(num)}</span>`;
  const baEl = ba
    ? `<span class="ba-badge" title="Business Area: ${escapeHtml(ba)}">${escapeHtml(ba)}</span>`
    : '';
  const updatedEl = updated
    ? `<time class="card-date" datetime="${escapeHtml(f.updated_at || '')}">Updated ${escapeHtml(updated)}</time>`
    : '';

  // Footer row: file-type (or link) pill, effective-date pill, View details,
  // and the right-aligned Download (or "Form Link") action.
  // US-005 AC1/AC3 — a "no source" form renders no pill at all (not even the
  // neutral FILE fallback), refining US-003 E3 for the no-file/no-link case.
  let pill = '';
  if (url) {
    pill = `<span class="file-type-pill link">${_icon('link')} Link</span>`;
  } else if (hasFileEvidence) {
    pill = `<span class="file-type-pill ${escapeHtml(ft)}">${_fileTypeIcon(ft)} ${escapeHtml(ftLabel || 'FILE')}</span>`;
  }
  const effEl = eff
    ? `<span class="file-type-pill file-date">${_icon('calendar')}<span class="visually-hidden">Effective:</span> ${escapeHtml(eff)}</span>`
    : '';
  const viewMore = hasNumber
    ? `<a class="btn-view-more" href="${href}" data-route-state='${routeState}'
          aria-label="View details about ${escapeHtml(num)}">${_icon('eye')} View details</a>`
    : '';

  // US-005 AC2 — a "no source" form renders no action control (not even a
  // disabled one). The disabled Download is reserved for a file-source form
  // that lacks a form_number to download by (US-003 AC14).
  let action = '';
  if (url) {
    action = `<a class="btn-download" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer"
                 data-no-router="1" aria-label="Open link for ${escapeHtml(num)} (opens in new tab)">${_icon('externalLink')} Form Link</a>`;
  } else if (hasFileEvidence) {
    if (hasNumber) {
      action = `<button type="button" class="btn-download" data-action="download"
                 data-form-number="${escapeHtml(f.form_number)}"
                 aria-label="Download ${escapeHtml(num)}${ftLabel ? ` (${escapeHtml(ftLabel)})` : ''}">${_icon('download')} Download</button>`;
    } else {
      action = `<button type="button" class="btn-download" disabled aria-disabled="true"
                 aria-label="Download (unavailable)">${_icon('download')} Download</button>`;
    }
  }

  return `<li>
      <article class="form-card-v2" aria-labelledby="${titleId}">
        <div class="card-accent" aria-hidden="true"></div>
        <div class="card-body-inner">
          <div class="card-meta-row">
            ${formNumberEl}
            ${baEl}
            ${updatedEl}
          </div>
          <h2 id="${titleId}">${escapeHtml(title)}</h2>
          <p class="card-desc">${escapeHtml(desc)}</p>
          <div class="card-footer-row">
            ${pill}
            ${effEl}
            ${viewMore}
            ${action}
          </div>
        </div>
      </article>
    </li>`;
}

/* ─── Meta-tag helpers (shared with home, used by _resetHomeMeta) ─────── */

function _setMeta(name, content) {
  let el = document.head.querySelector(`meta[name="${name}"]`);
  if (content === '') {
    el?.remove();
    return;
  }
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute('name', name);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
}

function _setProp(prop, content) {
  let el = document.head.querySelector(`meta[property="${prop}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute('property', prop);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
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

