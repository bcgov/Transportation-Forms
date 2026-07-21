// frontend/js/views/admin/cms-page-edit.js
// FEAT-0026 — Admin CMS Page edit view (US-002/US-003/US-004/US-005).
//
// Loads a single page, renders an edit form with live character counters,
// enforces optimistic concurrency via `If-Match`, and exposes soft-delete
// and revision-restore controls. Revisions are shown inline (newest first).

import { API_BASE, ROUTES } from '../../constants.js';
import {
  escapeHtml,
  formatDateTime,
  showAlert,
  getErrorDetail,
} from '../../utils.js';
import { getAuthToken } from '../../auth.js';

// ─── Module-private state ───────────────────────────────────────────────────
let _page = null;
let _pageEtag = null;
let _revisions = null;
let _reservedSlugs = null;
let _viewWired = false;

// ─── Auth helpers ───────────────────────────────────────────────────────────

function _authHeaders(extra = {}) {
  return { Authorization: `Bearer ${getAuthToken()}`, ...extra };
}

function _jsonHeaders(extra = {}) {
  return _authHeaders({ 'Content-Type': 'application/json', ...extra });
}

// ─── View lifecycle ────────────────────────────────────────────────────────

export async function showCmsPageEditView(pageId) {
  const view = document.getElementById('cmsPageEditView');
  if (!view) {
    showAlert('CMS page editor is not available in this build.', 'danger');
    return;
  }
  view.style.display = 'block';
  document.getElementById('pageTitle').textContent = 'Edit CMS Page - BC Gov';

  _wireView();
  await Promise.all([_loadReservedSlugs(), _loadPage(pageId)]);
}

function _wireView() {
  if (_viewWired) return;
  _viewWired = true;

  // Delegated click / input handling on the edit content container.
  const container = document.getElementById('cmsPageEditContent');
  container.addEventListener('click', _handleClick);
  container.addEventListener('input', _handleInput);
}

// ─── Data loading ──────────────────────────────────────────────────────────

async function _loadReservedSlugs() {
  if (_reservedSlugs) return;
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
}

async function _loadPage(pageId) {
  const container = document.getElementById('cmsPageEditContent');
  container.innerHTML = `
    <div class="spinner-container">
      <div class="spinner-border" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>`;

  try {
    const resp = await fetch(
      `${API_BASE}/admin/cms/pages/${pageId}?include_deleted=true`,
      { headers: _authHeaders() },
    );
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to load page.'));
    }
    _page = await resp.json();
    _pageEtag = resp.headers.get('etag') || null;
    _revisions = null;
    _render();
  } catch (err) {
    container.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
  }
}

async function _loadRevisions() {
  if (!_page?.id) return;
  const listEl = document.getElementById('cmsPageEdit_revisionsList');
  if (!listEl) return;
  listEl.innerHTML = `
    <div class="spinner-container">
      <div class="spinner-border spinner-border-sm" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>`;

  try {
    const resp = await fetch(
      `${API_BASE}/admin/cms/pages/${_page.id}/revisions`,
      { headers: _authHeaders() },
    );
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to load revisions.'));
    }
    _revisions = await resp.json();
    _renderRevisions();
  } catch (err) {
    listEl.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
  }
}

// ─── Render ─────────────────────────────────────────────────────────────────

