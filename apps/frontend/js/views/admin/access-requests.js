// frontend/js/views/admin/access-requests.js
//
// Dual-purpose module:
//   1. Admin view  — list / approve / reject all access requests
//                    (GET  /api/v1/admin/access-requests)
//                    (POST /api/v1/admin/access-requests/:id/approve|reject)
//   2. User-facing — show current request status and let the user submit one
//                    (GET  /api/v1/access-requests/me)
//                    (POST /api/v1/access-requests)

import { API_BASE } from '../../constants.js';
import { escapeHtml, formatDateTime, showAlert, showSpinner, getErrorDetail } from '../../utils.js';
import { isAuthenticated, hasPortalRoles, getAuthToken } from '../../auth.js';

// ─── Admin view ───────────────────────────────────────────────────────────────

/**
 * Show the admin access-requests panel and load its data.
 * Corresponds to the inline `showAccessRequestsView()` in index.html.
 */
export function showAccessRequestsView() {
  // Hide all sibling views before showing this one.
  document.querySelectorAll('[id$="View"]').forEach(el => { el.style.display = 'none'; });

  const view = document.getElementById('accessRequestsView');
  if (view) view.style.display = 'block';

  document.getElementById('pageTitle').textContent = 'Access Requests - BC Gov';

  _initAdminDelegation();

  if (view && !view.dataset.wired) {
    view.dataset.wired = '1';
    view.querySelector('[data-action="refresh-access-requests"]')
      ?.addEventListener('click', loadAdminAccessRequests);
    document.getElementById('accessRequestStatusFilter')
      ?.addEventListener('change', loadAdminAccessRequests);
  }

  loadAdminAccessRequests();
}

/**
 * Wire up delegated click handling for Approve / Reject buttons rendered
 * inside the #accessRequestsList container.  Safe to call multiple times —
 * the listener is attached only once.
 */
let _adminListenerAttached = false;
function _initAdminDelegation() {
  const container = document.getElementById('accessRequestsList');
  if (!container || _adminListenerAttached) return;
  _adminListenerAttached = true;

  container.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    const { action, id } = btn.dataset;
    if (action === 'approve') await approveAccessRequest(id);
    else if (action === 'reject') await rejectAccessRequest(id);
  });
}

/**
 * Fetch and render the access-request list (filtered by the status dropdown).
 * Endpoint: GET /api/v1/admin/access-requests?skip=0&limit=100[&status=...]
 */
