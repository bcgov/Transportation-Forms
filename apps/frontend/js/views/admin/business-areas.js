// frontend/js/views/admin/business-areas.js
// Admin business areas management view — list, create, detail (edit/delete/contacts).
// FEAT-0025: Business Areas Admin Management CRUD

import { API_BASE, ROUTES, STATUS_LABELS } from '../../constants.js';
import { escapeHtml, formatDateTime, showAlert, getErrorDetail } from '../../utils.js';
import { getAuthToken } from '../../auth.js';

// ── Module-private state ──────────────────────────────────────────────────────
let _currentAreaDetail = null;

// ── Internal helpers ──────────────────────────────────────────────────────────

function _authHeaders(extra = {}) {
  return { Authorization: `Bearer ${getAuthToken()}`, ...extra };
}

function _jsonHeaders() {
  return _authHeaders({ 'Content-Type': 'application/json' });
}

// ── List view ─────────────────────────────────────────────────────────────────

export async function showBusinessAreasAdminView() {
  document.getElementById('businessAreasView').style.display = 'block';
  document.getElementById('pageTitle').textContent = 'Business Areas - BC Gov';
  _wireBusinessAreasAdminView();
  await loadBusinessAreasList();
}

function _wireBusinessAreasAdminView() {
  const view = document.getElementById('businessAreasView');
  if (view.dataset.wired) return;
  view.dataset.wired = '1';

  view.querySelector('[data-action="ba-admin-refresh"]')
    ?.addEventListener('click', () => loadBusinessAreasList());
}