function _render() {
  const container = document.getElementById('cmsPageEditContent');
  if (!_page) {
    container.innerHTML = '<div class="alert alert-warning">Page not found.</div>';
    return;
  }
  const p = _page;
  const isDeleted = Boolean(p.deleted_at);

  const disabledAttr = isDeleted ? 'disabled' : '';

  container.innerHTML = `
    ${isDeleted
      ? `<div class="alert alert-warning d-flex justify-content-between align-items-center">
           <div>
             <i class="fas fa-exclamation-triangle"></i>
             This page is soft-deleted. Editing is disabled until it is restored.
           </div>
           <button class="btn btn-sm btn-bc-primary" type="button"
             data-action="cms-page-restore">
             <i class="fas fa-undo"></i> Restore Page
           </button>
         </div>`
      : ''}

    <div class="card mb-3">
      <div class="card-body">
        <div class="row g-3">
          <div class="col-12">
            <label for="cmsPageEdit_title" class="form-label">
              Title <span class="text-danger">*</span>
            </label>
            <input id="cmsPageEdit_title" class="form-control" type="text"
              maxlength="120" value="${escapeHtml(p.title || '')}" ${disabledAttr}>
            <div class="d-flex justify-content-between">
              <div id="cmsPageEdit_title_error" class="invalid-feedback d-block"
                style="display:none;"></div>
              <small id="cmsPageEdit_title_count" class="text-muted"></small>
            </div>
          </div>
          <div class="col-12">
            <label for="cmsPageEdit_slug" class="form-label">
              URL Slug <span class="text-danger">*</span>
            </label>
            <input id="cmsPageEdit_slug" class="form-control" type="text"
              maxlength="80" value="${escapeHtml(p.slug || '')}" ${disabledAttr}>
            <div class="d-flex justify-content-between">
              <div id="cmsPageEdit_slug_error" class="invalid-feedback d-block"
                style="display:none;"></div>
              <small id="cmsPageEdit_slug_count" class="text-muted"></small>
            </div>
            <div class="form-text">
              Changing the slug automatically creates a redirect from the old slug.
            </div>
          </div>
          <div class="col-12">
            <label for="cmsPageEdit_meta" class="form-label">Meta Description</label>
            <textarea id="cmsPageEdit_meta" class="form-control" rows="2" maxlength="180"
              ${disabledAttr}>${escapeHtml(p.meta_description || '')}</textarea>
            <div class="d-flex justify-content-between">
              <div id="cmsPageEdit_meta_error" class="invalid-feedback d-block"
                style="display:none;"></div>
              <small id="cmsPageEdit_meta_count" class="text-muted"></small>
            </div>
          </div>
          <div class="col-12">
            <label for="cmsPageEdit_body" class="form-label">
              Body HTML <span class="text-danger">*</span>
            </label>
            <textarea id="cmsPageEdit_body" class="form-control" rows="14"
              ${disabledAttr}>${escapeHtml(p.body_html || '')}</textarea>
            <div id="cmsPageEdit_body_error" class="invalid-feedback d-block"
              style="display:none;"></div>
            <div class="form-text">
              Body is re-sanitized on save. Disallowed tags/attributes are stripped.
            </div>
          </div>
          <div class="col-12">
            <div class="form-check">
              <input class="form-check-input" type="checkbox"
                id="cmsPageEdit_show_in_nav" ${p.show_in_nav ? 'checked' : ''} ${disabledAttr}>
              <label class="form-check-label" for="cmsPageEdit_show_in_nav">
                Show in Forms Portal navigation
              </label>
            </div>
          </div>
        </div>
        <div class="mt-4 d-flex flex-wrap gap-2">
          ${isDeleted
            ? ''
            : `<button class="btn btn-bc-primary" type="button" data-action="cms-page-save">
                 <i class="fas fa-save"></i> Save Changes
               </button>
               <button class="btn btn-outline-danger" type="button" data-action="cms-page-delete">
                 <i class="fas fa-trash"></i> Delete
               </button>`}
          <button class="btn btn-outline-secondary" type="button" data-route="/admin/cms/pages">
            Cancel
          </button>
        </div>
        <div class="mt-3 small text-muted">
          <div><strong>Page ID:</strong> <code>${escapeHtml(p.id)}</code></div>
          <div><strong>Created:</strong> ${p.created_at ? formatDateTime(p.created_at) : '—'}</div>
          <div><strong>Updated:</strong> ${p.updated_at ? formatDateTime(p.updated_at) : '—'}</div>
          <div><strong>Nav order:</strong> ${p.nav_order ?? '—'}</div>
          ${isDeleted
            ? `<div class="text-danger"><strong>Deleted:</strong> ${formatDateTime(p.deleted_at)}</div>`
            : ''}
        </div>
      </div>
    </div>

    <!-- Revision history (US-005) -->
    <div class="card">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span><i class="fas fa-history"></i> Revision History</span>
        <button class="btn btn-sm btn-outline-secondary" type="button"
          data-action="cms-page-revisions-load">
          <i class="fas fa-sync-alt"></i> Load / Refresh
        </button>
      </div>
      <div class="card-body">
        <div id="cmsPageEdit_revisionsList">
          <p class="text-muted small mb-0">
            Click <em>Load / Refresh</em> to view prior versions of this page.
          </p>
        </div>
      </div>
    </div>
  `;

  _updateAllCounters();
}

