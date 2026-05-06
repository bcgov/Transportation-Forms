// frontend/js/views/admin/users.js
// Admin user management view — list with search/pagination and detail with role assignment.
import { API_BASE, ROUTES } from '../../constants.js';
import { escapeHtml, formatDateTime, showAlert, getErrorDetail } from '../../utils.js';
import { getCurrentUser } from '../../state.js';
import { getAllRolesCache, ensureRolesCache } from './roles.js';
import { getAuthToken } from '../../auth.js';

// ── Module-private state ──────────────────────────────────────────────────────
let _usersPageSkip = 0;
const _adminPageLimit = 20;
let _currentUserDetail = null;

// ── Internal helpers ──────────────────────────────────────────────────────────

function _getAuthToken() {
    return getAuthToken();
}

function _authHeaders(extra = {}) {
    return { 'Authorization': `Bearer ${_getAuthToken()}`, ...extra };
}

// ── View entry-points ─────────────────────────────────────────────────────────

/**
 * Shows the users list view and loads the first page.
 * Called by the router at path "/users".
 */
export async function showUsersView() {
    document.getElementById('usersView').style.display = 'block';
    document.getElementById('pageTitle').textContent = 'Users - BC Gov';
    _usersPageSkip = 0;
    _wireUsersView();
    await loadUsersPage();
}

/** Attach delegated event listeners to the static usersView DOM (idempotent). */
function _wireUsersView() {
    const view = document.getElementById('usersView');
    if (view.dataset.wired) return;
    view.dataset.wired = '1';

    // Refresh button
    view.querySelector('[data-action="users-refresh"]')
        ?.addEventListener('click', () => loadUsersPage());

    // Search input — trigger on Enter
    document.getElementById('usersSearchInput')
        ?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                _usersPageSkip = 0;
                loadUsersPage();
            }
        });

    // Search button
    view.querySelector('[data-action="users-search"]')
        ?.addEventListener('click', () => {
            _usersPageSkip = 0;
            loadUsersPage();
        });
}

// ── Users list ────────────────────────────────────────────────────────────────

/**
 * Loads and renders a page of users. Updates _usersPageSkip.
 *
 * @param {number} [skip]
 */
