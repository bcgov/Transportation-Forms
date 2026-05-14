// frontend/js/views/admin/prefixes.js
// Admin prefix management view — list, create, detail (edit/archive/delete).
// FEAT-0012: Form Number Prefix Management CRUD

import { API_BASE, ROUTES, STATUS_LABELS } from '../../constants.js';
import { escapeHtml, formatDateTime, showAlert, getErrorDetail } from '../../utils.js';
import { getAuthToken } from '../../auth.js';

// ── Module-private state ──────────────────────────────────────────────────────
let _currentPrefixDetail = null;

// ── Internal helpers ──────────────────────────────────────────────────────────

function _authHeaders(extra = {}) {
  return { Authorization: `Bearer ${getAuthToken()}`, ...extra };
}

function _jsonHeaders() {
  return _authHeaders({ 'Content-Type': 'application/json' });
}

function _statusBadge(isActive) {
  return isActive
    ? '<span class="badge bg-success">Active</span>'
    : '<span class="badge bg-secondary">Archived</span>';
}

// ── List view ─────────────────────────────────────────────────────────────────

export async function showPrefixesView() {
  document.getElementById('prefixesView').style.display = 'block';
  document.getElementById('pageTitle').textContent = 'Prefixes - BC Gov';
  _wirePrefixesView();
  await loadPrefixesList();
}

function _wirePrefixesView() {
  const view = document.getElementById('prefixesView');
  if (view.dataset.wired) return;
  view.dataset.wired = '1';

  view.querySelector('[data-action="prefixes-refresh"]')
    ?.addEventListener('click', () => loadPrefixesList());

  document.getElementById('prefixStatusFilter')
    ?.addEventListener('change', () => loadPrefixesList());
}

async function loadPrefixesList() {
  const list = document.getElementById('prefixesList');
  const filterValue = document.getElementById('prefixStatusFilter')?.value ?? '';

  list.innerHTML = `
    <div class="spinner-container">
      <div class="spinner-border" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>`;

  try {
    const response = await fetch(`${API_BASE}/admin/prefixes`, {
      headers: _authHeaders(),
    });
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to load prefixes.'));
    }

    let items = await response.json();

    // Client-side filter
    if (filterValue === 'active') {
      items = items.filter(p => p.is_active);
    } else if (filterValue === 'archived') {
      items = items.filter(p => !p.is_active);
    }

    if (!items.length) {
      list.innerHTML = '<div class="alert alert-light border">No prefixes found.</div>';
      return;
    }

    list.innerHTML = `
      <div class="table-responsive">
        <table class="table table-striped table-hover align-middle">
          <thead>
            <tr>
              <th>Prefix</th>
              <th>Description</th>
              <th>Sequence</th>
              <th>Padding</th>
              <th>Status</th>
              <th>Updated</th>
              <th class="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${items
              .map(
                p => `
              <tr>
                <td><strong>${escapeHtml(p.prefix)}</strong></td>
                <td>${escapeHtml(p.description || '-')}</td>
                <td>${p.current_sequence}</td>
                <td>${p.padding_length}</td>
                <td>${_statusBadge(p.is_active)}</td>
                <td>${formatDateTime(p.updated_at)}</td>
                <td class="text-end">
                  <button class="btn btn-sm btn-outline-primary"
                    data-action="view-prefix"
                    data-prefix-id="${escapeHtml(p.id)}">View</button>
                </td>
              </tr>`,
              )
              .join('')}
          </tbody>
        </table>
      </div>`;

    list.querySelectorAll('[data-action="view-prefix"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const prefixId = btn.dataset.prefixId;
        window.history.pushState({}, '', `${ROUTES.PREFIXES}/${prefixId}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
      });
    });
  } catch (error) {
    list.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
  }
}

// ── Create view ───────────────────────────────────────────────────────────────

export async function showPrefixCreateView() {
  document.getElementById('prefixCreateView').style.display = 'block';
  document.getElementById('pageTitle').textContent = 'New Prefix - BC Gov';
  _wirePrefixCreateView();
  // Reset fields
  document.getElementById('newPrefixCode').value = '';
  document.getElementById('newPrefixDescription').value = '';
  document.getElementById('newPrefixSequence').value = '0';
  document.getElementById('newPrefixPadding').value = '4';
  document.getElementById('newPrefixMaxLen').value = '10';
  document.getElementById('newPrefixCaseSensitive').checked = false;
}

function _wirePrefixCreateView() {
  const view = document.getElementById('prefixCreateView');
  if (view.dataset.wired) return;
  view.dataset.wired = '1';

  view.querySelector('[data-action="create-prefix-submit"]')
    ?.addEventListener('click', () => _submitCreatePrefix());
}

async function _submitCreatePrefix() {
  const prefix = (document.getElementById('newPrefixCode').value || '').trim();
  const description = (document.getElementById('newPrefixDescription').value || '').trim();
  const currentSequence = parseInt(document.getElementById('newPrefixSequence').value, 10) || 0;
  const paddingLength = parseInt(document.getElementById('newPrefixPadding').value, 10) || 4;
  const maxNumberLength = parseInt(document.getElementById('newPrefixMaxLen').value, 10) || 10;
  const isCaseSensitive = document.getElementById('newPrefixCaseSensitive').checked;

  if (!prefix) {
    showAlert('Prefix is required.', 'warning');
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/admin/prefixes`, {
      method: 'POST',
      headers: _jsonHeaders(),
      body: JSON.stringify({
        prefix,
        description: description || null,
        current_sequence: currentSequence,
        padding_length: paddingLength,
        max_number_length: maxNumberLength,
        is_case_sensitive: isCaseSensitive,
      }),
    });
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to create prefix.'));
    }
    showAlert('Prefix created successfully.', 'success');
    window.history.pushState({}, '', ROUTES.PREFIXES);
    window.dispatchEvent(new PopStateEvent('popstate'));
  } catch (error) {
    showAlert(error.message, 'danger');
  }
}