export async function loadAdminAccessRequests() {
  const container = document.getElementById('accessRequestsList');
  if (!container) return;

  showSpinner('#accessRequestsList', true);

  const status = document.getElementById('accessRequestStatusFilter')?.value ?? '';

  try {
    const query = new URLSearchParams({ skip: '0', limit: '100' });
    if (status) query.set('status', status);

    const response = await fetch(`${API_BASE}/admin/access-requests?${query}`, {
      headers: { Authorization: `Bearer ${getAuthToken()}` },
    });

    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to load access requests.'));
    }

    const payload = await response.json();
    const items = payload.items ?? [];

    if (!items.length) {
      container.innerHTML = '<div class="alert alert-light border">No access requests found.</div>';
      return;
    }

    const rows = items.map(item => {
      const badgeClass = item.status === 'pending'
        ? 'bg-warning text-dark'
        : item.status === 'approved' ? 'bg-success' : 'bg-danger';

      const actions = item.status === 'pending'
        ? `<button class="btn btn-sm btn-success"
                   data-action="approve"
                   data-id="${escapeHtml(item.id)}">Approve</button>
           <button class="btn btn-sm btn-outline-danger ms-1"
                   data-action="reject"
                   data-id="${escapeHtml(item.id)}">Reject</button>`
        : '<span class="text-muted">—</span>';

      return `
        <tr>
          <td>${escapeHtml(item.user_email || item.user_id)}</td>
          <td><span class="badge ${badgeClass}">${escapeHtml(item.status)}</span></td>
          <td>${formatDateTime(item.created_at)}</td>
          <td>${formatDateTime(item.processed_at)}</td>
          <td>${escapeHtml(item.review_notes || '—')}</td>
          <td class="text-end">${actions}</td>
        </tr>`;
    }).join('');

    container.innerHTML = `
      <div class="table-responsive">
        <table class="table table-striped table-hover align-middle">
          <thead>
            <tr>
              <th>User</th>
              <th>Status</th>
              <th>Submitted</th>
              <th>Processed</th>
              <th>Notes</th>
              <th class="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  } catch (error) {
    container.innerHTML = `<div class="alert alert-danger">${escapeHtml(error.message)}</div>`;
  }
}

/**
 * Prompt for optional notes then approve the given request.
 * Endpoint: POST /api/v1/admin/access-requests/:id/approve
 */
export async function approveAccessRequest(requestId) {
  const reviewNotes = window.prompt('Optional review notes:', '') ?? null;
  try {
    const response = await fetch(`${API_BASE}/admin/access-requests/${requestId}/approve`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${getAuthToken()}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ review_notes: reviewNotes }),
    });

    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to approve request.'));
    }

    showAlert('Access request approved.', 'success');
    loadAdminAccessRequests();
  } catch (error) {
    showAlert(error.message, 'danger');
  }
}

/**
 * Prompt for optional notes then reject the given request.
 * Endpoint: POST /api/v1/admin/access-requests/:id/reject
 */
export async function rejectAccessRequest(requestId) {
  const reviewNotes = window.prompt('Optional rejection notes:', '') ?? null;
  try {
    const response = await fetch(`${API_BASE}/admin/access-requests/${requestId}/reject`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${getAuthToken()}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ review_notes: reviewNotes }),
    });

    if (!response.ok) {
      throw new Error(await getErrorDetail(response, 'Failed to reject request.'));
    }

    showAlert('Access request rejected.', 'success');
    loadAdminAccessRequests();
  } catch (error) {
    showAlert(error.message, 'danger');
  }
}

// ─── User-facing request-access flow ─────────────────────────────────────────

/**
 * Load the current user's access-request status and update the
 * #requestAccessPanel banner shown on the public list/home view.
 * Endpoint: GET /api/v1/access-requests/me
 */
export async function loadRequestAccessState() {
  const panel = document.getElementById('requestAccessPanel');
  const statusText = document.getElementById('requestAccessStatusText');
  const requestBtn = document.getElementById('requestAccessBtn');

  if (!panel || !statusText || !requestBtn) return;

  // Hide the panel when the user is not logged in or already has portal roles.
  if (!isAuthenticated() || hasPortalRoles()) {
    panel.style.display = 'none';
    return;
  }

  panel.style.display = 'flex';
  requestBtn.disabled = false;
  statusText.textContent = 'You do not currently have a portal role assignment.';

  try {
    const response = await fetch(`${API_BASE}/access-requests/me`, {
      headers: { Authorization: `Bearer ${getAuthToken()}` },
    });

    if (response.status === 404) {
      // No request on file yet — show the button so the user can submit one.
      requestBtn.style.display = 'inline-block';
      return;
    }

    if (!response.ok) {
      statusText.textContent = 'Unable to load access request status.';
      requestBtn.style.display = 'inline-block';
      return;
    }

    const request = await response.json();
    const hideButton = request.status === 'pending' || request.status === 'approved';
    requestBtn.style.display = hideButton ? 'none' : 'inline-block';

    if (request.status === 'pending') {
      statusText.textContent =
        `Access request is pending review (submitted ${formatDateTime(request.created_at)}).`;
    } else if (request.status === 'approved') {
      statusText.textContent =
        `Access request approved ${formatDateTime(request.processed_at)}.`;
    } else if (request.status === 'rejected') {
      statusText.textContent =
        `Access request rejected ${formatDateTime(request.processed_at)}.`;
    } else {
      statusText.textContent = `Latest request status: ${escapeHtml(request.status)}`;
    }
  } catch (_error) {
    statusText.textContent = 'Unable to load access request status.';
  }
}

/**
 * Submit a new access request on behalf of the current user.
 * Endpoint: POST /api/v1/access-requests
 */
export async function submitAccessRequest() {
  const requestBtn = document.getElementById('requestAccessBtn');
  if (requestBtn) requestBtn.disabled = true;

  try {
    const response = await fetch(`${API_BASE}/access-requests`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${getAuthToken()}` },
    });

    if (!response.ok) {
      const detail = await getErrorDetail(response, 'Failed to submit access request.');
      throw new Error(detail);
    }

    showAlert('Access request submitted.', 'success');
    await loadRequestAccessState();
  } catch (error) {
    showAlert(error.message, 'danger');
  } finally {
    if (requestBtn) requestBtn.disabled = false;
  }
}
