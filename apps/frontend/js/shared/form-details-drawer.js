// Shared responsive form-details drawer for Forms, deep links, and Approvals.

import { API_BASE } from '../constants.js';
import {
    escapeHtml,
    formatDateTime,
    getErrorDetail,
    getFormNumberDisplay,
    showAlert,
    showNotification,
} from '../utils.js';
import { getAuthToken, hasPermission } from '../auth.js';
import { getCurrentUser } from '../state.js';

const DEEPLINK_DENIED_MESSAGE =
    "Form not found or you don't have permission to view it.";
const SELF_APPROVE_TOOLTIP = 'You cannot approve your own request';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STATUS_STYLE_STATES = new Set(['draft', 'pending_review', 'published', 'archived']);
const WORKFLOW_ACTION_SELECTOR = [
    '[data-action="delete-form"]',
    '[data-action="navigate"]',
    '[data-action="submit-form"]',
    '[data-action="archive-form"]',
    '[data-action="restore-form"]',
].join(', ');
const FOCUSABLE_SELECTOR = [
    'a[href]:not([tabindex="-1"])',
    'button:not([disabled]):not([tabindex="-1"])',
    'input:not([disabled]):not([tabindex="-1"])',
    'select:not([disabled]):not([tabindex="-1"])',
    'textarea:not([disabled]):not([tabindex="-1"])',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

let _openerElement = null;
let _currentFormId = null;
let _currentMode = 'default';
let _currentApprovalContext = null;
let _openedFromDeepLink = false;
let _listenersAttached = false;
let _formRequestController = null;
let _drawerGeneration = 0;
let _backgroundInertState = null;
const _pendingApprovalRequests = new Set();

function _elements() {
    return {
        drawer: document.getElementById('formDetailsDrawer'),
        scrim: document.getElementById('formDetailsScrim'),
        body: document.getElementById('formDetailsDrawerBody'),
        number: document.getElementById('formDetailsNumber'),
        title: document.getElementById('formDetailsTitle'),
        sourceActions: document.getElementById('formDetailsSourceActions'),
        workflowActions: document.getElementById('formDetailsWorkflowActions'),
        requestContext: document.getElementById('formDetailsRequestContext'),
        requester: document.getElementById('formDetailsRequester'),
        submitted: document.getElementById('formDetailsSubmitted'),
        status: document.getElementById('formDetailsStatus'),
        businessAreaTerm: document.getElementById('formDetailsBusinessAreaTerm'),
        businessArea: document.getElementById('formDetailsBusinessArea'),
        fileType: document.getElementById('formDetailsFileType'),
        isPublic: document.getElementById('formDetailsPublic'),
        personalInfo: document.getElementById('formDetailsPersonalInfo'),
        updated: document.getElementById('formDetailsUpdated'),
        description: document.getElementById('formDetailsDescription'),
        contactNote: document.getElementById('formDetailsContactNote'),
        contactNoteText: document.getElementById('formDetailsContactNoteText'),
    };
}

/**
 * Open the shared form-details drawer.
 *
 * @param {object} options
 * @param {string} options.formId
 * @param {'default'|'approvals'} [options.mode='default']
 * @param {string} [options.requesterName]
 * @param {string} [options.submittedAt]
 * @param {HTMLElement} [options.openerElement]
 * @param {Function} [options.onNotFound]
 * @returns {Promise<void>}
 */
export async function openFormDetailsDrawer(options) {
    const {
        formId,
        mode = 'default',
        requesterName = null,
        submittedAt = null,
        openerElement = null,
        onNotFound = null,
    } = options || {};

    _formRequestController?.abort();
    const requestController = new AbortController();
    _formRequestController = requestController;
    const drawerGeneration = ++_drawerGeneration;

    _openerElement = openerElement instanceof HTMLElement ? openerElement : null;
    _currentFormId = formId;
    _currentMode = mode === 'approvals' ? 'approvals' : 'default';
    _currentApprovalContext = _currentMode === 'approvals'
        ? { requesterName, submittedAt }
        : null;
    _openedFromDeepLink = !_openerElement
        && window.location.pathname.replace(/\/$/, '') === `/forms/${formId}`;

    _ensureListeners();
    _clearDrawerContent();
    if (!_openedFromDeepLink) {
        _showDrawer();
        _setLoadingState(true);
        document.getElementById('closeFormDetailsDrawer')?.focus();
    }

    const form = await _fetchForm(formId, requestController.signal);
    if (drawerGeneration !== _drawerGeneration || requestController.signal.aborted) return;
    _formRequestController = null;

    if (!form) {
        _closeDrawer({ updateUrl: false });
        if (typeof onNotFound === 'function') onNotFound();
        else showNotification(DEEPLINK_DENIED_MESSAGE, 'warning');
        return;
    }

    await _renderDrawer(form, drawerGeneration);
    if (drawerGeneration !== _drawerGeneration) return;
    if (_openedFromDeepLink) _showDrawer();
    _setLoadingState(false);
    document.getElementById('closeFormDetailsDrawer')?.focus();
}

export function closeFormDetailsDrawer() {
    _closeDrawer();
}

async function _fetchForm(formId, signal) {
    if (typeof formId !== 'string' || !formId) return null;
    try {
        const response = await fetch(`${API_BASE}/forms/${encodeURIComponent(formId)}`, {
            headers: { Authorization: `Bearer ${getAuthToken()}` },
            signal,
        });
        if (!response.ok) return null;
        return await response.json();
    } catch (_error) {
        return null;
    }
}

async function _renderDrawer(form, drawerGeneration) {
    const elements = _elements();
    elements.number.textContent = getFormNumberDisplay(form) || 'Form number unavailable';
    elements.title.textContent = form.title || 'Untitled form';
    elements.status.textContent = _formatStatus(form.status);
    elements.status.dataset.status = _getStatusStyle(form.status);

    const businessAreaName = typeof form.business_area?.name === 'string'
        ? form.business_area.name.trim()
        : '';
    elements.businessAreaTerm.hidden = !businessAreaName;
    elements.businessArea.hidden = !businessAreaName;
    elements.businessArea.textContent = businessAreaName;
    elements.fileType.textContent = typeof form.file_type === 'string' && form.file_type.trim()
        ? form.file_type.trim().toUpperCase()
        : 'Unavailable';
    elements.isPublic.textContent = form.is_public === true ? 'Yes' : 'No';
    elements.personalInfo.textContent = form.collects_personal_info === 'Yes' ? 'Yes' : 'No';
    elements.updated.textContent = formatDateTime(form.updated_at);
    elements.description.textContent = typeof form.description === 'string' && form.description
        ? form.description
        : 'Unavailable';

    _renderRequestContext(elements);
    _renderSourceActions(elements.sourceActions, form);
    await _renderWorkflowActions(elements.workflowActions, form, drawerGeneration);
    _renderContactNote(elements, form.business_area?.mailbox);
}

function _formatStatus(value) {
    if (typeof value !== 'string' || !value.trim()) return 'Unavailable';
    return value.trim().split('_')
        .map(word => word ? word[0].toUpperCase() + word.slice(1) : '')
        .join(' ');
}

function _getStatusStyle(value) {
    if (typeof value !== 'string') return '';
    const status = value.trim().toLowerCase();
    return STATUS_STYLE_STATES.has(status) ? status : '';
}

function _renderRequestContext(elements) {
    const visible = _currentMode === 'approvals' && _currentApprovalContext;
    elements.requestContext.hidden = !visible;
    if (!visible) return;
    elements.requester.textContent = _currentApprovalContext.requesterName || 'Unavailable';
    elements.submitted.textContent = formatDateTime(_currentApprovalContext.submittedAt);
}

function _renderSourceActions(container, form) {
    container.replaceChildren();

    if (form.form_source === 'Download'
        && form.form_attachment_url
        && form.form_attachment_filename) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-bc-primary';
        button.dataset.action = 'download-attachment';
        button.dataset.formId = form.id;
        button.dataset.formFilename = form.form_attachment_filename;
        button.innerHTML = '<i class="fas fa-download" aria-hidden="true"></i> Download';
        container.appendChild(button);
        return;
    }

    if (form.form_source === 'URL' && _isSafeHttpUrl(form.form_source_url)) {
        const link = document.createElement('a');
        link.className = 'btn btn-bc-primary';
        link.href = form.form_source_url.trim();
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.innerHTML = '<i class="fas fa-arrow-up-right-from-square" aria-hidden="true"></i> Form link';
        container.appendChild(link);
    }
}

