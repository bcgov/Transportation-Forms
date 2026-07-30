// frontend/js/views/admin/cms-redirects.js
// FEAT-0026 US-008 — Admin CMS redirects: list + hard-delete.

import { API_BASE } from '../../constants.js';
import {
  escapeHtml,
  formatDateTime,
  showAlert,
  getErrorDetail,
} from '../../utils.js';
import { getAuthToken } from '../../auth.js';

let _viewWired = false;

function _authHeaders(extra = {}) {
  return { Authorization: `Bearer ${getAuthToken()}`, ...extra };
}

export async function showCmsRedirectsView() {
  const view = document.getElementById('cmsRedirectsView');
  if (!view) {
    showAlert('CMS redirects view is not available in this build.', 'danger');
    return;
  }
  view.style.display = 'block';
  document.getElementById('pageTitle').textContent = 'CMS Redirects - BC Gov';

  _wireView();
  await _loadRedirects();
}

function _wireView() {
  if (_viewWired) return;
  _viewWired = true;

  document
    .getElementById('cmsRedirectsView')
    ?.querySelector('[data-action="cms-redirects-refresh"]')
    ?.addEventListener('click', () => _loadRedirects());

  document
    .getElementById('cmsRedirectsList')
    ?.addEventListener('click', _handleClick);
}

async function _loadRedirects() {
  const container = document.getElementById('cmsRedirectsList');
  container.innerHTML = `
    <div class="spinner-container">
      <div class="spinner-border" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>`;

  try {
    const resp = await fetch(`${API_BASE}/admin/cms/redirects`, {
      headers: _authHeaders(),
    });
    if (!resp.ok) {
      throw new Error(await getErrorDetail(resp, 'Failed to load redirects.'));
    }
    const rows = await resp.json();
    _render(container, Array.isArray(rows) ? rows : []);
  } catch (err) {
    container.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
  }
}

function _render(container, rows) {
  if (!rows.length) {
    container.innerHTML =
      '<div class="alert alert-light border">No redirects recorded.</div>';
    return;
  }
  const body = rows
    .map(
      r => `
      <tr>
        <td><code>${escapeHtml(r.from_slug)}</code></td>
        <td><i class="fas fa-arrow-right text-muted"></i></td>
        <td><code>${escapeHtml(r.to_slug || '')}</code></td>
        <td><small class="text-muted">${r.created_at ? formatDateTime(r.created_at) : '—'}</small></td>
        <td class="text-end">
          <button class="btn btn-sm btn-outline-danger" type="button"
            data-action="cms-redirect-delete"
            data-redirect-id="${escapeHtml(r.id)}"
            data-from-slug="${escapeHtml(r.from_slug)}">
            <i class="fas fa-trash"></i> Delete
          </button>
        </td>
      </tr>`,
    )
    .join('');

  container.innerHTML = `
    <div class="table-responsive">
      <table class="table table-hover align-middle">
        <thead>
          <tr>
            <th>From</th>
            <th></th>
            <th>To</th>
            <th>Created</th>
            <th class="text-end">Actions</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

async function _handleClick(e) {
  const btn = e.target.closest('[data-action="cms-redirect-delete"]');
  if (!btn) return;
  const id = btn.dataset.redirectId;
  const from = btn.dataset.fromSlug || '';
  if (!id) return;
  if (!confirm(`Permanently delete the redirect from "${from}"? This cannot be undone.`)) {
    return;
  }
  try {
    const resp = await fetch(`${API_BASE}/admin/cms/redirects/${id}`, {
      method: 'DELETE',
      headers: _authHeaders(),
    });
    if (!resp.ok && resp.status !== 204) {
      throw new Error(await getErrorDetail(resp, 'Failed to delete redirect.'));
    }
    showAlert('Redirect deleted.', 'success');
    await _loadRedirects();
  } catch (err) {
    showAlert(err.message || 'Failed to delete redirect.', 'danger');
  }
}
