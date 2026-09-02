// frontend/js/shared/form-view-popup.js
// Shared "View Details" popup used by both the Forms list (US-008) and
// the Approvals queue (US-006, FEAT-0027). One component, two entry points.
//
// Public API:
//   openFormViewPopup({ formId, mode?, requesterName?, submittedAt?,
//                       openerElement?, onNotFound? })
//
// Modes:
//   'default'   — Forms list entry point. Renders form details + Share button.
//   'approvals' — Approvals queue entry point. Adds a labelled Request Context
//                 section (requester / submitted date) and Approve / Reject
//                 action buttons that hit the SAME endpoints as the existing
//                 inline row controls (CC-BR-04).
//
// Deep-link URL shape (US-008 / Q5b / Q6):
//   ${origin}/forms/<form_uuid>
//
// Information-leak (CC-BR-05): any failure to load the form (invalid UUID,
// 400, 403, 404, network error) surfaces the SAME generic toast:
//   "Form not found or you don't have permission to view it."

import { API_BASE } from '../constants.js';
import {
    escapeHtml,
    formatDateTime,
    getFormNumberDisplay,
    showAlert,
    showNotification,
    getErrorDetail,
} from '../utils.js';
import { hasPermission, getAuthToken } from '../auth.js';
import { getCurrentUser } from '../state.js';

const DEEPLINK_DENIED_MESSAGE =
    "Form not found or you don't have permission to view it.";

const SELF_APPROVE_TOOLTIP = 'You cannot approve your own request';

// ─── Module-private state ─────────────────────────────────────────────────────

let _openerElement = null;
let _currentPopupFormId = null;
let _currentPopupMode = 'default';
let _currentApprovalContext = null;  // { requesterName, submittedAt }
let _listenersAttached = false;

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Open the shared View Details popup for a form.
 *
 * @param {object} options
 * @param {string} options.formId         UUID of the form to display.
 * @param {'default'|'approvals'} [options.mode='default']
 * @param {string} [options.requesterName]  Approvals-only: display name of the requester.
 * @param {string} [options.submittedAt]    Approvals-only: ISO timestamp of the request submission.
 * @param {HTMLElement} [options.openerElement]  Element to receive focus when the popup closes (CC-BR-06 / AC8).
 * @param {Function} [options.onNotFound]   Optional override for the "not found / no permission" branch.
 *                                          When omitted, a generic toast is shown per CC-BR-05.
 * @returns {Promise<void>}
 */
export async function openFormViewPopup(options) {
    const {
        formId,
        mode = 'default',
        requesterName = null,
        submittedAt = null,
        openerElement = null,
        onNotFound = null,
    } = options || {};

    _openerElement = openerElement || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    _currentPopupFormId = formId;
    _currentPopupMode = mode;
    _currentApprovalContext = mode === 'approvals'
        ? { requesterName, submittedAt }
        : null;

    _ensureFocusReturnHandler();

    const form = await _fetchForm(formId);
    if (!form) {
        if (typeof onNotFound === 'function') {
            onNotFound();
        } else {
            showNotification(DEEPLINK_DENIED_MESSAGE, 'warning');
        }
        _openerElement = null;
        _currentPopupFormId = null;
        return;
    }

    _renderPopup(form);
    _showModal();
}

// ─── Rendering ────────────────────────────────────────────────────────────────