async function _renderWorkflowActions(container, form, drawerGeneration) {
    container.replaceChildren();
    if (_currentMode === 'approvals') {
        container.innerHTML = `${_renderApproveButtonHtml(form)}${_renderRejectButtonHtml(form)}`;
        container.hidden = false;
        return;
    }

    const { _renderFormActionButtons } = await import('../views/forms-list.js');
    if (drawerGeneration !== _drawerGeneration) return;
    container.innerHTML = _renderFormActionButtons(form);
    container.hidden = !container.childElementCount;
}

function _renderContactNote(elements, mailboxValue) {
    const mailbox = typeof mailboxValue === 'string' ? mailboxValue.trim() : '';
    elements.contactNote.hidden = !mailbox;
    elements.contactNoteText.textContent = mailbox
        ? `Contact ${mailbox} to request a correction or for more information.`
        : '';
}

function _renderApproveButtonHtml(form) {
    const actionState = getFormApprovalActionState(form.created_by?.id);
    const tooltip = actionState.disabledForSelf ? SELF_APPROVE_TOOLTIP : '';

    return `
        <button type="button" class="btn btn-success"
                data-action="form-details-approve"
                data-form-id="${escapeHtml(form.id)}"
                ${actionState.canApprove ? '' : 'disabled'}
                ${tooltip ? `title="${escapeHtml(tooltip)}" aria-label="Approve - ${escapeHtml(tooltip)}"` : 'aria-label="Approve"'}>
            <i class="fas fa-check" aria-hidden="true"></i> Approve
        </button>
    `;
}