// ── Detail view ───────────────────────────────────────────────────────────────

export async function showPrefixDetailView(prefixId) {
  document.getElementById('prefixDetailView').style.display = 'block';
  document.getElementById('pageTitle').textContent = 'Prefix Detail - BC Gov';
  await _loadPrefixDetail(prefixId);
}

async function _loadPrefixDetail(prefixId) {
  const container = document.getElementById('prefixDetailContent');
  container.innerHTML = `
    <div class="spinner-container">
      <div class="spinner-border" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>`;

  try {
    const response = await fetch(`${API_BASE}/admin/prefixes/${prefixId}`, {
      headers: _authHeaders(),
    });
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to load prefix detail.'));
    }
    const detail = await response.json();
    _currentPrefixDetail = detail;
    _renderDetail(container, detail);
  } catch (error) {
    container.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
  }
}

function _renderDetail(container, detail) {
  const isArchived = !detail.is_active;
  const hasLinked = detail.has_linked_forms;

  container.innerHTML = `
    <!-- Config card -->
    <div class="card mb-3">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span><strong>${escapeHtml(detail.prefix)}</strong> ${_statusBadge(detail.is_active)}</span>
        <div class="d-flex gap-2">
          ${!isArchived ? `<button class="btn btn-sm btn-warning" type="button" data-action="archive-prefix"><i class="fas fa-archive"></i> Archive</button>` : ''}
          <button class="btn btn-sm btn-outline-danger" type="button" data-action="delete-prefix"><i class="fas fa-trash"></i> Delete</button>
        </div>
      </div>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-md-4">
            <label class="form-label">Prefix</label>
            <input id="editPrefixCode" class="form-control" value="${escapeHtml(detail.prefix)}"
              maxlength="10" ${hasLinked ? 'disabled title="Cannot change — linked forms exist"' : ''} ${isArchived ? 'disabled' : ''}>
            ${hasLinked ? '<div class="form-text text-warning"><i class="fas fa-lock"></i> Locked — linked forms exist</div>' : ''}
          </div>
          <div class="col-md-4">
            <label class="form-label">Current Sequence</label>
            <div class="input-group">
              <input id="editPrefixSequence" class="form-control" type="number" min="0"
                value="${detail.current_sequence}" ${isArchived ? 'disabled' : ''}>
              ${!isArchived ? '<button class="btn btn-outline-secondary" type="button" data-action="check-sequence"><i class="fas fa-search"></i> Check</button>' : ''}
            </div>
          </div>
          <div class="col-md-4">
            <label class="form-label">Padding Length</label>
            <input id="editPrefixPadding" class="form-control" type="number" min="1" max="20"
              value="${detail.padding_length}" ${isArchived ? 'disabled' : ''}>
          </div>
          <div class="col-md-8">
            <label class="form-label">Description</label>
            <input id="editPrefixDescription" class="form-control" value="${escapeHtml(detail.description || '')}"
              maxlength="500" ${isArchived ? 'disabled' : ''}>
          </div>
          <div class="col-md-2">
            <label class="form-label">Max Num Length</label>
            <input id="editPrefixMaxLen" class="form-control" type="number" min="1" max="50"
              value="${detail.max_number_length}" ${isArchived ? 'disabled' : ''}>
          </div>
          <div class="col-md-2 d-flex align-items-end">
            <div class="form-check">
              <input class="form-check-input" type="checkbox" id="editPrefixCaseSensitive"
                ${detail.is_case_sensitive ? 'checked' : ''} ${isArchived ? 'disabled' : ''}>
              <label class="form-check-label" for="editPrefixCaseSensitive">Case Sensitive</label>
            </div>
          </div>
        </div>
        <div class="mt-2 text-muted small">
          Created by ${escapeHtml(detail.created_by_name || '-')} on ${formatDateTime(detail.created_at)}
          ${detail.updated_by_name ? ` · Updated by ${escapeHtml(detail.updated_by_name)} on ${formatDateTime(detail.updated_at)}` : ''}
        </div>
        ${!isArchived ? `<div class="mt-3"><button class="btn btn-bc-primary" type="button" data-action="save-prefix"><i class="fas fa-save"></i> Save Changes</button></div>` : ''}
      </div>
    </div>

    <!-- Sequence conflict result -->
    <div id="sequenceConflictResult" class="mb-3" style="display:none;"></div>

    <!-- Tabs: Reservation History + Linked Forms -->
    <ul class="nav nav-tabs" role="tablist">
      <li class="nav-item" role="presentation">
        <button class="nav-link active" id="tab-history" data-bs-toggle="tab" data-bs-target="#pane-history"
          type="button" role="tab">Reservation History (${detail.reservation_history.length})</button>
      </li>
      <li class="nav-item" role="presentation">
        <button class="nav-link" id="tab-forms" data-bs-toggle="tab" data-bs-target="#pane-forms"
          type="button" role="tab">Linked Forms (${detail.linked_forms.length})</button>
      </li>
    </ul>
    <div class="tab-content border border-top-0 rounded-bottom p-3 mb-4">
      <div class="tab-pane fade show active" id="pane-history" role="tabpanel">
        ${_renderHistoryTable(detail.reservation_history)}
      </div>
      <div class="tab-pane fade" id="pane-forms" role="tabpanel">
        ${_renderLinkedFormsTable(detail.linked_forms)}
      </div>
    </div>
  `;

  // Wire actions
  container.querySelector('[data-action="save-prefix"]')
    ?.addEventListener('click', () => _savePrefix());
  container.querySelector('[data-action="archive-prefix"]')
    ?.addEventListener('click', () => _archivePrefix());
  container.querySelector('[data-action="delete-prefix"]')
    ?.addEventListener('click', () => _deletePrefix());
  container.querySelector('[data-action="check-sequence"]')
    ?.addEventListener('click', () => _checkSequence());
}

