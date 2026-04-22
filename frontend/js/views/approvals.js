// frontend/js/views/approvals.js
// Approvals queue view — reviewers/admins process pending reservation requests.
import { API_BASE } from '../constants.js';
import {
    escapeHtml,
    formatDateTime,
    showAlert,
    showNotification,
    showSpinner,
    getErrorDetail,
    formatReservationStatus,
    getFormNumberDisplay,
} from '../utils.js';
import { getAuthToken } from '../auth.js';

// Module-private state
let _actionReservationId = null;

// ─── Bootstrap Modal helper ───────────────────────────────────────────────────

function _getModal(id) {
    return window.bootstrap.Modal.getOrCreateInstance(document.getElementById(id));
}

function _hideModal(id) {
    const instance = window.bootstrap.Modal.getInstance(document.getElementById(id));
    if (instance) instance.hide();
}

// ─── View initialisation ──────────────────────────────────────────────────────

/**
 * Show the approvals queue view and wire up delegated event listeners.
 * Safe to call multiple times — listeners are attached once via a guard flag.
 */
export async function showApprovalsView() {
    document.getElementById('approvalsView').style.display = 'block';
    document.getElementById('pageTitle').textContent = 'Pending Approvals - BC Gov';

    _attachDelegatedListeners();
    await loadPendingApprovals();
}

// Guard so we only attach the delegated listeners once per page lifetime.
let _listenersAttached = false;
let _modalListenersAttached = false;

/**
 * Wire up the modal confirm buttons. Called from every modal opener so the
 * buttons work whether the user arrived via the approvals list or the detail
 * view (which never calls showApprovalsView).
 */
function _ensureModalListeners() {
    if (_modalListenersAttached) return;
    _modalListenersAttached = true;

    document.getElementById('confirmApproveBtn')
        ?.addEventListener('click', confirmApprove);
    document.getElementById('confirmRejectBtn')
        ?.addEventListener('click', confirmReject);
    document.getElementById('confirmChangesBtn')
        ?.addEventListener('click', confirmRequestChanges);
    document.getElementById('confirmReleaseBtn')
        ?.addEventListener('click', confirmRelease);
}

function _attachDelegatedListeners() {
    if (_listenersAttached) return;
    _listenersAttached = true;

    // Refresh button inside the approvals view header
    const approvalsView = document.getElementById('approvalsView');
    if (approvalsView) {
        approvalsView.addEventListener('click', (e) => {
            const refreshBtn = e.target.closest('[data-action="refresh-approvals"]');
            if (refreshBtn) {
                loadPendingApprovals();
                return;
            }

            const approveBtn = e.target.closest('[data-action="open-approve"]');
            if (approveBtn) {
                e.stopPropagation();
                openApproveModal(approveBtn.dataset.id, approveBtn.dataset.formNumber);
                return;
            }

            const changesBtn = e.target.closest('[data-action="open-request-changes"]');
            if (changesBtn) {
                e.stopPropagation();
                openRequestChangesModal(changesBtn.dataset.id);
                return;
            }

            const rejectBtn = e.target.closest('[data-action="open-reject"]');
            if (rejectBtn) {
                e.stopPropagation();
                openRejectModal(rejectBtn.dataset.id);
                return;
            }

            const releaseBtn = e.target.closest('[data-action="open-release"]');
            if (releaseBtn) {
                e.stopPropagation();
                openReleaseModal(releaseBtn.dataset.id, releaseBtn.dataset.formNumber);
            }
        });
    }

    _ensureModalListeners();
}

// ─── Load list ────────────────────────────────────────────────────────────────