function _renderRevisions() {
  const listEl = document.getElementById('cmsPageEdit_revisionsList');
  if (!listEl) return;
  if (!_revisions?.length) {
    listEl.innerHTML =
      '<p class="text-muted small mb-0">No revisions recorded yet.</p>';
    return;
  }
  const rows = _revisions
    .map((r, idx) => {
      const isFirst = idx === _revisions.length - 1;
      const slugBadge =
        _page && r.slug !== _page.slug
          ? '<span class="badge bg-warning text-dark ms-1" title="Slug differs">Slug changed</span>'
          : '';
      return `
      <tr>
        <td><small class="text-muted">${r.edited_at ? formatDateTime(r.edited_at) : '—'}</small></td>
        <td>${escapeHtml(r.title || '')}</td>
        <td><code>${escapeHtml(r.slug || '')}</code>${slugBadge}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-outline-primary" type="button"
            data-action="cms-page-revision-restore"
            data-revision-id="${escapeHtml(r.id)}"
            ${isFirst ? 'disabled title="This is the current or oldest revision"' : ''}>
            <i class="fas fa-undo"></i> Restore
          </button>
        </td>
      </tr>`;
    })
    .join('');

  listEl.innerHTML = `
    <div class="table-responsive">
      <table class="table table-sm align-middle mb-0">
        <thead>
          <tr>
            <th>Edited</th>
            <th>Title</th>
            <th>Slug</th>
            <th class="text-end">Actions</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// ─── Event handlers ─────────────────────────────────────────────────────────

function _handleClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;

  if (action === 'cms-page-save') return _submitSave();
  if (action === 'cms-page-delete') return _submitDelete();
  if (action === 'cms-page-restore') return _submitRestore();
  if (action === 'cms-page-revisions-load') return _loadRevisions();
  if (action === 'cms-page-revision-restore') {
    return _submitRevisionRestore(btn.dataset.revisionId);
  }
}

function _handleInput(e) {
  const t = e.target;
  if (!t?.id) return;
  if (t.id === 'cmsPageEdit_title') {
    _updateCharCount('cmsPageEdit_title', 'cmsPageEdit_title_count', 120);
  } else if (t.id === 'cmsPageEdit_slug') {
    _updateCharCount('cmsPageEdit_slug', 'cmsPageEdit_slug_count', 80);
    _validateSlugInline();
  } else if (t.id === 'cmsPageEdit_meta') {
    _updateCharCount('cmsPageEdit_meta', 'cmsPageEdit_meta_count', 180);
  }
}

function _updateAllCounters() {
  _updateCharCount('cmsPageEdit_title', 'cmsPageEdit_title_count', 120);
  _updateCharCount('cmsPageEdit_slug', 'cmsPageEdit_slug_count', 80);
  _updateCharCount('cmsPageEdit_meta', 'cmsPageEdit_meta_count', 180);
}

function _updateCharCount(inputId, counterId, max) {
  const input = document.getElementById(inputId);
  const counter = document.getElementById(counterId);
  if (!input || !counter) return;
  const length = (input.value || '').length;
  counter.textContent = `${length} / ${max}`;
  counter.classList.toggle('text-danger', length > max);
}

function _setFieldError(field, message) {
  const el = document.getElementById(`cmsPageEdit_${field}_error`);
  if (!el) return;
  el.textContent = message || '';
  el.style.display = message ? 'block' : 'none';
  const input =
    document.getElementById(`cmsPageEdit_${field}`) ||
    document.getElementById(`cmsPageEdit_${field}_input`);
  if (input) {
    input.classList.toggle('is-invalid', Boolean(message));
  }
}

function _clearFieldErrors() {
  ['title', 'slug', 'meta', 'body'].forEach(f => _setFieldError(f, ''));
}

function _validateSlugInline() {
  const el = document.getElementById('cmsPageEdit_slug');
  const slug = (el?.value || '').trim();
  if (!slug) {
    _setFieldError('slug', 'Slug is required.');
    return false;
  }
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) {
    _setFieldError('slug',
      'Slug must be lowercase alphanumerics separated by single hyphens.');
    return false;
  }
  if (_reservedSlugs && _reservedSlugs.has(slug)) {
    _setFieldError('slug', `Slug "${slug}" is reserved.`);
    return false;
  }
  _setFieldError('slug', '');
  return true;
}

// ─── Save / delete / restore / revision restore ─────────────────────────────

async function _submitSave() {
  if (!_page?.id) return;
  _clearFieldErrors();

  const title = (document.getElementById('cmsPageEdit_title').value || '').trim();
  const slug = (document.getElementById('cmsPageEdit_slug').value || '').trim();
  const meta = (document.getElementById('cmsPageEdit_meta').value || '').trim();
  const body = document.getElementById('cmsPageEdit_body').value || '';
  const showInNav = document.getElementById('cmsPageEdit_show_in_nav').checked;

  let ok = true;
  if (!title) {
    _setFieldError('title', 'Title is required.');
    ok = false;
  }
  if (!_validateSlugInline()) ok = false;
  if (!body.trim()) {
    _setFieldError('body', 'Body is required.');
    ok = false;
  }
  if (!ok) return;

  // Only send fields that actually changed to keep the audit minimal.
  const payload = {};
  if (title !== (_page.title || '')) payload.title = title;
  if (slug !== (_page.slug || '')) payload.slug = slug;
  if (meta !== (_page.meta_description || '')) {
    payload.meta_description = meta || null;
  }
  if (body !== (_page.body_html || '')) payload.body_html = body;
  if (showInNav !== Boolean(_page.show_in_nav)) payload.show_in_nav = showInNav;

  if (Object.keys(payload).length === 0) {
    showAlert('No changes to save.', 'info');
    return;
  }

  try {
    const resp = await fetch(`${API_BASE}/admin/cms/pages/${_page.id}`, {
      method: 'PUT',
      headers: _jsonHeaders({ 'If-Match': _pageEtag || '*' }),
      body: JSON.stringify(payload),
    });
    if (resp.status === 412 || resp.status === 428) {
      showAlert(
        'Another editor saved changes. Reloading with the latest state.',
        'warning',
      );
      await _loadPage(_page.id);
      return;
    }
    if (resp.status === 422) {
      const detail = await _safeJson(resp);
      const field = detail?.detail?.field;
      const message = detail?.detail?.message || 'Invalid field value.';
      if (field && ['title', 'slug', 'meta_description', 'body_html'].includes(field)) {
        const uiField = field === 'meta_description' ? 'meta'
          : field === 'body_html' ? 'body' : field;
        _setFieldError(uiField, message);
      } else {
        showAlert(message, 'danger');
      }
      return;
    }
    if (resp.status === 409) {
      const detail = await _safeJson(resp);
      _setFieldError(
        'slug',
        detail?.detail?.message || 'That slug is already in use.',
      );
      return;
    }
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to save changes.'));
    }
    _page = await resp.json();
    _pageEtag = resp.headers.get('etag') || _pageEtag;
    _revisions = null;
    _render();
    showAlert('Changes saved.', 'success');
  } catch (err) {
    showAlert(err.message || 'Failed to save changes.', 'danger');
  }
}

async function _submitDelete() {
  if (!_page?.id) return;
  if (!confirm(`Soft-delete page "${_page.slug}"? It can be restored from the pages list.`)) {
    return;
  }
  try {
    const resp = await fetch(`${API_BASE}/admin/cms/pages/${_page.id}`, {
      method: 'DELETE',
      headers: _authHeaders({ 'If-Match': _pageEtag || '*' }),
    });
    if (resp.status === 412 || resp.status === 428) {
      showAlert(
        'Another editor changed this page. Reloading with the latest state.',
        'warning',
      );
      await _loadPage(_page.id);
      return;
    }
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to delete page.'));
    }
    showAlert('Page deleted.', 'success');
    window.history.pushState({}, '', ROUTES.CMS_PAGES);
    window.dispatchEvent(new PopStateEvent('popstate'));
  } catch (err) {
    showAlert(err.message || 'Failed to delete page.', 'danger');
  }
}

async function _submitRestore() {
  if (!_page?.id) return;
  await _postRestore(null);
}

async function _postRestore(alternateSlug) {
  try {
    const resp = await fetch(`${API_BASE}/admin/cms/pages/${_page.id}/restore`, {
      method: 'POST',
      headers: _jsonHeaders({ 'If-Match': _pageEtag || '*' }),
      body: JSON.stringify(alternateSlug ? { alternate_slug: alternateSlug } : {}),
    });
    if (resp.status === 409) {
      const detail = await _safeJson(resp);
      const prompt =
        detail?.detail?.message ||
        detail?.detail ||
        'The original slug is now in use by another active page.';
      const alt = window.prompt(
        `${prompt}\n\nEnter an alternate slug to complete the restore:`,
        '',
      );
      const cleaned = (alt || '').trim();
      if (!cleaned) {
        showAlert('Restore cancelled.', 'info');
        return;
      }
      await _postRestore(cleaned);
      return;
    }
    if (resp.status === 412 || resp.status === 428) {
      showAlert(
        'Another editor changed this page. Reloading.',
        'warning',
      );
      await _loadPage(_page.id);
      return;
    }
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to restore page.'));
    }
    _page = await resp.json();
    _pageEtag = resp.headers.get('etag') || _pageEtag;
    _revisions = null;
    _render();
    showAlert('Page restored.', 'success');
  } catch (err) {
    showAlert(err.message || 'Failed to restore page.', 'danger');
  }
}

async function _submitRevisionRestore(revisionId) {
  if (!_page?.id || !revisionId) return;
  if (!confirm('Restore this revision? A new revision is inserted; the current page state is overwritten.')) {
    return;
  }
  try {
    const resp = await fetch(
      `${API_BASE}/admin/cms/pages/${_page.id}/revisions/${revisionId}/restore`,
      {
        method: 'POST',
        headers: _authHeaders({ 'If-Match': _pageEtag || '*' }),
      },
    );
    if (resp.status === 412 || resp.status === 428) {
      showAlert(
        'Another editor changed this page. Reloading.',
        'warning',
      );
      await _loadPage(_page.id);
      return;
    }
    if (resp.status === 409) {
      const detail = await _safeJson(resp);
      showAlert(
        detail?.detail?.message ||
          detail?.detail ||
          'The revision could not be restored due to a slug conflict.',
        'danger',
      );
      return;
    }
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to restore revision.'));
    }
    _page = await resp.json();
    _pageEtag = resp.headers.get('etag') || _pageEtag;
    _revisions = null;
    _render();
    showAlert('Revision restored.', 'success');
  } catch (err) {
    showAlert(err.message || 'Failed to restore revision.', 'danger');
  }
}

async function _safeJson(resp) {
  try {
    return await resp.json();
  } catch {
    return null;
  }
}
