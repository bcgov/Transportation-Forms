// frontend/js/shared/reservation-view-popup.js
// FEAT-0027 US-007 — compact "View" popup for Form Number Reservations in the
// Approvals queue. This is a SEPARATE component from the Forms-list View Details
// popup (form-view-popup.js): reservations are not forms, so it renders only the
// four reservation facts required by the intake and never touches form data
// (AC2 / AC10 / BR-01).
//
// Public API:
//   openReservationViewPopup({ reservationId, openerElement? })
//
// The Approve / Request Changes / Reject buttons reuse the EXISTING inline row
// controls' server flow (CC-BR-04 / AC3): the popup hides itself and dispatches
// a `reservation-view-popup:<action>` event that approvals.js handles by opening
// the same confirmation modal the inline buttons open. No new endpoint, payload,
// transition, or audit event is introduced.

import { API_BASE } from '../constants.js';
import {
    escapeHtml,
    formatDateTime,
    showNotification,
} from '../utils.js';
import { hasPermission, getAuthToken } from '../auth.js';
import { getCurrentUser } from '../state.js';

// Information-leak parity with US-006: any failure to load the reservation
// (invalid id, 403, 404, network error) surfaces the SAME generic toast.
const DENIED_MESSAGE =
    "Reservation not found or you don't have permission to view it.";

const SELF_APPROVE_TOOLTIP = 'You cannot approve your own request';

// Future-proofing (US-007 AC5): reservation-side self-approval is NOT enforced
// today — no `reservation:approve-self` permission exists and the server allows
// a requester to approve their own reservation, so the popup matches that
// behaviour. To turn on segregation of duties later, seed the permission below
// and flip SELF_APPROVAL_ENFORCED to true; no other code change is required.
const RESERVATION_SELF_APPROVE_PERMISSION = 'reservation:approve-self';
const SELF_APPROVAL_ENFORCED = false;

const MODAL_ID = 'reservationViewModal';

// ─── Module-private state ─────────────────────────────────────────────────────

let _openerElement = null;
let _focusHandlerAttached = false;
let _reservationRequestController = null;
let _popupGeneration = 0;

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Open the compact reservation View popup.
 *
 * @param {object} options
 * @param {string} options.reservationId        UUID of the reservation to display.
 * @param {HTMLElement} [options.openerElement]  Element to receive focus on close (AC8 / CC-BR-06).
 * @returns {Promise<void>}
 */
export async function openReservationViewPopup(options) {
    const { reservationId, openerElement = null } = options || {};
    if (!reservationId) return;

    _reservationRequestController?.abort();
    const requestController = new AbortController();
    _reservationRequestController = requestController;
    const popupGeneration = ++_popupGeneration;

    _openerElement = openerElement
        || (document.activeElement instanceof HTMLElement ? document.activeElement : null);

    // AC4 — the popup opens only if the user holds `reservation:read`.
    if (!hasPermission('reservation:read')) {
        showNotification(DENIED_MESSAGE, 'warning');
        _openerElement = null;
        return;
    }

    _ensureFocusReturnHandler();

    const reservation = await _fetchReservation(reservationId, requestController.signal);
    if (popupGeneration !== _popupGeneration || requestController.signal.aborted) {
        return;
    }
    _reservationRequestController = null;
    if (!reservation) {
        showNotification(DENIED_MESSAGE, 'warning');
        _openerElement = null;
        return;
    }

    _renderPopup(reservation);
    _showModal();
}

// ─── Data ─────────────────────────────────────────────────────────────────────

async function _fetchReservation(reservationId, signal) {
    try {
        const response = await fetch(
            `${API_BASE}/reservations/${encodeURIComponent(reservationId)}`,
            {
                headers: { Authorization: `Bearer ${getAuthToken()}` },
                signal,
            },
        );
        if (!response.ok) return null;
        return await response.json();
    } catch (_error) {
        return null;
    }
}

// ─── Rendering ────────────────────────────────────────────────────────────────

function _renderPopup(reservation) {
    const bodyEl = document.getElementById('reservationViewModalBody');
    const footerEl = document.getElementById('reservationViewModalFooter');
    if (!bodyEl || !footerEl) return;

    bodyEl.innerHTML = _renderBodyHtml(reservation);
    footerEl.innerHTML = _renderFooterHtml(reservation);

    _wireFooterHandlers(reservation);
}

function _renderBodyHtml(r) {
    // AC2 — exactly four labelled fields; no form data (AC10 / BR-01).
    const formNumber = escapeHtml(r.full_form_number || r.form_number || '—');
    const method = escapeHtml(_formatMethod(r.numbering_method));
    const reservedBy = escapeHtml(r.reserved_by_name || r.reserved_by_email || '—');
    const created = escapeHtml(formatDateTime(r.created_at));

    return `
        <dl class="row mb-0">
            <dt class="col-sm-4">Form Number:</dt>
            <dd class="col-sm-8" data-testid="reservation-form-number">${formNumber}</dd>

            <dt class="col-sm-4">Method:</dt>
            <dd class="col-sm-8" data-testid="reservation-method">${method}</dd>

            <dt class="col-sm-4">Reserved By:</dt>
            <dd class="col-sm-8" data-testid="reservation-reserved-by">${reservedBy}</dd>

            <dt class="col-sm-4">Created:</dt>
            <dd class="col-sm-8" data-testid="reservation-created">${created}</dd>
        </dl>
    `;
}

/**
 * Map the numbering-method code to the same display string used by the inline
 * reservation rows. Unknown / legacy codes render as-is rather than crashing
 * (US-007 edge case).
 */
function _formatMethod(method) {
    if (method === 'auto_generated') return 'Auto-generated';
    if (method === 'custom') return 'Custom';
    return method || '—';
}