async function _fetchForm(formId) {
    try {
        const response = await fetch(`${API_BASE}/forms/${encodeURIComponent(formId)}`, {
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            return null;
        }
        return await response.json();
    } catch (_error) {
        return null;
    }
}

function _renderPopup(form) {
    const titleEl = document.getElementById('formModalTitle');
    const bodyEl = document.getElementById('formModalBody');
    const footerEl = _getModalFooter();
    if (!titleEl || !bodyEl || !footerEl) return;

    titleEl.textContent = form.title || 'Form Details';
    bodyEl.innerHTML = _renderBodyHtml(form);
    footerEl.innerHTML = _renderFooterHtml(form);

    _wireModalBodyHandlers(form);
    _wireModalFooterHandlers(form);
}

function _escapeAttribute(value) {
    return escapeHtml(value).replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function _renderBodyHtml(form) {
    const parts = [];

    if (_currentPopupMode === 'approvals' && _currentApprovalContext) {
        parts.push(_renderRequestContextHtml(_currentApprovalContext));
    }

    parts.push(`
        <dl class="row mb-0">
            <dt class="col-sm-3">Title:</dt>
            <dd class="col-sm-9">${escapeHtml(form.title || '')}</dd>

            <dt class="col-sm-3">Form Number:</dt>
            <dd class="col-sm-9">${escapeHtml(getFormNumberDisplay(form))}</dd>

            <dt class="col-sm-3">Description:</dt>
            <dd class="col-sm-9 form-view-popup__description">${escapeHtml(form.description || 'N/A')}</dd>

            <dt class="col-sm-3">Status:</dt>
            <dd class="col-sm-9"><span class="badge bg-info">${escapeHtml(form.status || '')}</span></dd>

            <dt class="col-sm-3">Public:</dt>
            <dd class="col-sm-9">${form.is_public ? 'Yes' : 'No'}</dd>

            <dt class="col-sm-3">Does this form collect personal info?</dt>
            <dd class="col-sm-9">${escapeHtml(form.collects_personal_info || 'No')}</dd>

            <dt class="col-sm-3">Form Source:</dt>
            <dd class="col-sm-9">${escapeHtml(form.form_source || 'N/A')}</dd>

            ${form.form_source === 'URL' && _isSafeHttpUrl(form.form_source_url) ? `
            <dt class="col-sm-3">Source URL:</dt>
            <dd class="col-sm-9">
                <a href="${_escapeAttribute(form.form_source_url.trim())}" target="_blank" rel="noopener noreferrer">
                    ${escapeHtml(form.form_source_url || '')}
                </a>
            </dd>
            ` : ''}

            ${form.form_source === 'Download' ? `
            <dt class="col-sm-3">Attachment:</dt>
            <dd class="col-sm-9">
                <button type="button" class="btn btn-link p-0"
                    data-action="download-attachment"
                    data-form-id="${escapeHtml(form.id)}">
                    <i class="fas fa-download"></i>
                    ${escapeHtml(form.form_attachment_filename || 'Download')}
                </button>
            </dd>
            ` : ''}

            ${form.file_type ? `
            <dt class="col-sm-3">File Type:</dt>
            <dd class="col-sm-9">${escapeHtml(form.file_type)}</dd>
            ` : ''}

            <dt class="col-sm-3">Business Area:</dt>
            <dd class="col-sm-9">
                ${form.business_area
                    ? `<span class="badge bg-primary me-1">${escapeHtml(form.business_area.name)}</span>`
                    : 'None'}
            </dd>

            <dt class="col-sm-3">Keywords:</dt>
            <dd class="col-sm-9">
                ${Array.isArray(form.keywords) && form.keywords.length
                    ? form.keywords.map(k => escapeHtml(k)).join(', ')
                    : 'None'}
            </dd>

            <dt class="col-sm-3">Effective Date:</dt>
            <dd class="col-sm-9">${form.effective_date ? escapeHtml(form.effective_date) : 'N/A'}</dd>

            <dt class="col-sm-3">Created:</dt>
            <dd class="col-sm-9">${formatDateTime(form.created_at)}</dd>

            <dt class="col-sm-3">Updated:</dt>
            <dd class="col-sm-9">${formatDateTime(form.updated_at)}</dd>
        </dl>
    `);

    return parts.join('');
}

function _isSafeHttpUrl(value) {
    if (typeof value !== 'string' || !value.trim()) return false;
    try {
        const url = new URL(value.trim());
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch (_error) {
        return false;
    }
}

function _renderRequestContextHtml(ctx) {
    const requester = ctx.requesterName ? escapeHtml(ctx.requesterName) : '—';
    const submitted = ctx.submittedAt ? escapeHtml(formatDateTime(ctx.submittedAt)) : '—';
    return `
        <section class="form-view-popup__request-context alert alert-secondary mb-3"
                 aria-labelledby="formViewPopupRequestContextLabel">
            <h6 id="formViewPopupRequestContextLabel" class="mb-2">
                <i class="fas fa-user-clock"></i> Approval Request
            </h6>
            <dl class="row mb-0">
                <dt class="col-sm-3">Requester:</dt>
                <dd class="col-sm-9" data-testid="request-context-requester">${requester}</dd>
                <dt class="col-sm-3">Submitted:</dt>
                <dd class="col-sm-9" data-testid="request-context-submitted-at">${submitted}</dd>
            </dl>
        </section>
    `;
}

function _renderFooterHtml(form) {
    const buttons = [];

    if (_currentPopupMode === 'approvals') {
        buttons.push(_renderApproveButtonHtml(form));
        buttons.push(_renderRejectButtonHtml(form));
    }

    // Share button — visible from every entry point (US-008 AC2, Q8c).
    buttons.push(`
        <button type="button" class="btn btn-outline-primary"
                data-action="form-view-share"
                aria-label="Share">
            <i class="fas fa-share-alt" aria-hidden="true"></i> Share
        </button>
    `);

    buttons.push(`
        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Close</button>
    `);

    return buttons.join('\n');
}

function _renderApproveButtonHtml(form) {
    const currentUser = getCurrentUser();
    const currentUserId = currentUser?.id || '';
    const creatorId = form.created_by?.id || '';
    const isSelfRequest = creatorId && currentUserId && creatorId === currentUserId;

    const hasApprove = hasPermission('form:approve') && hasPermission('form:review');
    const hasApproveSelf = hasPermission('form:approve-self');
    const disabledForSelf = isSelfRequest && !hasApproveSelf;

    const disabled = !hasApprove || disabledForSelf;
    const tooltip = disabledForSelf ? SELF_APPROVE_TOOLTIP : '';

    return `
        <button type="button" class="btn btn-success"
                data-action="form-view-approve"
                data-form-id="${escapeHtml(form.id)}"
                ${disabled ? 'disabled' : ''}
                ${tooltip ? `title="${escapeHtml(tooltip)}" aria-label="Approve — ${escapeHtml(tooltip)}"` : 'aria-label="Approve"'}>
            <i class="fas fa-check" aria-hidden="true"></i> Approve
        </button>
    `;
}

function _renderRejectButtonHtml(form) {
    const hasReject = hasPermission('form:approve') && hasPermission('form:review');
    return `
        <button type="button" class="btn btn-danger"
                data-action="form-view-reject"
                data-form-id="${escapeHtml(form.id)}"
                ${hasReject ? '' : 'disabled'}
                aria-label="Reject">
            <i class="fas fa-times" aria-hidden="true"></i> Reject
        </button>
    `;
}

// ─── DOM helpers ──────────────────────────────────────────────────────────────

function _getModalFooter() {
    const modal = document.getElementById('formModal');
    if (!modal) return null;
    return modal.querySelector('.modal-footer');
}

function _showModal() {
    const modalEl = document.getElementById('formModal');
    if (!modalEl) return;
    // eslint-disable-next-line no-undef
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
}

function _hideModal() {
    const modalEl = document.getElementById('formModal');
    if (!modalEl) return;
    // eslint-disable-next-line no-undef
    const inst = window.bootstrap.Modal.getInstance(modalEl);
    if (inst) inst.hide();
}

// ─── Event handlers ───────────────────────────────────────────────────────────

function _wireModalBodyHandlers(form) {
    const body = document.getElementById('formModalBody');
    if (!body) return;
    const downloadBtn = body.querySelector('[data-action="download-attachment"]');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', () => {
            downloadFormAttachment(
                downloadBtn.dataset.formId,
                form.form_attachment_filename,
            );
        });
    }
}