function _renderRejectButtonHtml(form) {
    const allowed = getFormApprovalActionState(form.created_by?.id).canDecide;
    return `
        <button type="button" class="btn btn-danger"
                data-action="form-details-reject"
                data-form-id="${escapeHtml(form.id)}"
                ${allowed ? '' : 'disabled'} aria-label="Reject">
            <i class="fas fa-times" aria-hidden="true"></i> Reject
        </button>
    `;
}

export function getFormApprovalActionState(creatorId) {
    const currentUserId = getCurrentUser()?.id;
    const hasValidIdentity = typeof currentUserId === 'string'
        && UUID_PATTERN.test(currentUserId);
    const hasValidCreator = typeof creatorId === 'string'
        && UUID_PATTERN.test(creatorId);
    const canDecide = hasValidIdentity
        && hasValidCreator
        && hasPermission('form:approve')
        && hasPermission('form:review');
    const disabledForSelf = canDecide
        && creatorId === currentUserId
        && !hasPermission('form:approve-self');
    return {
        canApprove: canDecide && !disabledForSelf,
        canDecide,
        disabledForSelf,
    };
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

function _showDrawer() {
    const { drawer, scrim } = _elements();
    if (!drawer || !scrim) return;
    _setBackgroundInert(true);
    drawer.hidden = false;
    drawer.inert = false;
    drawer.setAttribute('aria-hidden', 'false');
    scrim.hidden = false;
    document.body.classList.add('form-details-drawer-open');
    window.requestAnimationFrame(() => drawer.classList.add('is-open'));
}

function _closeDrawer({ updateUrl = true, restoreFocus = true } = {}) {
    const { drawer, scrim } = _elements();
    const shouldClearDeepLink = updateUrl && _openedFromDeepLink;
    const focusTarget = restoreFocus && _openerElement?.isConnected ? _openerElement : null;

    _drawerGeneration += 1;
    _formRequestController?.abort();
    _formRequestController = null;
    if (drawer?.contains(document.activeElement)) document.activeElement.blur();
    drawer?.classList.remove('is-open');
    if (drawer) {
        drawer.hidden = true;
        drawer.inert = true;
        drawer.setAttribute('aria-hidden', 'true');
        drawer.removeAttribute('aria-busy');
    }
    if (scrim) scrim.hidden = true;
    document.body.classList.remove('form-details-drawer-open');
    _setBackgroundInert(false);
    _clearDrawerContent();

    _openerElement = null;
    _currentFormId = null;
    _currentMode = 'default';
    _currentApprovalContext = null;
    _openedFromDeepLink = false;

    if (shouldClearDeepLink) {
        window.history.replaceState({}, '', '/forms');
    }
    focusTarget?.focus();
}

function _clearDrawerContent() {
    const elements = _elements();
    if (!elements.drawer) return;
    elements.number.textContent = '';
    elements.title.textContent = '';
    elements.sourceActions.replaceChildren();
    elements.workflowActions.replaceChildren();
    elements.workflowActions.hidden = true;
    elements.requestContext.hidden = true;
    elements.requester.textContent = '';
    elements.submitted.textContent = '';
    elements.status.textContent = '';
    delete elements.status.dataset.status;
    elements.businessAreaTerm.hidden = true;
    elements.businessArea.hidden = true;
    elements.businessArea.textContent = '';
    elements.fileType.textContent = '';
    elements.isPublic.textContent = '';
    elements.personalInfo.textContent = '';
    elements.updated.textContent = '';
    elements.description.textContent = '';
    elements.contactNote.hidden = true;
    elements.contactNoteText.textContent = '';
    elements.body.querySelector('.form-details-drawer__manual-copy')?.remove();
}

function _setLoadingState(loading) {
    const { drawer, title, number } = _elements();
    if (!drawer) return;
    if (loading) {
        drawer.setAttribute('aria-busy', 'true');
        number.textContent = 'Loading';
        title.textContent = 'Loading form details';
    } else {
        drawer.removeAttribute('aria-busy');
    }
}

function _setBackgroundInert(inert) {
    const elements = [
        document.querySelector('.staff-header'),
        document.getElementById('staffSidebar'),
        document.querySelector('body > .container'),
    ].filter(Boolean);

    if (inert) {
        if (_backgroundInertState) return;
        _backgroundInertState = elements.map(element => [element, element.inert]);
        elements.forEach(element => { element.inert = true; });
        return;
    }

    for (const [element, wasInert] of _backgroundInertState || []) {
        element.inert = wasInert;
    }
    _backgroundInertState = null;
}

function _ensureListeners() {
    if (_listenersAttached) return;
    const { drawer, scrim } = _elements();
    if (!drawer || !scrim) return;
    _listenersAttached = true;

    drawer.addEventListener('click', _handleDrawerClick);
    scrim.addEventListener('click', () => _closeDrawer());
    document.addEventListener('keydown', _handleDrawerKeydown);
}

async function _handleDrawerClick(event) {
    const closeButton = event.target.closest('[data-action="close-form-details"]');
    if (closeButton) {
        _closeDrawer();
        return;
    }

    const shareButton = event.target.closest('[data-action="form-details-share"]');
    if (shareButton && _currentFormId) {
        await _handleShare(_currentFormId);
        return;
    }

    const downloadButton = event.target.closest('[data-action="download-attachment"]');
    if (downloadButton) {
        await downloadFormAttachment(
            downloadButton.dataset.formId,
            downloadButton.dataset.formFilename,
        );
        return;
    }

    const approveButton = event.target.closest('[data-action="form-details-approve"]');
    if (approveButton && !approveButton.disabled) {
        await _handleApprove(approveButton.dataset.formId);
        return;
    }

    const rejectButton = event.target.closest('[data-action="form-details-reject"]');
    if (rejectButton && !rejectButton.disabled) {
        _handleReject(rejectButton.dataset.formId);
        return;
    }

    const workflowButton = event.target.closest(WORKFLOW_ACTION_SELECTOR);
    if (workflowButton && !workflowButton.disabled) {
        const { handleFormWorkflowAction } = await import('../views/forms-list.js');
        const succeeded = await handleFormWorkflowAction(workflowButton);
        if (succeeded && workflowButton.dataset.action !== 'navigate') _closeDrawer();
        else if (succeeded === false) _closeDrawer({ restoreFocus: false });
    }
}

function _handleDrawerKeydown(event) {
    const { drawer } = _elements();
    if (!drawer || drawer.hidden) return;
    if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        _closeDrawer();
        return;
    }
    if (event.key !== 'Tab') return;

    const focusable = [...drawer.querySelectorAll(FOCUSABLE_SELECTOR)]
        .filter(element => !element.hidden && element.getClientRects().length > 0);
    if (!focusable.length) {
        event.preventDefault();
        drawer.focus();
        return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}

function _buildDeepLinkUrl(formId) {
    return `${window.location.origin}/forms/${encodeURIComponent(formId)}`;
}

async function _handleShare(formId) {
    const url = _buildDeepLinkUrl(formId);
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        try {
            await navigator.clipboard.writeText(url);
            showNotification('Link copied to clipboard', 'success');
            return;
        } catch (_error) {
            // Fall through to the accessible manual-copy control.
        }
    }
    _showManualCopyFallback(url);
}