export async function loadUsersPage(skip = _usersPageSkip) {
    _usersPageSkip = skip;
    const container = document.getElementById('usersList');
    const search = (document.getElementById('usersSearchInput')?.value ?? '').trim();

    container.innerHTML = `
        <div class="spinner-container">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>`;

    try {
        const query = new URLSearchParams({
            skip: String(_usersPageSkip),
            limit: String(_adminPageLimit),
        });
        if (search) query.set('q', search);

        const response = await fetch(`${API_BASE}/admin/users?${query.toString()}`, {
            headers: _authHeaders(),
        });
        if (!response.ok) {
            throw new Error(await getErrorDetail(response, 'Failed to load users.'));
        }

        const payload = await response.json();
        const users = payload.items || [];

        if (!users.length) {
            container.innerHTML = '<div class="alert alert-light border">No users found.</div>';
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-striped table-hover align-middle">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Email</th>
                            <th>First Sign-In</th>
                            <th>Roles</th>
                            <th class="text-end">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${users.map(user => `
                            <tr>
                                <td>${escapeHtml(
                                    (`${user.first_name || ''} ${user.last_name || ''}`).trim() || '-'
                                )}</td>
                                <td>${escapeHtml(user.email)}</td>
                                <td>${formatDateTime(user.first_sign_in_at)}</td>
                                <td>${(user.roles || []).map(role =>
                                    `<span class="badge bg-light text-dark me-1">${escapeHtml(role.name)}</span>`
                                ).join('') || '<span class="text-muted">None</span>'}</td>
                                <td class="text-end">
                                    <button class="btn btn-sm btn-outline-primary"
                                        data-action="view-user"
                                        data-user-id="${escapeHtml(user.id)}">View</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        // Delegated listener for "View" buttons
        container.querySelectorAll('[data-action="view-user"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const userId = btn.dataset.userId;
                window.history.pushState({}, '', `${ROUTES.USERS}/${userId}`);
                window.dispatchEvent(new PopStateEvent('popstate'));
            });
        });
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
    }
}

// ── User detail ───────────────────────────────────────────────────────────────

/**
 * Loads a single user from the API and renders the detail/role-assignment UI.
 * Called by the router at path "/users/:id".
 *
 * Uses ensureRolesCache() so the roles list is fetched at most once per session.
 *
 * @param {string} userId
 */
export async function loadUserDetail(userId) {
    document.getElementById('userDetailView').style.display = 'block';
    document.getElementById('pageTitle').textContent = 'User Detail - BC Gov';

    const container = document.getElementById('userDetailContent');
    container.innerHTML = `
        <div class="spinner-container">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>`;

    try {
        // Fetch the user and prime the roles cache in parallel
        const [userResponse] = await Promise.all([
            fetch(`${API_BASE}/admin/users/${userId}`, {
                headers: _authHeaders(),
            }),
            ensureRolesCache(),
        ]);

        if (!userResponse.ok) {
            throw new Error(await getErrorDetail(userResponse, 'Failed to load user detail.'));
        }

        const user = await userResponse.json();
        _currentUserDetail = user;

        const allRoles = getAllRolesCache() || [];
        const assignedRoleIds = new Set((user.roles || []).map(role => role.id));

        container.innerHTML = `
            <div class="card mb-3">
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <dl class="row mb-0">
                                <dt class="col-sm-5">First Name</dt>
                                <dd class="col-sm-7">${escapeHtml(user.first_name || '-')}</dd>
                                <dt class="col-sm-5">Last Name</dt>
                                <dd class="col-sm-7">${escapeHtml(user.last_name || '-')}</dd>
                                <dt class="col-sm-5">Email</dt>
                                <dd class="col-sm-7">${escapeHtml(user.email)}</dd>
                                <dt class="col-sm-5">First Sign-In</dt>
                                <dd class="col-sm-7">${formatDateTime(user.first_sign_in_at)}</dd>
                            </dl>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Assigned Roles</h5>
                    <div class="row row-cols-1 row-cols-md-2 g-2">
                        ${allRoles.map(role => `
                            <div class="col">
                                <label class="form-check">
                                    <input class="form-check-input user-role-checkbox"
                                        type="checkbox"
                                        value="${escapeHtml(role.id)}"
                                        ${assignedRoleIds.has(role.id) ? 'checked' : ''}>
                                    <span class="form-check-label">
                                        <strong>${escapeHtml(role.name)}</strong>
                                        ${role.description
                                            ? `<small class="text-muted d-block">${escapeHtml(role.description)}</small>`
                                            : ''}
                                    </span>
                                </label>
                            </div>
                        `).join('')}
                    </div>
                    <div class="mt-3">
                        <button class="btn btn-bc-primary" type="button"
                            data-action="save-user-roles">Save Role Assignments</button>
                    </div>
                </div>
            </div>
        `;

        container.querySelector('[data-action="save-user-roles"]')
            ?.addEventListener('click', () => saveUserRoles());
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
    }
}

// ── Save role assignments ─────────────────────────────────────────────────────

/**
 * Reads all checked role checkboxes and PUTs the updated list to the API.
 * Re-loads the user detail on success.
 */
export async function saveUserRoles() {
    if (!_currentUserDetail?.id) return;

    const selectedRoleIds = Array.from(
        document.querySelectorAll('.user-role-checkbox:checked')
    ).map(el => el.value);

    try {
        const response = await fetch(`${API_BASE}/admin/users/${_currentUserDetail.id}/roles`, {
            method: 'PUT',
            headers: _authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ role_ids: selectedRoleIds }),
        });
        if (!response.ok) {
            throw new Error(await getErrorDetail(response, 'Failed to update user roles.'));
        }
        showAlert('User role assignments updated.', 'success');
        await loadUserDetail(_currentUserDetail.id);
    } catch (error) {
        showAlert(error.message, 'danger');
    }
}
