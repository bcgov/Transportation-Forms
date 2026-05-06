// frontend/js/views/my-reservations.js
// "My Reservations" view — shows the current user's form number reservation requests.

import { API_BASE, ROUTES } from '../constants.js';
import { escapeHtml, formatDateTime, showAlert, showSpinner, getErrorDetail, formatReservationStatus, getFormNumberDisplay } from '../utils.js';
import { getAuthToken } from '../auth.js';
import { openReleaseModal } from './approvals.js';

// Statuses from which a requester may release their own reservation.
const REQUESTER_RELEASABLE_STATUSES = ['reserved', 'pending_approval', 'changes_requested'];

function isRequesterReleaseAllowed(status) {
    return REQUESTER_RELEASABLE_STATUSES.includes(status);
}

// ─── View entry-point ─────────────────────────────────────────────────────────

/**
 * Show the My Reservations view and trigger an initial data load.
 * Expects the DOM element #myReservationsView to exist.
 */
export function showMyReservationsView() {
    const view = document.getElementById('myReservationsView');
    view.style.display = 'block';
    document.getElementById('pageTitle').textContent = 'My Reservations - BC Gov';

    if (!view.dataset.wired) {
        view.dataset.wired = '1';
        view.querySelector('[data-action="refresh-my-reservations"]')
            ?.addEventListener('click', loadMyReservations);
        document.getElementById('myResStatusFilter')
            ?.addEventListener('change', loadMyReservations);
        // Reload list after a release (or any approval action) completes while
        // this view is visible. approvals.js dispatches this event.
        document.addEventListener('approvals:action-complete', () => {
            if (view.style.display !== 'none') loadMyReservations();
        });
    }

    loadMyReservations();
}

// ─── Data loader ──────────────────────────────────────────────────────────────

/**
 * Fetch the current user's reservations from GET /api/v1/reservations/my and
 * render a card list into #myReservationsList.
 *
 * Filtering is performed client-side because the /my endpoint does not expose
 * a status query parameter.
 */
export async function loadMyReservations() {
    const container = document.getElementById('myReservationsList');
    showSpinner('#myReservationsList', true);

    try {
        const response = await fetch(`${API_BASE}/reservations/my?limit=50`, {
            headers: { 'Authorization': `Bearer ${getAuthToken()}` },
        });

        if (!response.ok) {
            const detail = await getErrorDetail(response, 'Failed to load reservations');
            throw new Error(detail);
        }

        const data = await response.json();
        let items = data.items || [];

        const statusFilter = document.getElementById('myResStatusFilter')?.value || '';
        if (statusFilter) {
            items = items.filter(r => r.status === statusFilter);
        }

        if (items.length === 0) {
            container.innerHTML = _renderEmptyState(statusFilter);
            return;
        }

        container.innerHTML = items.map(_renderReservationCard).join('');
        _bindCardEvents(container);
    } catch (error) {
        container.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-circle"></i>
                Error loading reservations: ${escapeHtml(error.message)}
            </div>`;
        console.error('My reservations load error:', error);
    }
}

// ─── Rendering helpers ────────────────────────────────────────────────────────

function _renderEmptyState(statusFilter) {
    return `
        <div class="empty-state">
            <i class="fas fa-inbox"></i>
            <h4>No Reservations Found</h4>
            <p>You haven't submitted any form number reservations${statusFilter ? ' with this status' : ''} yet.</p>
            <a class="btn btn-bc-primary" data-route="${ROUTES.RESERVE}">
                <i class="fas fa-hashtag"></i> Reserve a Form Number
            </a>
        </div>`;
}

function _renderReservationCard(r) {
    const detailPath = `/reservations/${escapeHtml(r.id)}`;
    const resubmitBtn = r.status === 'changes_requested'
        ? `<button class="btn btn-sm btn-warning"
                data-action="resubmit"
                data-reservation-id="${escapeHtml(r.id)}">
               <i class="fas fa-redo"></i> Resubmit
           </button>`
        : '';

    const releaseBtn = isRequesterReleaseAllowed(r.status)
        ? `<button class="btn btn-sm btn-outline-warning"
                data-action="release"
                data-reservation-id="${escapeHtml(r.id)}"
                data-form-number="${escapeHtml(r.full_form_number)}">
               <i class="fas fa-unlock-alt"></i> Release
           </button>`
        : '';

    const createdDate = r.created_at ? new Date(r.created_at).toLocaleDateString() : '-';
    const expiresRow = r.expires_at
        ? `<br><small class="text-muted">Expires: ${new Date(r.expires_at).toLocaleDateString()}</small>`
        : '';

    return `
        <div class="card reservation-card"
             style="cursor: pointer;"
             data-route="${detailPath}"
             data-return-to="my-reservations">
            <div class="card-body">
                <div class="row align-items-center">
                    <div class="col-md-3">
                        <h5 class="mb-1 fw-bold">${escapeHtml(r.full_form_number)}</h5>
                        <small class="text-muted">
                            ${r.numbering_method === 'auto_generated' ? 'Auto-generated' : 'Custom'}
                        </small>
                    </div>
                    <div class="col-md-3">
                        <span class="badge reservation-status-badge status-${escapeHtml(r.status)}">
                            ${formatReservationStatus(r.status)}
                        </span>
                    </div>
                    <div class="col-md-3">
                        <small class="text-muted">Created: ${createdDate}</small>
                        ${expiresRow}
                    </div>
                    <div class="col-md-3 text-end">
                        ${resubmitBtn}
                        ${releaseBtn}
                        <a class="btn btn-sm btn-outline-primary"
                           data-route="${detailPath}"
                           data-return-to="my-reservations">
                            <i class="fas fa-eye"></i> View
                        </a>
                    </div>
                </div>
            </div>
        </div>`;
}

// ─── Event delegation ─────────────────────────────────────────────────────────

let _cardEventsController = null;

/**
 * Attach a single delegated click listener to the list container.
 * Uses an AbortController so repeated loads don't stack listeners.
 */
function _bindCardEvents(container) {
    if (_cardEventsController) _cardEventsController.abort();
    _cardEventsController = new AbortController();

    container.addEventListener('click', async (event) => {
        const actionBtn = event.target.closest('[data-action]');
        if (!actionBtn) return;

        // Prevent the card's data-route from also triggering navigation.
        event.stopPropagation();

        const action = actionBtn.dataset.action;
        const reservationId = actionBtn.dataset.reservationId;
        const formNumber = actionBtn.dataset.formNumber;

        if (action === 'resubmit') {
            await _resubmit(reservationId);
        } else if (action === 'release') {
            openReleaseModal(reservationId, formNumber);
        }
    }, { signal: _cardEventsController.signal });
}

async function _resubmit(reservationId) {
    if (!reservationId) return;
    if (!confirm('Are you sure you want to resubmit this reservation for approval?')) return;

    try {
        const response = await fetch(`${API_BASE}/reservations/${reservationId}/resubmit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${getAuthToken()}`,
            },
        });

        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to resubmit');
            throw new Error(msg);
        }

        showAlert('Reservation resubmitted for approval', 'success');
        loadMyReservations();
    } catch (error) {
        showAlert('Error resubmitting reservation: ' + error.message, 'danger');
    }
}