function _showManualCopyFallback(url) {
    showNotification(`Unable to copy link. Please copy manually: ${url}`, 'warning');
    const { body } = _elements();
    body.querySelector('.form-details-drawer__manual-copy')?.remove();
    const wrapper = document.createElement('div');
    wrapper.className = 'form-details-drawer__manual-copy alert alert-warning';
    wrapper.setAttribute('role', 'status');
    const label = document.createElement('label');
    label.className = 'form-label small mb-1';
    label.textContent = 'Copy this link:';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'form-control form-control-sm';
    input.readOnly = true;
    input.value = url;
    input.dataset.testid = 'manual-copy-url';
    wrapper.append(label, input);
    body.appendChild(wrapper);
    input.focus();
    input.select();
}

async function _handleApprove(formId) {
    if (!UUID_PATTERN.test(formId) || _pendingApprovalRequests.has(formId)) return;
    _pendingApprovalRequests.add(formId);
    try {
        const response = await fetch(`${API_BASE}/staff/forms/${encodeURIComponent(formId)}/approve`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            throw new Error(await getErrorDetail(response, 'Failed to approve form'));
        }
        _closeDrawer({ restoreFocus: false });
        showAlert('The form has been approved and published.', 'success');
        document.dispatchEvent(new CustomEvent('form-details-drawer:action-complete'));
    } catch (error) {
        _closeDrawer({ restoreFocus: false });
        showAlert(`Error approving form: ${error.message}`, 'danger');
    } finally {
        _pendingApprovalRequests.delete(formId);
    }
}

