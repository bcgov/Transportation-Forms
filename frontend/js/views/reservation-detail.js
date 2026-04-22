// frontend/js/views/reservation-detail.js
// Reservation detail view — TASK-411 extraction from index.html inline JS.

import { API_BASE, ROUTES } from '../constants.js';
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
import { getCurrentUser } from '../state.js';
import { getAuthToken } from '../auth.js';
import { openApproveModal, openRejectModal, openRequestChangesModal, openReleaseModal } from './approvals.js';

// ─── Module-private state ─────────────────────────────────────────────────────

let _detailReturnRoute = 'approvals';
let _currentDetailReservationId = null;
let _listenerAbortController = null;

// ─── Auth helper ──────────────────────────────────────────────────────────────

function _getAuthToken() {
    return getAuthToken();
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Show the reservation detail view, fetching data for `reservationId` from the API.
 * `returnRoute` controls where "Back" navigates to ('my-reservations' | 'approvals').
 *
 * @param {string} reservationId
 * @param {string} [returnRoute='approvals']
 */
export async function showReservationDetailView(reservationId, returnRoute) {
    _detailReturnRoute = returnRoute || 'approvals';
    _currentDetailReservationId = reservationId;

    document.getElementById('pageTitle').textContent = 'Reservation Detail - BC Gov';

    const detailView = document.getElementById('reservationDetailView');
    if (detailView) detailView.style.display = 'block';
    if (detailView && !detailView.dataset.wired) {
        detailView.dataset.wired = '1';
        detailView.querySelector('[data-action="go-back-detail"]')
            ?.addEventListener('click', goBackFromDetail);
    }

    const container = document.getElementById('reservationDetailContent');
    showSpinner('#reservationDetailContent', true);

    // Bind delegated listeners once the container is present in the DOM.
    _bindDelegatedListeners(container);

    try {
        const response = await fetch(`${API_BASE}/reservations/${reservationId}`, {
            headers: { 'Authorization': `Bearer ${_getAuthToken()}` },
        });
        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Reservation not found');
            throw new Error(msg);
        }
        const detail = await response.json();
        container.innerHTML = renderReservationDetail(detail);
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> Error loading reservation details: ${escapeHtml(error.message)}</div>`;
        console.error('Reservation detail error:', error);
    }
}

/**
 * Build and return the HTML string for a reservation detail.
 * Buttons use `data-action` attributes; no inline `onclick`.
 *
 * @param {object} detail  Reservation object from the API.
 * @returns {string}
 */
export function renderReservationDetail(detail) {
    const isPending = detail.status === 'pending_approval';
    const isChangesRequested = detail.status === 'changes_requested';
    const canRequesterRelease =
        _detailReturnRoute === 'my-reservations' && _isRequesterReleaseAllowed(detail.status);

    // ── Approver decisions table ──────────────────────────────────────────────
    let approverHtml = '';
    if (detail.approvers && detail.approvers.length > 0) {
        approverHtml = `
        <h5 class="mt-4 mb-3"><i class="fas fa-users"></i> Approver Decisions</h5>
        <div class="table-responsive">
            <table class="table table-sm table-bordered">
                <thead class="table-light">
                    <tr>
                        <th>Approver</th>
                        <th>Decision</th>
                        <th>Reason / Comments</th>
                        <th>Date</th>
                    </tr>
                </thead>
                <tbody>
                    ${detail.approvers.map(a => `
                        <tr>
                            <td>${escapeHtml(a.approver_name || a.approver_email || a.approver_id)}</td>
                            <td>${a.decision
                                ? `<span class="badge reservation-status-badge status-${escapeHtml(a.decision)}">${formatReservationStatus(a.decision)}</span>`
                                : '<span class="text-muted">Pending</span>'
                            }</td>
                            <td>${escapeHtml(a.decision_reason || a.decision_comments || '-')}</td>
                            <td>${formatDateTime(a.decided_at)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
        `;
    }

    // ── Action buttons ────────────────────────────────────────────────────────
    let actionButtons = '';
    if (isPending) {
        actionButtons = `
        <div class="mt-4 d-flex gap-2">
            <button class="btn btn-success"
                data-action="approve"
                data-id="${escapeHtml(detail.id)}"
                data-form-number="${escapeHtml(detail.full_form_number)}">
                <i class="fas fa-check-circle"></i> Approve
            </button>
            <button class="btn btn-warning"
                data-action="request-changes"
                data-id="${escapeHtml(detail.id)}">
                <i class="fas fa-edit"></i> Request Changes
            </button>
            <button class="btn btn-danger"
                data-action="reject"
                data-id="${escapeHtml(detail.id)}">
                <i class="fas fa-times-circle"></i> Reject
            </button>
        </div>
        `;
    }
    if (isChangesRequested) {
        actionButtons = `
        <div class="mt-4">
            <button class="btn btn-warning"
                data-action="resubmit"
                data-id="${escapeHtml(detail.id)}">
                <i class="fas fa-redo"></i> Resubmit for Approval
            </button>
        </div>
        `;
    }
    if (canRequesterRelease) {
        actionButtons += `
        <div class="mt-2">
            <button class="btn btn-outline-warning"
                data-action="release"
                data-id="${escapeHtml(detail.id)}"
                data-form-number="${escapeHtml(detail.full_form_number)}">
                <i class="fas fa-unlock-alt"></i> Release Reservation
            </button>
        </div>
        `;
    }

    // ── Detail fields ─────────────────────────────────────────────────────────
    const prefixLabel = detail.prefix
        ? escapeHtml(detail.prefix.prefix) + (detail.prefix.description ? ' \u2014 ' + escapeHtml(detail.prefix.description) : '')
        : escapeHtml(String(detail.prefix_id));

    return `
    <div class="row">
        <div class="col-md-8">
            <dl class="row">
                <dt class="col-sm-5">Form Number:</dt>
                <dd class="col-sm-7"><strong class="fs-5">${escapeHtml(detail.full_form_number)}</strong></dd>

                <dt class="col-sm-5">Prefix:</dt>
                <dd class="col-sm-7">${prefixLabel}</dd>

                <dt class="col-sm-5">Numbering Method:</dt>
                <dd class="col-sm-7">${detail.numbering_method === 'auto_generated' ? 'Auto-generated' : 'Custom'}</dd>

                ${detail.custom_number_reason ? `
                    <dt class="col-sm-5">Custom Reason:</dt>
                    <dd class="col-sm-7">${escapeHtml(detail.custom_number_reason)}</dd>
                ` : ''}

                <dt class="col-sm-5">Requester:</dt>
                <dd class="col-sm-7">${escapeHtml(detail.reserved_by_name || detail.reserved_by_email || detail.reserved_by_id)}</dd>

                <dt class="col-sm-5">Status:</dt>
                <dd class="col-sm-7">
                    <span class="badge reservation-status-badge status-${escapeHtml(detail.status)}">
                        ${formatReservationStatus(detail.status)}
                    </span>
                </dd>

                <dt class="col-sm-5">Created:</dt>
                <dd class="col-sm-7">${formatDateTime(detail.created_at)}</dd>

                <dt class="col-sm-5">Last Updated:</dt>
                <dd class="col-sm-7">${formatDateTime(detail.updated_at)}</dd>

                ${detail.expires_at ? `
                    <dt class="col-sm-5">Expires:</dt>
                    <dd class="col-sm-7">${formatDateTime(detail.expires_at)}</dd>
                ` : ''}

                ${detail.released_at ? `
                    <dt class="col-sm-5">Released:</dt>
                    <dd class="col-sm-7">${formatDateTime(detail.released_at)}</dd>
                ` : ''}
            </dl>
        </div>
    </div>

    ${approverHtml}
    ${actionButtons}
    `;
}

/**
 * Navigate back to wherever the user came from before viewing the detail.
 * Uses the router when available, falls back to `history.back()`.
 */
export async function goBackFromDetail() {
    const route = _detailReturnRoute === 'my-reservations'
        ? ROUTES.MY_RESERVATIONS
        : ROUTES.APPROVALS;

    try {
        const { navigateTo } = await import('../router.js');
        navigateTo(route);
    } catch {
        history.back();
    }
}

/**
 * POST to `/reservations/{id}/resubmit`, then refresh the detail view.
 * If no `reservationId` argument is given, uses the currently loaded ID.
 *
 * @param {string} [reservationId]
 */
export async function resubmitReservation(reservationId) {
    const id = reservationId || _currentDetailReservationId;
    if (!id) return;

    if (!confirm('Are you sure you want to resubmit this reservation for approval?')) return;

    try {
        const response = await fetch(`${API_BASE}/reservations/${id}/resubmit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${_getAuthToken()}`,
            },
        });

        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to resubmit');
            throw new Error(msg);
        }

        showNotification('Reservation resubmitted for approval', 'success');
        showAlert('Reservation resubmitted for approval', 'success');

        // Refresh the detail panel if we're still viewing the same reservation.
        if (_currentDetailReservationId === id) {
            await showReservationDetailView(id, _detailReturnRoute);
        }
    } catch (error) {
        showAlert('Error resubmitting reservation: ' + error.message, 'danger');
    }
}