export async function loadPendingApprovals() {
    const container = document.getElementById('pendingApprovalsList');
    showSpinner('#pendingApprovalsList', true);

    try {
        const response = await fetch(`${API_BASE}/reservations/pending?limit=50`, {
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });

        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to load pending approvals');
            throw new Error(msg);
        }

        const data = await response.json();
        const items = data.items || [];

        document.getElementById('pendingCountLabel').textContent =
            `${data.total ?? items.length} pending request(s)`;

        if (items.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-check-circle"></i>
                    <h4>No Pending Requests</h4>
                    <p>There are no reservations waiting for your approval.</p>
                </div>
            `;
            return;
        }

        container.innerHTML = items.map(r => `
            <div class="card reservation-card pending-card"
                 data-action="view-detail"
                 data-id="${escapeHtml(r.id)}"
                 style="cursor: pointer;">
                <div class="card-body">
                    <div class="row align-items-center">
                        <div class="col-md-3">
                            <h5 class="mb-1 fw-bold">${escapeHtml(r.full_form_number)}</h5>
                            <small class="text-muted">${r.numbering_method === 'auto_generated' ? 'Auto-generated' : 'Custom'}</small>
                        </div>
                        <div class="col-md-2">
                            <span class="badge reservation-status-badge status-${escapeHtml(r.status)}">
                                ${formatReservationStatus(r.status)}
                            </span>
                        </div>
                        <div class="col-md-3">
                            <small class="text-muted">Submitted: ${new Date(r.created_at).toLocaleDateString()}</small>
                            ${r.expires_at ? `<br><small class="text-muted">Expires: ${new Date(r.expires_at).toLocaleDateString()}</small>` : ''}
                        </div>
                        <div class="col-md-4 text-end">
                            <div class="btn-group btn-group-sm">
                                <button class="btn btn-success"
                                        data-action="open-approve"
                                        data-id="${escapeHtml(r.id)}"
                                        data-form-number="${escapeHtml(r.full_form_number)}"
                                        title="Approve">
                                    <i class="fas fa-check"></i> Approve
                                </button>
                                <button class="btn btn-warning"
                                        data-action="open-request-changes"
                                        data-id="${escapeHtml(r.id)}"
                                        title="Request Changes">
                                    <i class="fas fa-edit"></i> Changes
                                </button>
                                <button class="btn btn-danger"
                                        data-action="open-reject"
                                        data-id="${escapeHtml(r.id)}"
                                        title="Reject">
                                    <i class="fas fa-times"></i> Reject
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-circle"></i>
                Error loading pending approvals: ${escapeHtml(error.message)}
            </div>`;
        console.error('Pending approvals load error:', error);
    }
}

// ─── Modal openers ────────────────────────────────────────────────────────────

export function openApproveModal(reservationId, formNumber) {
    _ensureModalListeners();
    _actionReservationId = reservationId;
    document.getElementById('approveFormNumber').textContent = formNumber || reservationId;
    _getModal('approveModal').show();
}

export function openRejectModal(reservationId) {
    _ensureModalListeners();
    _actionReservationId = reservationId;
    const reasonField = document.getElementById('rejectReason');
    reasonField.value = '';
    reasonField.classList.remove('is-invalid');
    _getModal('rejectModal').show();
}

export function openRequestChangesModal(reservationId) {
    _ensureModalListeners();
    _actionReservationId = reservationId;
    const commentsField = document.getElementById('changesComments');
    commentsField.value = '';
    commentsField.classList.remove('is-invalid');
    _getModal('requestChangesModal').show();
}

export function openReleaseModal(reservationId, formNumber) {
    _ensureModalListeners();
    _actionReservationId = reservationId;
    document.getElementById('releaseFormNumber').textContent = formNumber || 'this reservation';
    _getModal('releaseModal').show();
}

// ─── Confirm actions ──────────────────────────────────────────────────────────

export async function confirmApprove() {
    if (!_actionReservationId) return;

    const btn = document.getElementById('confirmApproveBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Approving...';

    try {
        const response = await fetch(
            `${API_BASE}/reservations/${_actionReservationId}/approve`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${getAuthToken()}`,
                },
            },
        );

        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to approve');
            throw new Error(msg);
        }

        _hideModal('approveModal');
        showAlert('Reservation approved successfully', 'success');
        _refreshAfterAction();
    } catch (error) {
        showAlert(`Error approving reservation: ${error.message}`, 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-check-circle"></i> Confirm Approval';
    }
}

export async function confirmReject() {
    const reasonField = document.getElementById('rejectReason');
    const reason = reasonField.value.trim();
    if (!reason) {
        reasonField.classList.add('is-invalid');
        return;
    }

    if (!_actionReservationId) return;

    const btn = document.getElementById('confirmRejectBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Rejecting...';

    try {
        const response = await fetch(
            `${API_BASE}/reservations/${_actionReservationId}/reject`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${getAuthToken()}`,
                },
                body: JSON.stringify({ reason }),
            },
        );

        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to reject');
            throw new Error(msg);
        }

        _hideModal('rejectModal');
        showAlert('Reservation rejected', 'warning');
        _refreshAfterAction();
    } catch (error) {
        showAlert(`Error rejecting reservation: ${error.message}`, 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-times-circle"></i> Confirm Rejection';
    }
}

export async function confirmRequestChanges() {
    const commentsField = document.getElementById('changesComments');
    const comments = commentsField.value.trim();
    if (!comments) {
        commentsField.classList.add('is-invalid');
        return;
    }

    if (!_actionReservationId) return;

    const btn = document.getElementById('confirmChangesBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Submitting...';

    try {
        const response = await fetch(
            `${API_BASE}/reservations/${_actionReservationId}/request-changes`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${getAuthToken()}`,
                },
                body: JSON.stringify({ comments }),
            },
        );

        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to request changes');
            throw new Error(msg);
        }

        _hideModal('requestChangesModal');
        showAlert('Changes requested on reservation', 'info');
        _refreshAfterAction();
    } catch (error) {
        showAlert(`Error requesting changes: ${error.message}`, 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-edit"></i> Submit Change Request';
    }
}

export async function confirmRelease() {
    if (!_actionReservationId) return;

    const btn = document.getElementById('confirmReleaseBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Releasing...';

    try {
        const response = await fetch(
            `${API_BASE}/reservations/${_actionReservationId}/release`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${getAuthToken()}`,
                },
            },
        );

        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to release reservation');
            throw new Error(msg);
        }

        _hideModal('releaseModal');
        showAlert('Reservation released successfully', 'success');
        _refreshAfterAction();
    } catch (error) {
        showAlert(`Error releasing reservation: ${error.message}`, 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-unlock-alt"></i> Confirm Release';
    }
}

// ─── Internal helpers ─────────────────────────────────────────────────────────

/**
 * After any approval action, reload whichever panel is currently visible.
 * The detail view and my-reservations view are handled by their own modules;
 * here we only own the approvals list.
 */
function _refreshAfterAction() {
    const detailView = document.getElementById('reservationDetailView');
    const approvalsView = document.getElementById('approvalsView');
    const myReservationsView = document.getElementById('myReservationsView');

    if (detailView?.style.display !== 'none') {
        // Let the detail view module handle its own refresh via a custom event.
        document.dispatchEvent(new CustomEvent('approvals:action-complete'));
    } else if (approvalsView?.style.display !== 'none') {
        loadPendingApprovals();
    } else if (myReservationsView?.style.display !== 'none') {
        document.dispatchEvent(new CustomEvent('approvals:action-complete'));
    }
}