function _renderHistoryTable(history) {
  if (!history.length) {
    return '<p class="text-muted mb-0">No reservation history.</p>';
  }
  return `
    <div class="table-responsive">
      <table class="table table-sm table-striped align-middle mb-0">
        <thead>
          <tr>
            <th>Form Number</th>
            <th>Method</th>
            <th>Status</th>
            <th>Reserved By</th>
            <th>Created</th>
            <th>Expires</th>
          </tr>
        </thead>
        <tbody>
          ${history
            .map(
              r => `
            <tr>
              <td><code>${escapeHtml(r.full_form_number)}</code></td>
              <td>${escapeHtml(r.numbering_method)}</td>
              <td>${_reservationStatusBadge(r.status)}</td>
              <td>${escapeHtml(r.reserved_by_name || '-')}</td>
              <td>${formatDateTime(r.created_at)}</td>
              <td>${r.expires_at ? formatDateTime(r.expires_at) : '-'}</td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
}

function _reservationStatusBadge(st) {
  const colors = {
    reserved: 'bg-primary',
    pending_approval: 'bg-warning text-dark',
    approved: 'bg-success',
    rejected: 'bg-danger',
    changes_requested: 'bg-info',
    released: 'bg-secondary',
    expired: 'bg-dark',
  };
  const label = STATUS_LABELS[st] || st;
  return `<span class="badge ${colors[st] || 'bg-secondary'}">${escapeHtml(label)}</span>`;
}

function _renderLinkedFormsTable(forms) {
  if (!forms.length) {
    return '<p class="text-muted mb-0">No linked forms.</p>';
  }
  return `
    <div class="table-responsive">
      <table class="table table-sm table-striped align-middle mb-0">
        <thead>
          <tr>
            <th>Title</th>
            <th>Status</th>
            <th>Created By</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          ${forms
            .map(
              f => `
            <tr>
              <td>${escapeHtml(f.title)}</td>
              <td><span class="badge bg-info">${escapeHtml(f.status)}</span></td>
              <td>${escapeHtml(f.created_by_name || '-')}</td>
              <td>${formatDateTime(f.created_at)}</td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
}

// ── Detail actions ────────────────────────────────────────────────────────────

