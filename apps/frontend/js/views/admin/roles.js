// frontend/js/views/admin/roles.js
// Admin roles management view — list, create, detail (edit/delete), and cache.
import { API_BASE, ROUTES } from '../../constants.js';
import { escapeHtml, formatDateTime, showAlert, getErrorDetail, parsePermissions } from '../../utils.js';
import { getCurrentUser } from '../../state.js';
import { getAuthToken } from '../../auth.js';

// ── Module-private state ──────────────────────────────────────────────────────
let _rolesPageSkip = 0;
let _allRolesCache = null;
let _currentRoleDetail = null;

const PAGE_LIMIT = 20;

// ── Internal helpers ──────────────────────────────────────────────────────────

function _getAuthToken() {
    return getAuthToken();
}

function _authHeaders(extra = {}) {
    return { 'Authorization': `Bearer ${_getAuthToken()}`, ...extra };
}

// ── Cache accessors (used by admin/users.js) ──────────────────────────────────

/** Returns the cached roles array, or null if not yet fetched. */
export function getAllRolesCache() {
    return _allRolesCache;
}

/**
 * Ensures _allRolesCache is populated. Fetches all roles (no pagination) if the
 * cache is empty. Safe to call multiple times — only one fetch will occur.
 */
export async function ensureRolesCache() {
    if (_allRolesCache !== null) return;

    try {
        const response = await fetch(`${API_BASE}/admin/roles?skip=0&limit=1000`, {
            headers: _authHeaders(),
        });
        if (!response.ok) {
            throw new Error(await getErrorDetail(response, 'Failed to load roles cache.'));
        }
        const payload = await response.json();
        _allRolesCache = payload.items || [];
    } catch (error) {
        console.error('ensureRolesCache:', error);
        _allRolesCache = null; // Do not poison the cache on failure
    }
}

// Clear the cache automatically when the session ends
window.addEventListener('auth:session-cleared', () => {
    _allRolesCache = null;
});

// ── View entry-points ─────────────────────────────────────────────────────────

/**
 * Shows the roles list view and triggers the first page load.
 * Called by the router at path "/roles".
 */
export async function showRolesView() {
    document.getElementById('rolesView').style.display = 'block';
    document.getElementById('pageTitle').textContent = 'Roles - BC Gov';
    _rolesPageSkip = 0;
    _wireRolesView();
    await loadRolesPage();
}

/** Attach delegated event listeners to the static rolesView DOM (idempotent). */
function _wireRolesView() {
    const view = document.getElementById('rolesView');
    if (view.dataset.wired) return;
    view.dataset.wired = '1';

    // Refresh button
    view.querySelector('[data-action="roles-refresh"]')
        ?.addEventListener('click', () => loadRolesPage());

    // Search on Enter
    document.getElementById('rolesSearchInput')
        ?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                _rolesPageSkip = 0;
                loadRolesPage();
            }
        });

    // Toggle create-role form
    view.querySelector('[data-action="toggle-create-role"]')
        ?.addEventListener('click', () => _toggleCreateRoleForm());

    // Create / Cancel buttons inside the form
    view.querySelector('[data-action="create-role-submit"]')
        ?.addEventListener('click', () => createRole());
    view.querySelector('[data-action="create-role-cancel"]')
        ?.addEventListener('click', () => _toggleCreateRoleForm(false));
}

// ── Roles list ────────────────────────────────────────────────────────────────