async function loadBusinessAreasList() {
  const list = document.getElementById('businessAreasAdminList');

  list.innerHTML = `
    <div class="spinner-container">
      <div class="spinner-border" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>`;

  try {
    const response = await fetch(`${API_BASE}/admin/business-areas`, {
      headers: _authHeaders(),
    });
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to load business areas.'));
    }

    let items = await response.json();
    
    // sorting alphabetically by Name ascending
    items.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));

    if (!items.length) {
      list.innerHTML = '<div class="alert alert-light border">No business areas found.</div>';
      return;
    }

    list.innerHTML = `
      <div class="table-responsive">
        <table class="table table-striped table-hover align-middle">
          <thead>
            <tr>
              <th>Name</th>
              <th>Mailbox</th>
              <th>Contacts</th>
              <th>Linked Forms</th>
              <th class="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${items
              .map(
                p => `
              <tr>
                <td><strong>${escapeHtml(p.name)}</strong></td>
                <td>${escapeHtml(p.mailbox || '-')}</td>
                <td>${p.contact_count}</td>
                <td>${p.linked_forms_count}</td>
                <td class="text-end">
                  <button class="btn btn-sm btn-outline-primary"
                    data-action="view-ba"
                    data-ba-id="${escapeHtml(p.id)}">View</button>
                </td>
              </tr>`,
              )
              .join('')}
          </tbody>
        </table>
      </div>`;

    list.querySelectorAll('[data-action="view-ba"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const baId = btn.dataset.baId;
        window.history.pushState({}, '', `${ROUTES.BUSINESS_AREAS}/${baId}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
      });
    });
  } catch (error) {
    list.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
  }
}

// ── Create view ───────────────────────────────────────────────────────────────

export async function showBusinessAreaCreateView() {
  document.getElementById('businessAreaCreateView').style.display = 'block';
  document.getElementById('pageTitle').textContent = 'New Business Area - BC Gov';
  _wireBusinessAreaCreateView();
  // Reset fields
  document.getElementById('newBaName').value = '';
  document.getElementById('newBaMailbox').value = '';
}

function _wireBusinessAreaCreateView() {
  const view = document.getElementById('businessAreaCreateView');
  if (view.dataset.wired) return;
  view.dataset.wired = '1';

  view.querySelector('[data-action="create-ba-submit"]')
    ?.addEventListener('click', () => _submitCreateBusinessArea());
}

async function _submitCreateBusinessArea() {
  const name = (document.getElementById('newBaName').value || '').trim();
  const mailbox = (document.getElementById('newBaMailbox').value || '').trim();

  if (!name) {
    showAlert('Name is required.', 'warning');
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/admin/business-areas`, {
      method: 'POST',
      headers: _jsonHeaders(),
      body: JSON.stringify({
        name,
        mailbox: mailbox || null
      }),
    });
    
    if (response.status === 409) {
      // AC3: A soft-deleted Business Area with this Name already exists.
      // The backend returns a structured detail of the form
      //   { code: 'soft_deleted_collision', message: '...', existing_id: '<uuid>' }
      // Confirm with the admin and, if accepted, call the restore endpoint
      // and navigate to the restored area's detail view.
      let payload = null;
      try {
        const body = await response.json();
        payload = body && typeof body.detail === 'object' ? body.detail : null;
      } catch (_) {
        payload = null;
      }

      const promptMessage = (payload && payload.message)
        || 'A deleted Business Area with this name already exists. Would you like to restore it instead?';

      if (!payload || payload.code !== 'soft_deleted_collision' || !payload.existing_id) {
        throw new Error(promptMessage);
      }

      if (!confirm(promptMessage)) {
        return;
      }

      const restoreResponse = await fetch(
        `${API_BASE}/admin/business-areas/${encodeURIComponent(payload.existing_id)}/restore`,
        { method: 'POST', headers: _jsonHeaders() }
      );
      if (!restoreResponse.ok) {
        throw new Error(await getErrorDetail(restoreResponse, 'Failed to restore business area.'));
      }
      const restored = await restoreResponse.json();
      showAlert('Business Area restored successfully.', 'success');
      window.history.pushState({}, '', `${ROUTES.BUSINESS_AREAS}/${restored.id}`);
      window.dispatchEvent(new PopStateEvent('popstate'));
      return;
    }
    
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to create business area.'));
    }
    
    const newArea = await response.json();
    showAlert('Business Area created successfully.', 'success');
    window.history.pushState({}, '', `${ROUTES.BUSINESS_AREAS}/${newArea.id}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  } catch (error) {
    showAlert(error.message, 'danger');
  }
}

// ── Detail view ───────────────────────────────────────────────────────────────

export async function showBusinessAreaDetailView(baId) {
  document.getElementById('businessAreaDetailView').style.display = 'block';
  document.getElementById('pageTitle').textContent = 'Business Area Detail - BC Gov';
  await _loadBusinessAreaDetail(baId);
}

async function _loadBusinessAreaDetail(baId) {
  const container = document.getElementById('businessAreaDetailContent');
  container.innerHTML = `
    <div class="spinner-container">
      <div class="spinner-border" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>`;

  try {
    // We don't have a direct GET /{id} for business areas yet in the backend
    // Fetch all and find the required one
    const response = await fetch(`${API_BASE}/admin/business-areas`, {
      headers: _authHeaders(),
    });
    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to load business areas.'));
    }
    const allAreas = await response.json();
    const detail = allAreas.find(a => a.id === baId);
    
    if (!detail) throw new Error('Business Area not found.');

    // Fetch contacts
    const contactsRes = await fetch(`${API_BASE}/admin/business-areas/${baId}/contacts`, { headers: _authHeaders() });
    const contacts = contactsRes.ok ? await contactsRes.json() : [];

    // Fetch linked forms
    const formsRes = await fetch(`${API_BASE}/admin/business-areas/${baId}/forms`, { headers: _authHeaders() });
    const forms = formsRes.ok ? await formsRes.json() : [];

    _currentAreaDetail = { ...detail, contacts, linked_forms: forms, allAreas }; // keep allAreas for reassignment logic
    
    _renderDetail(container, _currentAreaDetail);
  } catch (error) {
    container.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
  }
}

function _renderDetail(container, detail) {
  const hasLinked = detail.linked_forms_count > 0;

  container.innerHTML = `
    <!-- Config card -->
    <div class="card mb-3">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span><strong>${escapeHtml(detail.name)}</strong></span>
        <div class="d-flex gap-2">
          <button class="btn btn-sm btn-outline-danger" type="button" data-action="delete-ba"><i class="fas fa-trash"></i> Delete</button>
        </div>
      </div>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-md-6">
            <label class="form-label">Name</label>
            <input id="editBaName" class="form-control" value="${escapeHtml(detail.name)}" maxlength="75">
          </div>
          <div class="col-md-6">
            <label class="form-label">Mailbox</label>
            <input id="editBaMailbox" class="form-control" type="email" value="${escapeHtml(detail.mailbox || '')}" maxlength="75">
          </div>
        </div>
        <div class="mt-3">
          <button class="btn btn-bc-primary" type="button" data-action="save-ba"><i class="fas fa-save"></i> Save Changes</button>
        </div>
      </div>
    </div>

    <!-- Tabs: Contacts + Linked Forms -->
    <ul class="nav nav-tabs" role="tablist">
      <li class="nav-item" role="presentation">
        <button class="nav-link active" id="tab-contacts" data-bs-toggle="tab" data-bs-target="#pane-contacts"
          type="button" role="tab">Contacts (${detail.contacts.length})</button>
      </li>
      <li class="nav-item" role="presentation">
        <button class="nav-link" id="tab-forms" data-bs-toggle="tab" data-bs-target="#pane-forms"
          type="button" role="tab">Linked Forms (${detail.linked_forms.length})</button>
      </li>
    </ul>
    <div class="tab-content border border-top-0 rounded-bottom p-3 mb-4">
      <div class="tab-pane fade show active" id="pane-contacts" role="tabpanel">
        
        <div class="mb-3">
          <form id="addBaContactForm" class="row g-2 align-items-end">
             <div class="col-md-4">
               <label class="form-label mb-0 small">Name</label>
               <input class="form-control form-control-sm" id="newContactName" placeholder="Name" maxlength="150" required>
             </div>
             <div class="col-md-4">
               <label class="form-label mb-0 small">Email</label>
               <input class="form-control form-control-sm" id="newContactEmail" type="email" placeholder="Email" maxlength="75" required>
             </div>
             <div class="col-md-4">
               <button type="button" class="btn btn-sm btn-primary" data-action="add-contact">Add Contact</button>
             </div>
          </form>
        </div>

        ${_renderContactsTable(detail.contacts)}
      </div>
      <div class="tab-pane fade" id="pane-forms" role="tabpanel">
        ${_renderLinkedFormsTable(detail.linked_forms)}
      </div>
    </div>
  `;

  // Wire actions
  container.querySelector('[data-action="save-ba"]')
    ?.addEventListener('click', () => _saveBusinessArea());
  container.querySelector('[data-action="delete-ba"]')
    ?.addEventListener('click', () => _deleteBusinessArea());
  container.querySelector('[data-action="add-contact"]')
    ?.addEventListener('click', () => _addContact());
    
  container.querySelectorAll('[data-action="remove-contact"]').forEach(btn => {
    btn.addEventListener('click', (e) => _removeContact(e.target.closest('button').dataset.id));
  });

  // Reassignment Modal logic
  if (!document.getElementById('baDeleteModal')) {
    const modalHtml = `
      <div class="modal fade" id="baDeleteModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">Delete Business Area</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <p id="baDeleteModalMessage"></p>
              <div id="baDeleteModalReassignGroup" class="mb-3" style="display:none;">
                <label class="form-label">Select target Business Area for Reassignment:</label>
                <select id="baDeleteModalTarget" class="form-select"></select>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="button" class="btn btn-warning" id="baDeleteModalSoft" style="display:none;">Soft Delete instead</button>
              <button type="button" class="btn btn-danger" id="baDeleteModalHard">Delete</button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
  }
}

