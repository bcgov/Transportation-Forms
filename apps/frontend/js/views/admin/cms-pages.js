// frontend/js/views/admin/cms-pages.js
// FEAT-0026 — Admin CMS Pages list with search, "Show deleted" toggle, and
// native HTML5 drag-and-drop reorder (US-003, US-006).
//
// Reorder uses the list-level ETag returned by GET /admin/cms/pages and
// posts it back as the `If-Match` header on POST /reorder (CC-BR-03).
// Reorder is disabled while a search term is active or the "Show deleted"
// toggle is on, because the API requires the payload to enumerate every
// non-deleted page exactly once.

import { API_BASE, ROUTES } from '../../constants.js';
import {
  escapeHtml,
  formatDateTime,
  showAlert,
  getErrorDetail,
} from '../../utils.js';
import { getAuthToken } from '../../auth.js';

// ─── Module-private state ────────────────────────────────────────────────────
let _pages = [];
let _listEtag = null;
let _draggingId = null;
let _pendingRestoreId = null;
let _pendingRestoreEtag = null;
let _restoreModalListenersAttached = false;
let _viewWired = false;

// ─── Helpers ────────────────────────────────────────────────────────────────

function _authHeaders(extra = {}) {
  return { Authorization: `Bearer ${getAuthToken()}`, ...extra };
}

function _jsonHeaders(extra = {}) {
  return _authHeaders({ 'Content-Type': 'application/json', ...extra });
}

function _searchTerm() {
  return (document.getElementById('cmsPagesSearchInput')?.value || '').trim();
}

function _showDeleted() {
  return Boolean(document.getElementById('cmsPagesShowDeleted')?.checked);
}

function _canReorder() {
  return !_searchTerm() && !_showDeleted() && _pages.length > 1;
}

function _pageEtagOf(page) {
  // Deterministic ETag mirrors backend CmsPageService.page_etag().
  // Instead of duplicating SHA-256 in JS, we fall back to a wildcard
  // If-Match ('*') when the server hasn't handed us a specific value —
  // the backend accepts '*' for restore/delete which is the only place
  // we need per-page ETags on the list view.
  return page.__etag || '*';
}

// ─── View lifecycle ──────────────────────────────────────────────────────────

export async function showCmsPagesListView() {
  const view = document.getElementById('cmsPagesListView');
  if (!view) {
    showAlert('CMS page list is not available in this build.', 'danger');
    return;
  }
  view.style.display = 'block';
  document.getElementById('pageTitle').textContent = 'CMS Pages - BC Gov';

  _wireView();
  await _loadPages();
}

function _wireView() {
  if (_viewWired) return;
  _viewWired = true;

  const view = document.getElementById('cmsPagesListView');

  view
    .querySelector('[data-action="cms-pages-refresh"]')
    ?.addEventListener('click', () => _loadPages());

  document
    .getElementById('cmsPagesSearchInput')
    ?.addEventListener('input', _debounce(() => _loadPages(), 200));

  document
    .getElementById('cmsPagesShowDeleted')
    ?.addEventListener('change', () => _loadPages());

  // Delegated click handler for row actions.
  document
    .getElementById('cmsPagesList')
    .addEventListener('click', _handleRowClick);
}

function _debounce(fn, delay) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), delay);
  };
}

// ─── Data loading ────────────────────────────────────────────────────────────

async function _loadPages() {
  const container = document.getElementById('cmsPagesList');
  container.innerHTML = `
    <div class="spinner-container">
      <div class="spinner-border" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>`;

  const params = new URLSearchParams();
  const search = _searchTerm();
  if (search) params.set('search', search);
  if (_showDeleted()) params.set('include_deleted', 'true');

  try {
    const resp = await fetch(
      `${API_BASE}/admin/cms/pages${params.toString() ? `?${params}` : ''}`,
      { headers: _authHeaders() },
    );
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to load CMS pages.'));
    }
    const body = await resp.json();
    _pages = Array.isArray(body?.pages) ? body.pages : [];
    _listEtag = body?.list_etag || resp.headers.get('etag') || null;
    _render();
  } catch (err) {
    container.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
  }
}

// ─── Rendering ───────────────────────────────────────────────────────────────