function _wireModalFooterHandlers(form) {
    const footer = _getModalFooter();
    if (!footer) return;

    const shareBtn = footer.querySelector('[data-action="form-view-share"]');
    if (shareBtn) {
        shareBtn.addEventListener('click', () => _handleShare(form.id));
    }

    const approveBtn = footer.querySelector('[data-action="form-view-approve"]');
    if (approveBtn && !approveBtn.disabled) {
        approveBtn.addEventListener('click', () => _handleApprove(form.id));
    }

    const rejectBtn = footer.querySelector('[data-action="form-view-reject"]');
    if (rejectBtn && !rejectBtn.disabled) {
        rejectBtn.addEventListener('click', () => _handleReject(form.id));
    }
}

function _ensureFocusReturnHandler() {
    if (_listenersAttached) return;
    _listenersAttached = true;
    const modalEl = document.getElementById('formModal');
    if (!modalEl) return;
    modalEl.addEventListener('hidden.bs.modal', () => {
        // AC8 — return focus to the opener (or the row's View button).
        if (_openerElement && typeof _openerElement.focus === 'function') {
            try { _openerElement.focus(); } catch (_e) { /* ignore */ }
        }
        _openerElement = null;
        _currentPopupFormId = null;
        _currentPopupMode = 'default';
        _currentApprovalContext = null;
    });
}

// ─── Share (US-008) ───────────────────────────────────────────────────────────

function _buildDeepLinkUrl(formId) {
    // BR-01 — shape is `<origin>/forms/<form_uuid>`; NO query string (AC11).
    return `${window.location.origin}/forms/${encodeURIComponent(formId)}`;
}

async function _handleShare(formId) {
    const url = _buildDeepLinkUrl(formId);
    const clipboard = navigator.clipboard;
    if (clipboard && typeof clipboard.writeText === 'function') {
        try {
            await clipboard.writeText(url);
            showNotification('Link copied to clipboard', 'success');
            return;
        } catch (_error) {
            // Fall through to manual-copy fallback (AC5).
        }
    }
    _showManualCopyFallback(url);
}