async function _savePrefix() {
  if (!_currentPrefixDetail?.id) return;

  const body = {};

  const prefixCode = (document.getElementById('editPrefixCode').value || '').trim();
  if (prefixCode && prefixCode !== _currentPrefixDetail.prefix) {
    body.prefix = prefixCode;
  }

  const description = (document.getElementById('editPrefixDescription').value || '').trim();
  body.description = description || null;

  const seq = parseInt(document.getElementById('editPrefixSequence').value, 10);
  if (!isNaN(seq) && seq !== _currentPrefixDetail.current_sequence) {
    body.current_sequence = seq;
  }

  const pad = parseInt(document.getElementById('editPrefixPadding').value, 10);
  if (!isNaN(pad) && pad !== _currentPrefixDetail.padding_length) {
    body.padding_length = pad;
  }

  const maxLen = parseInt(document.getElementById('editPrefixMaxLen').value, 10);
  if (!isNaN(maxLen) && maxLen !== _currentPrefixDetail.max_number_length) {
    body.max_number_length = maxLen;
  }

  const caseSensitive = document.getElementById('editPrefixCaseSensitive').checked;
  if (caseSensitive !== _currentPrefixDetail.is_case_sensitive) {
    body.is_case_sensitive = caseSensitive;
  }

  try {
    const response = await fetch(`${API_BASE}/admin/prefixes/${_currentPrefixDetail.id}`, {
      method: 'PUT',
      headers: _jsonHeaders(),
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to update prefix.'));
    }
    showAlert('Prefix updated successfully.', 'success');
    await _loadPrefixDetail(_currentPrefixDetail.id);
  } catch (error) {
    showAlert(error.message, 'danger');
  }
}

async function _archivePrefix() {
  if (!_currentPrefixDetail?.id) return;
  if (!confirm(`Archive prefix "${_currentPrefixDetail.prefix}"? It will no longer appear in public lists.`)) return;

  try {
    const response = await fetch(`${API_BASE}/admin/prefixes/${_currentPrefixDetail.id}/archive`, {
      method: 'POST',
      headers: _authHeaders(),
    });
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to archive prefix.'));
    }
    showAlert('Prefix archived.', 'success');
    await _loadPrefixDetail(_currentPrefixDetail.id);
  } catch (error) {
    showAlert(error.message, 'danger');
  }
}

async function _deletePrefix() {
  if (!_currentPrefixDetail?.id) return;
  if (!confirm(`Delete prefix "${_currentPrefixDetail.prefix}"? This action cannot be undone.`)) return;

  try {
    const response = await fetch(`${API_BASE}/admin/prefixes/${_currentPrefixDetail.id}`, {
      method: 'DELETE',
      headers: _authHeaders(),
    });
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to delete prefix.'));
    }
    showAlert('Prefix deleted.', 'success');
    window.history.pushState({}, '', ROUTES.PREFIXES);
    window.dispatchEvent(new PopStateEvent('popstate'));
  } catch (error) {
    showAlert(error.message, 'danger');
  }
}

async function _checkSequence() {
  if (!_currentPrefixDetail?.id) return;

  const proposed = parseInt(document.getElementById('editPrefixSequence').value, 10);
  if (isNaN(proposed) || proposed < 0) {
    showAlert('Enter a valid sequence number (≥ 0).', 'warning');
    return;
  }

  const resultDiv = document.getElementById('sequenceConflictResult');

  try {
    const response = await fetch(
      `${API_BASE}/admin/prefixes/${_currentPrefixDetail.id}/check-sequence`,
      {
        method: 'POST',
        headers: _jsonHeaders(),
        body: JSON.stringify({ proposed_sequence: proposed }),
      },
    );
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to check sequence.'));
    }

    const data = await response.json();
    resultDiv.style.display = 'block';

    if (data.has_conflicts) {
      resultDiv.innerHTML = `
        <div class="alert alert-warning mb-0">
          <i class="fas fa-exclamation-triangle"></i>
          <strong>Sequence conflict detected.</strong>
          Conflicting reservation numbers: <strong>${data.conflicting_numbers.join(', ')}</strong>.
          Suggested safe sequence: <strong>${data.suggested_sequence}</strong>.
          <button class="btn btn-sm btn-outline-warning ms-2" type="button" data-action="apply-suggested-sequence">
            Apply Suggested
          </button>
        </div>`;
      resultDiv.querySelector('[data-action="apply-suggested-sequence"]')
        ?.addEventListener('click', () => {
          document.getElementById('editPrefixSequence').value = data.suggested_sequence;
          resultDiv.style.display = 'none';
        });
    } else {
      resultDiv.innerHTML = `
        <div class="alert alert-success mb-0">
          <i class="fas fa-check-circle"></i> No sequence conflicts detected. Safe to use sequence <strong>${proposed}</strong>.
        </div>`;
    }
  } catch (error) {
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = `<div class="alert alert-danger mb-0">${escapeHtml(error.message)}</div>`;
  }
}