function _handleReject(formId) {
    const rejectModal = document.getElementById('approvalsFormRejectModal');
    if (!rejectModal) {
        showAlert('Reject dialog not available.', 'danger');
        return;
    }
    _closeDrawer({ restoreFocus: false });
    const reasonField = document.getElementById('approvalsFormRejectReason');
    if (reasonField) {
        reasonField.value = '';
        reasonField.classList.remove('is-invalid');
    }
    document.dispatchEvent(new CustomEvent('form-details-drawer:reject-request', {
        detail: { formId },
    }));
    window.bootstrap.Modal.getOrCreateInstance(rejectModal).show();
}

function _resetDrawerLifecycle() {
    _closeDrawer({ updateUrl: false, restoreFocus: false });
}

window.addEventListener('app:route-changing', _resetDrawerLifecycle);
window.addEventListener('auth:session-expired', _resetDrawerLifecycle);
window.addEventListener('auth:session-started', _resetDrawerLifecycle);
window.addEventListener('auth:session-cleared', _resetDrawerLifecycle);
window.addEventListener('auth:authorization-refreshed', _resetDrawerLifecycle);

export async function downloadFormAttachment(formId, fallbackFilename) {
    let objectUrl = null;
    try {
        const response = await fetch(`${API_BASE}/forms/${encodeURIComponent(formId)}/file`, {
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            let detail = '';
            try {
                const contentType = response.headers.get('content-type') || '';
                if (contentType.includes('json')) {
                    const responseBody = await response.json();
                    detail = responseBody.detail || responseBody.title || '';
                }
            } catch (_error) {
                // Preserve the status-based fallback below.
            }
            throw new Error(detail || `Download failed (${response.status})`);
        }

        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        const disposition = response.headers.get('content-disposition') || '';
        const match = /filename\*?=(?:UTF-8'')?["']?([^"';]+)/i.exec(disposition);
        const filename = (match && decodeURIComponent(match[1])) || fallbackFilename || 'attachment';
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename;
        link.rel = 'noopener noreferrer';
        document.body.appendChild(link);
        link.click();
        link.remove();
    } catch (error) {
        showAlert(`Error downloading attachment: ${error.message}`, 'danger');
    } finally {
        if (objectUrl) setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    }
}

export const DEEPLINK_DENIED_TOAST = DEEPLINK_DENIED_MESSAGE;