// ─── Private helpers ──────────────────────────────────────────────────────────

/**
 * Statuses from which a requester is permitted to release their own reservation.
 * Mirrors the `isRequesterReleaseAllowed` check from the original inline JS.
 */
function _isRequesterReleaseAllowed(status) {
    return ['reserved', 'approved'].includes(status);
}

/**
 * Attach a single delegated click listener on `container` to handle all
 * `data-action` buttons rendered inside the detail pane.
 * Re-calling this aborts and replaces the previous listener to avoid duplicates.
 */
function _bindDelegatedListeners(container) {
    if (_listenerAbortController) _listenerAbortController.abort();
    _listenerAbortController = new AbortController();
    const { signal } = _listenerAbortController;

    container.addEventListener('click', async (event) => {
        const btn = event.target.closest('[data-action]');
        if (!btn) return;

        const action = btn.dataset.action;
        const id = btn.dataset.id;
        const formNumber = btn.dataset.formNumber;

        switch (action) {
            case 'approve':
                openApproveModal(id, formNumber);
                break;
            case 'request-changes':
                openRequestChangesModal(id);
                break;
            case 'reject':
                openRejectModal(id);
                break;
            case 'resubmit':
                await resubmitReservation(id);
                break;
            case 'release':
                openReleaseModal(id, formNumber);
                break;
        }
    }, { signal });

    // Refresh the detail panel after any approval action completes.
    // approvals.js dispatches this event when the detail view is visible.
    document.addEventListener('approvals:action-complete', () => {
        if (_currentDetailReservationId) {
            showReservationDetailView(_currentDetailReservationId, _detailReturnRoute);
        }
    }, { signal });
}