function _showManualCopyFallback(url) {
    // AC5 — display the URL for manual copy without leaking a console exception.
    showNotification(`Unable to copy link. Please copy manually: ${url}`, 'warning');
    const body = document.getElementById('formModalBody');
    if (!body) return;
    const existing = body.querySelector('.form-view-popup__manual-copy');
    if (existing) existing.remove();
    const wrap = document.createElement('div');
    wrap.className = 'form-view-popup__manual-copy alert alert-warning mt-3';
    wrap.setAttribute('role', 'status');
    wrap.innerHTML = `
        <label class="form-label small mb-1">Copy this link:</label>
        <input type="text" class="form-control form-control-sm" readonly
               value="${escapeHtml(url)}"
               data-testid="manual-copy-url">
    `;
    body.appendChild(wrap);
    const input = wrap.querySelector('input');
    if (input) {
        input.focus();
        try { input.select(); } catch (_e) { /* ignore */ }
    }
}

// ─── Approve / Reject (US-006) ────────────────────────────────────────────────

async function _handleApprove(formId) {
    try {
        const response = await fetch(`${API_BASE}/staff/forms/${encodeURIComponent(formId)}/approve`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const msg = await getErrorDetail(response, 'Failed to approve form');
            throw new Error(msg);
        }
        _hideModal();
        showAlert('The form has been approved and published.', 'success');
        _emitActionComplete();
    } catch (error) {
        showAlert(`Error approving form: ${error.message}`, 'danger');
    }
}

function _handleReject(formId) {
    // Reuse the existing Approvals-page reject modal (approvalsFormRejectModal).
    // We hide the View popup first so the user sees the reject dialog cleanly.
    const rejectModalEl = document.getElementById('approvalsFormRejectModal');
    if (!rejectModalEl) {
        showAlert('Reject dialog not available.', 'danger');
        return;
    }

    _hideModal();

    const reasonField = document.getElementById('approvalsFormRejectReason');
    if (reasonField) {
        reasonField.value = '';
        reasonField.classList.remove('is-invalid');
    }

    // Store the target form id on the reject dialog so its confirm handler
    // (owned by approvals.js) can pick it up. The approvals view exposes a
    // shared setter via a custom event so we don't reach into its private
    // module state directly.
    document.dispatchEvent(new CustomEvent('form-view-popup:reject-request', {
        detail: { formId },
    }));

    // eslint-disable-next-line no-undef
    window.bootstrap.Modal.getOrCreateInstance(rejectModalEl).show();
}

function _emitActionComplete() {
    document.dispatchEvent(new CustomEvent('form-view-popup:action-complete'));
}

// ─── Attachment download (single source of truth for every entry point) ───────

/**
 * Download a form's current attachment via the internal `/forms/{id}/file`
 * endpoint. This is the single internal Download control reused by both the
 * View Details popup and the Forms-list per-card Download button (US-009 /
 * AC2 / BR-01) so the endpoint, headers, and file-selection logic never
 * diverge between entry points.
 *
 * @param {string} formId            UUID of the form whose file to download.
 * @param {string} [fallbackFilename] Filename to use if the response omits a
 *                                    Content-Disposition header.
 * @returns {Promise<void>}
 */
export async function downloadFormAttachment(formId, fallbackFilename) {
    let objectUrl = null;
    try {
        const response = await fetch(`${API_BASE}/forms/${encodeURIComponent(formId)}/file`, {
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            let detail = '';
            try {
                const ct = response.headers.get('content-type') || '';
                if (ct.includes('json')) {
                    const body = await response.json();
                    detail = body.detail || body.title || '';
                }
            } catch { /* ignore */ }
            throw new Error(detail || `Download failed (${response.status})`);
        }

        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);

        const disposition = response.headers.get('content-disposition') || '';
        const match = /filename\*?=(?:UTF-8'')?["']?([^"';]+)/i.exec(disposition);
        const filename = (match && decodeURIComponent(match[1])) || fallbackFilename || 'attachment';

        const a = document.createElement('a');
        a.href = objectUrl;
        a.download = filename;
        a.rel = 'noopener noreferrer';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    } catch (error) {
        showAlert('Error downloading attachment: ' + error.message, 'danger');
    } finally {
        if (objectUrl) {
            setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
        }
    }
}

// ─── Exported constants (for tests / callers) ─────────────────────────────────

export const DEEPLINK_DENIED_TOAST = DEEPLINK_DENIED_MESSAGE;
