// frontend/js/views/approvals.js
// Approvals queue view — reviewers/admins process pending reservation requests
// and pending form approval requests (FEAT-0001).
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
let _actionFormId = null;  // FEAT-0001: tracks which form is being acted on

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

    // FEAT-0001: form approval/rejection from unified approvals page
    document.getElementById('confirmFormApprovalsRejectBtn')
        ?.addEventListener('click', _confirmFormApprovalsReject);
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
                return;
            }

            // FEAT-0001: form approval actions
            const formApproveBtn = e.target.closest('[data-action="form-approve"]');
            if (formApproveBtn) {
                e.stopPropagation();
                _approveForm(formApproveBtn.dataset.formId);
                return;
            }

            const formRejectBtn = e.target.closest('[data-action="form-reject"]');
            if (formRejectBtn) {
                e.stopPropagation();
                _openFormRejectModal(formRejectBtn.dataset.formId);
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
        // Fetch reservations and form approvals in parallel (FEAT-0001)
        const [reservationResponse, formsResponse] = await Promise.all([
            fetch(`${API_BASE}/reservations/pending?limit=50`, {
                headers: { Authorization: `Bearer ${getAuthToken()}` },
            }),
            fetch(`${API_BASE}/staff/forms/pending-approvals`, {
                headers: { Authorization: `Bearer ${getAuthToken()}` },
            }),
        ]);

        if (!reservationResponse.ok) {
            const msg = await getErrorDetail(reservationResponse, 'Failed to load pending reservations');
            throw new Error(msg);
        }

        const reservationData = await reservationResponse.json();
        const reservationItems = reservationData.items || [];

        // Form approvals are optional — reviewer role required; gracefully skip on 403
        let formItems = [];
        if (formsResponse.ok) {
            const formsData = await formsResponse.json();
            formItems = formsData.items || [];
        }

        const totalCount = (reservationData.total ?? reservationItems.length) + formItems.length;
        document.getElementById('pendingCountLabel').textContent =
            `${totalCount} pending request(s)`;

        if (reservationItems.length === 0 && formItems.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-check-circle"></i>
                    <h4>No Pending Requests</h4>
                    <p>No pending requests at this time.</p>
                </div>
            `;
            return;
        }

        let html = '';

        // ── Reservation requests section ──────────────────────────────────
        if (reservationItems.length > 0) {
            html += `<h5 class="text-muted mt-2 mb-2"><i class="fas fa-hashtag"></i> Form Number Reservations</h5>`;
            html += reservationItems.map(r => `
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
        }

        // ── Form approval requests section (FEAT-0001) ────────────────────
        if (formItems.length > 0) {
            html += `<h5 class="text-muted mt-3 mb-2"><i class="fas fa-file-alt"></i> Form Approval Requests</h5>`;
            html += formItems.map(f => `
                <div class="card reservation-card pending-card">
                    <div class="card-body">
                        <div class="row align-items-center">
                            <div class="col-md-2">
                                <h5 class="mb-1 fw-bold">${escapeHtml(f.form_number || '—')}</h5>
                                <small class="text-muted">Form #</small>
                            </div>
                            <div class="col-md-3">
                                <strong>${escapeHtml(f.title)}</strong>
                            </div>
                            <div class="col-md-2">
                                <span class="badge bg-warning text-dark">Pending Review</span>
                            </div>
                            <div class="col-md-2">
                                <small class="text-muted">
                                    ${f.submitted_at ? new Date(f.submitted_at).toLocaleDateString() : '—'}
                                </small><br>
                                <small class="text-muted">${escapeHtml(f.submitted_by || '—')}</small>
                            </div>
                            <div class="col-md-3 text-end">
                                <div class="btn-group btn-group-sm">
                                    <button class="btn btn-success"
                                            data-action="form-approve"
                                            data-form-id="${escapeHtml(f.form_id)}"
                                            title="Approve &amp; Publish">
                                        <i class="fas fa-check"></i> Approve
                                    </button>
                                    <button class="btn btn-danger"
                                            data-action="form-reject"
                                            data-form-id="${escapeHtml(f.form_id)}"
                                            title="Reject">
                                        <i class="fas fa-times"></i> Reject
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `).join('');
        }

        container.innerHTML = html;
    } catch (error) {
        container.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-circle"></i>
                Error loading pending approvals: ${escapeHtml(error.message)}
            </div>`;
        console.error('Pending approvals load error:', error);
    }
}

// ─── FEAT-0001: Form approval/rejection actions ───────────────────────────────

async function _approveForm(formId) {
    if (!formId) return;
    try {
        const response = await fetch(`${API_BASE}/staff/forms/${formId}/approve`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to approve form');
            throw new Error(msg);
        }
        showAlert('The form has been approved and published.', 'success');
        _refreshAfterAction();
    } catch (error) {
        showAlert(`Error approving form: ${error.message}`, 'danger');
    }
}

function _openFormRejectModal(formId) {
    _ensureModalListeners();
    _actionFormId = formId;
    const reasonField = document.getElementById('approvalsFormRejectReason');
    if (reasonField) {
        reasonField.value = '';
        reasonField.classList.remove('is-invalid');
    }
    _getModal('approvalsFormRejectModal').show();
}

async function _confirmFormApprovalsReject() {
    const reasonField = document.getElementById('approvalsFormRejectReason');
    const reason = reasonField?.value?.trim() || '';
    if (!reason) {
        reasonField?.classList.add('is-invalid');
        return;
    }
    if (!_actionFormId) return;

    const btn = document.getElementById('confirmFormApprovalsRejectBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Rejecting...';

    try {
        const response = await fetch(`${API_BASE}/staff/forms/${_actionFormId}/reject`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${getAuthToken()}`,
            },
            body: JSON.stringify({ reason_notes: reason }),
        });
        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to reject form');
            throw new Error(msg);
        }
        _hideModal('approvalsFormRejectModal');
        showAlert('Form rejected and returned to draft.', 'warning');
        _refreshAfterAction();
    } catch (error) {
        showAlert(`Error rejecting form: ${error.message}`, 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-times-circle"></i> Confirm Rejection';
    }
}

// ─── Modal openers (reservations) ────────────────────────────────────────────

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

// ─── Confirm actions (reservations) ──────────────────────────────────────────

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
 */
function _refreshAfterAction() {
    const detailView = document.getElementById('reservationDetailView');
    const approvalsView = document.getElementById('approvalsView');
    const myReservationsView = document.getElementById('myReservationsView');

    if (detailView?.style.display !== 'none') {
        document.dispatchEvent(new CustomEvent('approvals:action-complete'));
    } else if (approvalsView?.style.display !== 'none') {
        loadPendingApprovals();
    } else if (myReservationsView?.style.display !== 'none') {
        document.dispatchEvent(new CustomEvent('approvals:action-complete'));
    }
}