// frontend/js/views/admin/cms-page-new.js
// FEAT-0026 US-001 — Minimal admin form for creating a new CMS page.
//
// Form fields:
//   * Title (required, ≤120 chars)
//   * Slug (required, ≤80 chars, lowercase + hyphens; auto-derived from title
//     until the user edits the field manually)
//   * Meta description (optional, ≤180 chars)
//   * Body HTML (required, plain <textarea>; server sanitizes via nh3)
//   * Show in nav (checkbox, default on)
//
// Reserved-slug list (US-007) is fetched once per view load and used for
// inline validation so authors get fast feedback before submitting.

import { API_BASE, ROUTES } from '../../constants.js';
import {
  escapeHtml,
  showAlert,
  getErrorDetail,
} from '../../utils.js';
import { getAuthToken } from '../../auth.js';

// ─── Module-private state ─────────────────────────────────────────────────────
let _reservedSlugs = null;
let _slugManuallyEdited = false;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function _authHeaders(extra = {}) {
  return { Authorization: `Bearer ${getAuthToken()}`, ...extra };
}

function _jsonHeaders() {
  return _authHeaders({ 'Content-Type': 'application/json' });
}

function _slugify(title) {
  return (title || '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
}

async function _fetchReservedSlugs() {
  if (_reservedSlugs) return _reservedSlugs;
  try {
    const resp = await fetch(`${API_BASE}/admin/cms/pages/reserved-slugs`, {
      headers: _authHeaders(),
    });
    if (resp.ok) {
      const body = await resp.json();
      _reservedSlugs = new Set(body.reserved || []);
    } else {
      _reservedSlugs = new Set();
    }
  } catch {
    _reservedSlugs = new Set();
  }
  return _reservedSlugs;
}

function _setError(field, message) {
  const el = document.getElementById(`cmsPageNew_${field}_error`);
  if (!el) return;
  el.textContent = message || '';
  el.style.display = message ? 'block' : 'none';
  const input = document.getElementById(`cmsPageNew_${field}`);
  if (input) {
    input.classList.toggle('is-invalid', Boolean(message));
  }
}

function _clearErrors() {
  ['title', 'slug', 'meta_description', 'body_html'].forEach(f => _setError(f, ''));
}

function _updateCharCount(inputId, counterId, max) {
  const input = document.getElementById(inputId);
  const counter = document.getElementById(counterId);
  if (!input || !counter) return;
  const length = (input.value || '').length;
  counter.textContent = `${length} / ${max}`;
  counter.classList.toggle('text-danger', length > max);
}

// ─── Public view entry point ──────────────────────────────────────────────────

export async function showCmsPageNewView() {
  const view = document.getElementById('cmsPageNewView');
  if (!view) {
    showAlert('CMS page editor is not available in this build.', 'danger');
    return;
  }
  view.style.display = 'block';
  document.getElementById('pageTitle').textContent = 'New CMS Page - BC Gov';

  // Reset form
  document.getElementById('cmsPageNew_title').value = '';
  document.getElementById('cmsPageNew_slug').value = '';
  document.getElementById('cmsPageNew_meta_description').value = '';
  document.getElementById('cmsPageNew_body_html').value = '';
  document.getElementById('cmsPageNew_show_in_nav').checked = true;
  _slugManuallyEdited = false;
  _clearErrors();

  _wire();
  _updateCharCount('cmsPageNew_title', 'cmsPageNew_title_count', 120);
  _updateCharCount('cmsPageNew_slug', 'cmsPageNew_slug_count', 80);
  _updateCharCount(
    'cmsPageNew_meta_description',
    'cmsPageNew_meta_description_count',
    180,
  );

  await _fetchReservedSlugs();
}

function _wire() {
  const view = document.getElementById('cmsPageNewView');
  if (view.dataset.wired === '1') return;
  view.dataset.wired = '1';

  const titleEl = document.getElementById('cmsPageNew_title');
  const slugEl = document.getElementById('cmsPageNew_slug');
  const metaEl = document.getElementById('cmsPageNew_meta_description');

  titleEl?.addEventListener('input', () => {
    _updateCharCount('cmsPageNew_title', 'cmsPageNew_title_count', 120);
    if (!_slugManuallyEdited) {
      slugEl.value = _slugify(titleEl.value);
      _updateCharCount('cmsPageNew_slug', 'cmsPageNew_slug_count', 80);
      _validateSlugInline();
    }
  });

  slugEl?.addEventListener('input', () => {
    _slugManuallyEdited = true;
    _updateCharCount('cmsPageNew_slug', 'cmsPageNew_slug_count', 80);
    _validateSlugInline();
  });

  metaEl?.addEventListener('input', () => {
    _updateCharCount(
      'cmsPageNew_meta_description',
      'cmsPageNew_meta_description_count',
      180,
    );
  });

  view
    .querySelector('[data-action="cms-page-new-submit"]')
    ?.addEventListener('click', () => _submit());
}

function _validateSlugInline() {
  const slug = (document.getElementById('cmsPageNew_slug').value || '').trim();
  if (!slug) {
    _setError('slug', 'Slug is required.');
    return false;
  }
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) {
    _setError(
      'slug',
      'Slug must be lowercase alphanumerics separated by single hyphens.',
    );
    return false;
  }
  if (_reservedSlugs && _reservedSlugs.has(slug)) {
    _setError('slug', `Slug "${slug}" is reserved and cannot be used.`);
    return false;
  }
  _setError('slug', '');
  return true;
}