function _render() {
  const container = document.getElementById('cmsPagesList');
  if (!_pages.length) {
    container.innerHTML =
      '<div class="alert alert-light border">No CMS pages found.</div>';
    return;
  }

  const reorderEnabled = _canReorder();

  const rows = _pages
    .map(p => _renderRow(p, reorderEnabled))
    .join('');

  container.innerHTML = `
    <div class="table-responsive">
      <table class="table table-hover align-middle">
        <thead>
          <tr>
            ${reorderEnabled ? '<th style="width:2rem;"></th>' : ''}
            <th>Slug</th>
            <th>Title</th>
            <th class="text-center">In Nav</th>
            <th class="text-center">Nav Order</th>
            <th>Updated</th>
            <th class="text-end">Actions</th>
          </tr>
        </thead>
        <tbody id="cmsPagesTableBody">
          ${rows}
        </tbody>
      </table>
    </div>`;

  if (reorderEnabled) {
    _wireDragAndDrop();
  }
}

function _renderRow(page, reorderEnabled) {
  const isDeleted = Boolean(page.deleted_at);
  const draggable = reorderEnabled && !isDeleted;
  const navBadge = page.show_in_nav
    ? '<span class="badge bg-success">Yes</span>'
    : '<span class="badge bg-secondary">No</span>';
  const slugCell = isDeleted
    ? `<code class="text-muted">${escapeHtml(page.slug)}</code>
       <span class="badge bg-danger ms-1">Deleted</span>`
    : `<code>${escapeHtml(page.slug)}</code>`;

  const actions = isDeleted
    ? `<button class="btn btn-sm btn-outline-primary" type="button"
         data-action="cms-page-restore" data-page-id="${escapeHtml(page.id)}"
         data-slug="${escapeHtml(page.slug)}">
         <i class="fas fa-undo"></i> Restore
       </button>`
    : `<button class="btn btn-sm btn-outline-primary" type="button"
         data-action="cms-page-edit" data-page-id="${escapeHtml(page.id)}">
         <i class="fas fa-edit"></i> Edit
       </button>`;

  return `
    <tr data-page-id="${escapeHtml(page.id)}"
        ${draggable ? 'draggable="true"' : ''}
        class="${draggable ? 'cms-page-row' : ''} ${isDeleted ? 'text-muted' : ''}">
      ${reorderEnabled
        ? `<td class="${draggable ? 'text-secondary' : 'text-body-secondary'}"
             style="${draggable ? 'cursor:grab;' : ''}"
             title="${draggable ? 'Drag to reorder' : 'Reorder disabled for deleted rows'}">
             ${draggable ? '<i class="fas fa-grip-vertical"></i>' : ''}
           </td>`
        : ''}
      <td>${slugCell}</td>
      <td>${escapeHtml(page.title || '')}</td>
      <td class="text-center">${navBadge}</td>
      <td class="text-center">${page.nav_order ?? '<span class="text-muted">—</span>'}</td>
      <td><small class="text-muted">${page.updated_at ? formatDateTime(page.updated_at) : '—'}</small></td>
      <td class="text-end">${actions}</td>
    </tr>`;
}

// ─── Delegated row actions ───────────────────────────────────────────────────