/** Loads and renders a page of roles. Sets _rolesPageSkip to `skip`. */
export async function loadRolesPage(skip = _rolesPageSkip) {
    _rolesPageSkip = skip;
    const list = document.getElementById('rolesList');
    const search = (document.getElementById('rolesSearchInput')?.value ?? '').trim();

    list.innerHTML = `
        <div class="spinner-container">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>`;

    try {
        const query = new URLSearchParams({
            skip: String(_rolesPageSkip),
            limit: String(PAGE_LIMIT),
        });
        if (search) query.set('q', search);

        const response = await fetch(`${API_BASE}/admin/roles?${query.toString()}`, {
            headers: _authHeaders(),
        });
        if (!response.ok) {
            throw new Error(await getErrorDetail(response, 'Failed to load roles.'));
        }
        const payload = await response.json();
        const items = payload.items || [];

        // Refresh the shared cache whenever we load a fresh list
        _allRolesCache = items;

        if (!items.length) {
            list.innerHTML = '<div class="alert alert-light border">No roles found.</div>';
            return;
        }

        list.innerHTML = `
            <div class="table-responsive">
                <table class="table table-striped table-hover align-middle">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Description</th>
                            <th>Users</th>
                            <th>Permissions</th>
                            <th>Type</th>
                            <th class="text-end">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${items.map(role => `
                            <tr>
                                <td><strong>${escapeHtml(role.name)}</strong></td>
                                <td>${escapeHtml(role.description || '-')}</td>
                                <td>${role.user_count || 0}</td>
                                <td>${(role.permissions || []).map(p =>
                                    `<span class="badge bg-light text-dark me-1">${escapeHtml(p)}</span>`
                                ).join('')}</td>
                                <td>${role.is_system
                                    ? '<span class="badge bg-secondary">System</span>'
                                    : '<span class="badge bg-primary">Custom</span>'}</td>
                                <td class="text-end">
                                    <button class="btn btn-sm btn-outline-primary"
                                        data-action="view-role"
                                        data-role-id="${escapeHtml(role.id)}">View</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        // Delegated listener for "View" buttons
        list.querySelectorAll('[data-action="view-role"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const roleId = btn.dataset.roleId;
                window.history.pushState({}, '', `${ROUTES.ROLES}/${roleId}`);
                window.dispatchEvent(new PopStateEvent('popstate'));
            });
        });
    } catch (error) {
        list.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
    }
}

// ── Create role ───────────────────────────────────────────────────────────────

function _toggleCreateRoleForm(show) {
    const form = document.getElementById('createRoleForm');
    const shouldShow = typeof show === 'boolean' ? show : form.style.display === 'none';
    form.style.display = shouldShow ? 'block' : 'none';
    if (!shouldShow) {
        document.getElementById('newRoleName').value = '';
        document.getElementById('newRoleDescription').value = '';
        document.getElementById('newRolePermissions').value = '';
    }
}