async function _submit() {
  _clearErrors();

  const title = (document.getElementById('cmsPageNew_title').value || '').trim();
  const slug = (document.getElementById('cmsPageNew_slug').value || '').trim();
  const meta = (
    document.getElementById('cmsPageNew_meta_description').value || ''
  ).trim();
  const body = document.getElementById('cmsPageNew_body_html').value || '';
  const showInNav = document.getElementById('cmsPageNew_show_in_nav').checked;

  let ok = true;
  if (!title) {
    _setError('title', 'Title is required.');
    ok = false;
  } else if (title.length > 120) {
    _setError('title', 'Title must be 120 characters or fewer.');
    ok = false;
  }
  if (!_validateSlugInline()) ok = false;
  if (meta.length > 180) {
    _setError('meta_description', 'Meta description must be 180 characters or fewer.');
    ok = false;
  }
  if (!body.trim()) {
    _setError('body_html', 'Body is required.');
    ok = false;
  }
  if (!ok) return;

  try {
    const resp = await fetch(`${API_BASE}/admin/cms/pages`, {
      method: 'POST',
      headers: _jsonHeaders(),
      body: JSON.stringify({
        title,
        slug,
        meta_description: meta || null,
        body_html: body,
        show_in_nav: showInNav,
      }),
    });

    if (resp.status === 201) {
      let created = null;
      try {
        created = await resp.json();
      } catch {
        created = null;
      }
      showAlert('CMS page created successfully.', 'success');
      const target = created?.id
        ? `${ROUTES.CMS_PAGES}/${created.id}`
        : ROUTES.CMS_PAGES;
      window.history.pushState({}, '', target);
      window.dispatchEvent(new PopStateEvent('popstate'));
      return;
    }

    let detail = null;
    try {
      detail = await resp.json();
    } catch {
      detail = null;
    }

    if (resp.status === 422 && detail?.detail?.field) {
      _setError(detail.detail.field, detail.detail.message || 'Invalid value.');
      return;
    }
    if (resp.status === 409 && detail?.detail?.slug) {
      _setError(
        'slug',
        detail.detail.message ||
          `Slug "${escapeHtml(detail.detail.slug)}" is already in use.`,
      );
      return;
    }
    throw new Error(await getErrorDetail(resp, 'Failed to create CMS page.'));
  } catch (error) {
    showAlert(error.message || 'Failed to create CMS page.', 'danger');
  }
}