function _handleRowClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const pageId = btn.dataset.pageId;
  if (!pageId) return;

  if (btn.dataset.action === 'cms-page-edit') {
    window.history.pushState({}, '', `${ROUTES.CMS_PAGES}/${pageId}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  } else if (btn.dataset.action === 'cms-page-restore') {
    _openRestoreModal(pageId, btn.dataset.slug || '');
  }
}

// ─── Drag & drop reorder (US-006) ────────────────────────────────────────────

function _wireDragAndDrop() {
  const tbody = document.getElementById('cmsPagesTableBody');
  if (!tbody) return;

  tbody.addEventListener('dragstart', e => {
    const row = e.target.closest('tr[draggable="true"]');
    if (!row) return;
    _draggingId = row.dataset.pageId;
    row.classList.add('opacity-50');
    e.dataTransfer.effectAllowed = 'move';
    // Firefox requires setData for drag to fire.
    try {
      e.dataTransfer.setData('text/plain', _draggingId);
    } catch {
      /* ignore */
    }
  });

  tbody.addEventListener('dragover', e => {
    if (!_draggingId) return;
    e.preventDefault();
    const target = e.target.closest('tr[draggable="true"]');
    if (!target || target.dataset.pageId === _draggingId) return;
    const rect = target.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;
    const dragged = tbody.querySelector(
      `tr[data-page-id="${CSS.escape(_draggingId)}"]`,
    );
    if (!dragged) return;
    if (before) {
      tbody.insertBefore(dragged, target);
    } else {
      tbody.insertBefore(dragged, target.nextSibling);
    }
  });

  tbody.addEventListener('dragend', async () => {
    if (!_draggingId) return;
    const dragged = tbody.querySelector(
      `tr[data-page-id="${CSS.escape(_draggingId)}"]`,
    );
    dragged?.classList.remove('opacity-50');
    _draggingId = null;

    const newOrder = Array.from(tbody.querySelectorAll('tr[data-page-id]'))
      .map(r => r.dataset.pageId);
    const originalOrder = _pages.map(p => p.id);
    const changed = newOrder.some((id, i) => id !== originalOrder[i]);
    if (!changed) return;

    await _submitReorder(newOrder);
  });
}

async function _submitReorder(orderedIds) {
  if (!_listEtag) {
    showAlert('Cannot reorder — missing list ETag. Refresh and try again.', 'danger');
    await _loadPages();
    return;
  }
  try {
    const resp = await fetch(`${API_BASE}/admin/cms/pages/reorder`, {
      method: 'POST',
      headers: _jsonHeaders({ 'If-Match': _listEtag }),
      body: JSON.stringify({ ordered_ids: orderedIds }),
    });
    if (resp.status === 412 || resp.status === 428) {
      showAlert(
        'Another editor modified the page list. Reloading with the latest state.',
        'warning',
      );
      await _loadPages();
      return;
    }
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to reorder pages.'));
    }
    const body = await resp.json();
    _pages = Array.isArray(body?.pages) ? body.pages : [];
    _listEtag = body?.list_etag || resp.headers.get('etag') || null;
    _render();
    showAlert('Page order updated.', 'success');
  } catch (err) {
    showAlert(err.message || 'Failed to reorder pages.', 'danger');
    await _loadPages();
  }
}

function _jsonHeadersWithIfMatch(etag) {
  return _authHeaders({ 'Content-Type': 'application/json', 'If-Match': etag });
}

// ─── Restore modal (US-003 AC9) ──────────────────────────────────────────────

function _openRestoreModal(pageId, slug) {
  _pendingRestoreId = pageId;
  _pendingRestoreEtag = '*'; // list rows do not carry per-page ETags; wildcard OK for restore.

  document.getElementById('cmsRestoreMessage').textContent =
    `Restore soft-deleted page "${slug}"? It will re-appear in the pages list ` +
    'and be re-added at the end of the navigation order.';
  document.getElementById('cmsRestoreAlternateWrapper').style.display = 'none';
  document.getElementById('cmsRestoreAlternateSlug').value = '';
  document.getElementById('cmsRestoreAlternateError').textContent = '';

  _ensureRestoreModalListeners();

  const modal = new window.bootstrap.Modal(
    document.getElementById('cmsRestoreModal'),
  );
  modal.show();
}

function _ensureRestoreModalListeners() {
  if (_restoreModalListenersAttached) return;
  _restoreModalListenersAttached = true;
  document
    .getElementById('cmsRestoreConfirmBtn')
    ?.addEventListener('click', () => _confirmRestore());
}

async function _confirmRestore() {
  if (!_pendingRestoreId) return;

  const wrapper = document.getElementById('cmsRestoreAlternateWrapper');
  const alt = (
    document.getElementById('cmsRestoreAlternateSlug').value || ''
  ).trim();
  const err = document.getElementById('cmsRestoreAlternateError');
  err.textContent = '';

  const body = wrapper.style.display === 'none' ? {} : { alternate_slug: alt };
  if (wrapper.style.display !== 'none' && !alt) {
    err.textContent = 'Alternate slug is required.';
    return;
  }

  try {
    const resp = await fetch(
      `${API_BASE}/admin/cms/pages/${_pendingRestoreId}/restore`,
      {
        method: 'POST',
        headers: _jsonHeadersWithIfMatch(_pendingRestoreEtag),
        body: JSON.stringify(body),
      },
    );
    if (resp.status === 409) {
      // Slug collision — surface alternate-slug field per US-003 AC9.
      wrapper.style.display = '';
      let detail = null;
      try { detail = await resp.json(); } catch { /* ignore */ }
      err.textContent =
        detail?.detail?.message ||
        detail?.detail ||
        'The original slug is now in use by another active page. ' +
          'Provide an alternate slug to complete the restore.';
      return;
    }
    if (resp.status === 412 || resp.status === 428) {
      showAlert(
        'The page changed since the list was loaded. Reloading.',
        'warning',
      );
      window.bootstrap.Modal.getInstance(
        document.getElementById('cmsRestoreModal'),
      )?.hide();
      await _loadPages();
      return;
    }
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to restore page.'));
    }
    window.bootstrap.Modal.getInstance(
      document.getElementById('cmsRestoreModal'),
    )?.hide();
    showAlert('Page restored.', 'success');
    await _loadPages();
  } catch (error) {
    err.textContent = error.message || 'Failed to restore page.';
  }
}