function _renderFooterHtml(r) {
    return [
        _renderApproveButtonHtml(r),
        _renderRequestChangesButtonHtml(),
        _renderRejectButtonHtml(),
        `<button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Close</button>`,
    ].join('\n');
}

function _renderApproveButtonHtml(r) {
    const currentUser = getCurrentUser();
    const currentUserId = currentUser?.id || '';
    const reserverId = r.reserved_by_id || '';
    const isSelfRequest = Boolean(
        reserverId && currentUserId && String(reserverId) === String(currentUserId),
    );

    const hasApprove = hasPermission('reservation:approve');
    // AC5 — self-approval SoD is display-only and currently disabled
    // (SELF_APPROVAL_ENFORCED === false), so this matches the inline control.
    const deniedForSelf = SELF_APPROVAL_ENFORCED
        && isSelfRequest
        && !hasPermission(RESERVATION_SELF_APPROVE_PERMISSION);

    const disabled = !hasApprove || deniedForSelf;
    const tooltip = deniedForSelf ? SELF_APPROVE_TOOLTIP : '';

    return `
        <button type="button" class="btn btn-success"
                data-action="reservation-view-approve"
                ${disabled ? 'disabled' : ''}
                ${tooltip
                    ? `title="${escapeHtml(tooltip)}" aria-label="Approve — ${escapeHtml(tooltip)}"`
                    : 'aria-label="Approve"'}>
            <i class="fas fa-check" aria-hidden="true"></i> Approve
        </button>
    `;
}

function _renderRequestChangesButtonHtml() {
    const disabled = !hasPermission('reservation:request_changes');
    return `
        <button type="button" class="btn btn-warning"
                data-action="reservation-view-request-changes"
                ${disabled ? 'disabled' : ''}
                aria-label="Request Changes">
            <i class="fas fa-edit" aria-hidden="true"></i> Request Changes
        </button>
    `;
}

function _renderRejectButtonHtml() {
    const disabled = !hasPermission('reservation:reject');
    return `
        <button type="button" class="btn btn-danger"
                data-action="reservation-view-reject"
                ${disabled ? 'disabled' : ''}
                aria-label="Reject">
            <i class="fas fa-times" aria-hidden="true"></i> Reject
        </button>
    `;
}

// ─── Event handlers ───────────────────────────────────────────────────────────

function _wireFooterHandlers(r) {
    const footer = document.getElementById('reservationViewModalFooter');
    if (!footer) return;

    const approveBtn = footer.querySelector('[data-action="reservation-view-approve"]');
    if (approveBtn && !approveBtn.disabled) {
        approveBtn.addEventListener('click', () => _handleAction('approve', r));
    }

    const changesBtn = footer.querySelector('[data-action="reservation-view-request-changes"]');
    if (changesBtn && !changesBtn.disabled) {
        changesBtn.addEventListener('click', () => _handleAction('request-changes', r));
    }

    const rejectBtn = footer.querySelector('[data-action="reservation-view-reject"]');
    if (rejectBtn && !rejectBtn.disabled) {
        rejectBtn.addEventListener('click', () => _handleAction('reject', r));
    }
}

/**
 * Hand the action back to approvals.js, which owns the existing confirmation
 * modals and their server calls (CC-BR-04). Using events avoids a circular
 * import between this module and approvals.js.
 */
function _handleAction(kind, r) {
    _hideModal();
    document.dispatchEvent(new CustomEvent(`reservation-view-popup:${kind}`, {
        detail: {
            reservationId: String(r.id),
            formNumber: r.full_form_number || r.form_number || '',
        },
    }));
}

function _ensureFocusReturnHandler() {
    if (_focusHandlerAttached) return;
    _focusHandlerAttached = true;
    const modalEl = document.getElementById(MODAL_ID);
    if (!modalEl) return;
    modalEl.addEventListener('hidden.bs.modal', () => {
        // AC8 — return focus to the row's "View" button on close.
        if (_openerElement && typeof _openerElement.focus === 'function') {
            try { _openerElement.focus(); } catch (_e) { /* ignore */ }
        }
        _openerElement = null;
    });
}

// ─── DOM helpers ──────────────────────────────────────────────────────────────

function _showModal() {
    const modalEl = document.getElementById(MODAL_ID);
    if (!modalEl) return;
    // eslint-disable-next-line no-undef
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
}

function _hideModal() {
    const modalEl = document.getElementById(MODAL_ID);
    if (!modalEl) return;
    // eslint-disable-next-line no-undef
    const inst = window.bootstrap.Modal.getInstance(modalEl);
    if (inst) inst.hide();

    if (modalEl.contains(document.activeElement)) document.activeElement.blur();
    modalEl.classList.remove('show');
    modalEl.style.display = 'none';
    modalEl.setAttribute('aria-hidden', 'true');
    modalEl.removeAttribute('aria-modal');
    modalEl.removeAttribute('role');
    if (!document.querySelector('.modal.show')) {
        document.querySelectorAll('.modal-backdrop').forEach(backdrop => backdrop.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');
    }
}

function _resetPopupLifecycle() {
    _popupGeneration += 1;
    _reservationRequestController?.abort();
    _reservationRequestController = null;
    _openerElement = null;
    _hideModal();

    const body = document.getElementById('reservationViewModalBody');
    const footer = document.getElementById('reservationViewModalFooter');
    if (body) body.replaceChildren();
    if (footer) footer.replaceChildren();
}

window.addEventListener('app:route-changing', _resetPopupLifecycle);
window.addEventListener('auth:session-expired', _resetPopupLifecycle);
window.addEventListener('auth:session-started', _resetPopupLifecycle);
window.addEventListener('auth:session-cleared', _resetPopupLifecycle);
window.addEventListener('auth:authorization-refreshed', _resetPopupLifecycle);