/** Reads the create-role form, POSTs to the API, and refreshes the list. */
export async function createRole() {
    const name = document.getElementById('newRoleName').value.trim();
    const description = document.getElementById('newRoleDescription').value.trim();
    const permissions = parsePermissions(document.getElementById('newRolePermissions').value);

    if (!name) {
        showAlert('Role name is required.', 'warning');
        return;
    }
    if (!permissions.length) {
        showAlert('At least one permission is required.', 'warning');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/admin/roles`, {
            method: 'POST',
            headers: _authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ name, description: description || null, permissions }),
        });
        if (!response.ok) {
            throw new Error(await getErrorDetail(response, 'Failed to create role.'));
        }
        _allRolesCache = null; // invalidate cache after mutation
        showAlert('Role created successfully.', 'success');
        _toggleCreateRoleForm(false);
        await loadRolesPage(0);
    } catch (error) {
        showAlert(error.message, 'danger');
    }
}

// ── Role detail ───────────────────────────────────────────────────────────────

/**
 * Loads a single role from the API and renders the detail/edit UI.
 * Called by the router at path "/roles/:id".
 */
export async function loadRoleDetail(roleId) {
    document.getElementById('roleDetailView').style.display = 'block';
    const container = document.getElementById('roleDetailContent');
    container.innerHTML = `
        <div class="spinner-container">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>`;

    try {
        const response = await fetch(`${API_BASE}/admin/roles/${roleId}`, {
            headers: _authHeaders(),
        });
        if (!response.ok) {
            throw new Error(await getErrorDetail(response, 'Failed to load role detail.'));
        }
        const role = await response.json();
        _currentRoleDetail = role;

        container.innerHTML = `
            <div class="card mb-3">
                <div class="card-body">
                    <div class="row g-2">
                        <div class="col-md-4">
                            <label class="form-label">Role Name</label>
                            <input id="editRoleName" class="form-control"
                                value="${escapeHtml(role.name)}"
                                ${role.is_system ? 'disabled' : ''}>
                        </div>
                        <div class="col-md-8">
                            <label class="form-label">Description</label>
                            <input id="editRoleDescription" class="form-control"
                                value="${escapeHtml(role.description || '')}">
                        </div>
                    </div>
                    <div class="mt-2">
                        <label class="form-label">Permissions (comma-separated)</label>
                        <textarea id="editRolePermissions" class="form-control" rows="3">${escapeHtml(
                            (role.permissions || []).join(', ')
                        )}</textarea>
                    </div>
                    <div class="mt-3 d-flex gap-2">
                        <button class="btn btn-bc-primary" type="button"
                            data-action="save-role-detail">Save</button>
                        ${role.is_system ? '' : `
                        <button class="btn btn-outline-danger" type="button"
                            data-action="delete-role"
                            data-role-id="${escapeHtml(role.id)}">Delete Role</button>`}
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Assigned Users</h5>
                    ${role.users?.length ? `
                        <div class="table-responsive">
                            <table class="table table-sm align-middle mb-0">
                                <thead>
                                    <tr><th>Name</th><th>Email</th><th>Assigned At</th></tr>
                                </thead>
                                <tbody>
                                    ${role.users.map(user => `
                                        <tr>
                                            <td>${escapeHtml(
                                                (`${user.first_name || ''} ${user.last_name || ''}`).trim() || '-'
                                            )}</td>
                                            <td>${escapeHtml(user.email || '-')}</td>
                                            <td>${formatDateTime(user.assigned_at)}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    ` : '<p class="text-muted mb-0">No users are currently assigned to this role.</p>'}
                </div>
            </div>
        `;

        // Wire delegated actions inside the rendered detail block
        container.querySelector('[data-action="save-role-detail"]')
            ?.addEventListener('click', () => saveRoleDetail());
        container.querySelector('[data-action="delete-role"]')
            ?.addEventListener('click', (e) => deleteRole(e.currentTarget.dataset.roleId));
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
    }
}

/** Reads the detail edit form and PUTs the updated role to the API. */
export async function saveRoleDetail() {
    if (!_currentRoleDetail?.id) return;

    const name = document.getElementById('editRoleName').value.trim() || _currentRoleDetail.name;
    const description = document.getElementById('editRoleDescription').value.trim();
    const permissions = parsePermissions(document.getElementById('editRolePermissions').value);

    if (!permissions.length) {
        showAlert('At least one permission is required.', 'warning');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/admin/roles/${_currentRoleDetail.id}`, {
            method: 'PUT',
            headers: _authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ name, description: description || null, permissions }),
        });
        if (!response.ok) {
            throw new Error(await getErrorDetail(response, 'Failed to update role.'));
        }
        _allRolesCache = null; // invalidate cache after mutation
        showAlert('Role updated successfully.', 'success');
        await loadRoleDetail(_currentRoleDetail.id);
    } catch (error) {
        showAlert(error.message, 'danger');
    }
}

/**
 * Deletes a role after confirmation and navigates back to the roles list.
 *
 * @param {string} roleId
 */
export async function deleteRole(roleId) {
    if (!confirm('Delete this role?')) return;

    try {
        const response = await fetch(`${API_BASE}/admin/roles/${roleId}`, {
            method: 'DELETE',
            headers: _authHeaders(),
        });
        if (!response.ok) {
            throw new Error(await getErrorDetail(response, 'Failed to delete role.'));
        }
        _allRolesCache = null; // invalidate cache after mutation
        showAlert('Role deleted.', 'success');
        window.history.pushState({}, '', ROUTES.ROLES);
        window.dispatchEvent(new PopStateEvent('popstate'));
    } catch (error) {
        showAlert(error.message, 'danger');
    }
}