function _renderContactsTable(contacts) {
  if (!contacts.length) {
    return '<p class="text-muted mb-0">No contacts assigned.</p>';
  }
  return `
    <div class="table-responsive">
      <table class="table table-sm table-striped align-middle mb-0">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th class="text-end">Actions</th>
          </tr>
        </thead>
        <tbody>
          ${contacts
            .map(
              c => `
            <tr>
              <td>${escapeHtml(c.name || '-')}</td>
              <td>${escapeHtml(c.email || '-')}</td>
              <td class="text-end">
                 <button class="btn btn-sm btn-outline-danger" data-action="remove-contact" data-id="${c.id}"><i class="fas fa-times"></i> Remove</button>
              </td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
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
            <th>Form Number</th>
            <th>Title</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          ${forms
            .map(
              f => `
            <tr>
              <td><a href="/edit/${f.id}" target="_blank" rel="noopener noreferrer">${escapeHtml(f.form_number)}</a></td>
              <td>${escapeHtml(f.title)}</td>
              <td><span class="badge bg-info">${escapeHtml(f.status)}</span></td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
}

// ── Detail actions ────────────────────────────────────────────────────────────

async function _saveBusinessArea() {
  if (!_currentAreaDetail?.id) return;

  const name = (document.getElementById('editBaName').value || '').trim();
  const mailbox = (document.getElementById('editBaMailbox').value || '').trim();

  try {
    const response = await fetch(`${API_BASE}/admin/business-areas/${_currentAreaDetail.id}`, {
      method: 'PUT',
      headers: _jsonHeaders(),
      body: JSON.stringify({ name, mailbox: mailbox || null }),
    });
    if (!response.ok) {
      if (response.status === 400) {
         throw new Error('Validation failed or name already exists.');
      }
      throw new Error(await getErrorDetail(response, 'Failed to update business area.'));
    }
    showAlert('Business Area updated successfully.', 'success');
    await _loadBusinessAreaDetail(_currentAreaDetail.id);
  } catch (error) {
    showAlert(error.message, 'danger');
  }
}

async function _deleteBusinessArea() {
  if (!_currentAreaDetail?.id) return;

  const count = _currentAreaDetail.linked_forms_count;
  
  if (count === 0) {
      if (!confirm(`Are you sure you want to permanently delete "${_currentAreaDetail.name}"?`)) return;
      await _executeDelete(_currentAreaDetail.id);
  } else {
      // Show modal for Reassignment / Soft-delete
      const myModalEl = document.getElementById('baDeleteModal');
      const myModal = new bootstrap.Modal(myModalEl);
      
      const msg = document.getElementById('baDeleteModalMessage');
      msg.textContent = `This Business Area is referenced by ${count} forms.\nPlease choose an action:`;
      
      const select = document.getElementById('baDeleteModalTarget');
      select.innerHTML = '<option value="">-- Select Target --</option>' + _currentAreaDetail.allAreas
          .filter(a => a.id !== _currentAreaDetail.id)
          .map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');
          
      document.getElementById('baDeleteModalReassignGroup').style.display = 'block';
      const btnSoft = document.getElementById('baDeleteModalSoft');
      const btnHard = document.getElementById('baDeleteModalHard');
      
      btnSoft.style.display = 'inline-block';
      btnHard.textContent = 'Reassign & Delete';
      
      const _cleanupListeners = () => {
         btnSoft.replaceWith(btnSoft.cloneNode(true));
         btnHard.replaceWith(btnHard.cloneNode(true));
      };
      
      _cleanupListeners();
      
      myModalEl.addEventListener('hidden.bs.modal', _cleanupListeners, { once: true });
      
      document.getElementById('baDeleteModalSoft').addEventListener('click', async () => {
          myModal.hide();
          await _executeDelete(_currentAreaDetail.id);
      });
      
      document.getElementById('baDeleteModalHard').addEventListener('click', async () => {
          const targetId = document.getElementById('baDeleteModalTarget').value;
          if (!targetId) {
             showAlert('Please select a target Business Area for reassignment.', 'warning');
             return;
          }
          myModal.hide();
          await _executeDelete(_currentAreaDetail.id, targetId);
      });
      
      myModal.show();
  }
}

async function _executeDelete(id, replacementId = null) {
    try {
        let url = `${API_BASE}/admin/business-areas/${id}`;
        if (replacementId) {
            url += `?replacement_id=${replacementId}`;
        }
        const response = await fetch(url, {
          method: 'DELETE',
          headers: _authHeaders(),
        });
        if (!response.ok) {
          throw new Error(await getErrorDetail(response, 'Failed to delete business area.'));
        }
        showAlert('Business Area deleted.', 'success');
        window.history.pushState({}, '', ROUTES.BUSINESS_AREAS);
        window.dispatchEvent(new PopStateEvent('popstate'));
    } catch (error) {
        showAlert(error.message, 'danger');
    }
}

async function _addContact() {
    const name = document.getElementById('newContactName').value.trim();
    const email = document.getElementById('newContactEmail').value.trim();
    
    if (!name || !email) {
        showAlert('Name and Email are required.', 'warning');
        return;
    }
    
    try {
      const response = await fetch(`${API_BASE}/admin/business-areas/${_currentAreaDetail.id}/contacts`, {
        method: 'POST',
        headers: _jsonHeaders(),
        body: JSON.stringify({ name, email }),
      });
      if (!response.ok) {
        throw new Error(await getErrorDetail(response, 'Failed to add contact.'));
      }
      showAlert('Contact added successfully.', 'success');
      await _loadBusinessAreaDetail(_currentAreaDetail.id);
    } catch (error) {
      showAlert(error.message, 'danger');
    }
}

async function _removeContact(contactId) {
    if (!confirm('Remove this contact?')) return;
    
    try {
      const response = await fetch(`${API_BASE}/admin/business-areas/${_currentAreaDetail.id}/contacts/${contactId}`, {
        method: 'DELETE',
        headers: _authHeaders(),
      });
      if (!response.ok) {
        throw new Error(await getErrorDetail(response, 'Failed to remove contact.'));
      }
      showAlert('Contact removed successfully.', 'success');
      await _loadBusinessAreaDetail(_currentAreaDetail.id);
    } catch (error) {
      showAlert(error.message, 'danger');
    }
}
