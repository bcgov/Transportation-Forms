// frontend/js/views/forms-create.js
// Create / Edit form view — extracted from the inline script block in index.html.
//
// Public API:
//   showCreateView()              — mount the blank create form
//   showEditView(formId)          — mount the form pre-populated with existing data
//   handleFormSubmit(event)       — POST (create) or PUT (edit) the form
//   resetFormState()              — reset all fields / state to blank-create defaults
//   loadFormNumberReservations()  — populate the approved-form-number dropdown

import { API_BASE, ROUTES } from '../constants.js';
import { escapeHtml, showAlert, getFormNumberDisplay } from '../utils.js';
import { clearAllFieldErrors, clearFieldError, showFieldError, showValidationErrors } from '../validation.js';
import { initKeywords, getKeywords, setKeywords, addKeyword, setKeywordsLocked } from './keywords.js';
import {
    initFileUpload,
    getUploadedFileUrl,
    getUploadedFileFilename,
    getUploadedFileType,
    clearUploadState,
    restoreUploadState,
} from './file-upload.js';
import { loadBusinessAreas, initBusinessAreaCombobox, getBusinessAreaOptions, resetBusinessAreas, closeBusinessAreaDropdown } from './business-areas.js';
import { getAuthToken, hasPermission, isAdminUser } from '../auth.js';
import { getCurrentUser } from '../state.js';

// ─── Module-private state ─────────────────────────────────────────────────────

let _currentFormId = null;
let _currentFormStatus = null;
let _currentFormCreatedById = null;  // FEAT-0013: track form creator for ownership checks
let _formNumberReservationId = null;
let _formNumberReservations = [];
let _workflowListenersAttached = false;
let _businessAreasState = 'loading';
let _businessAreaLoadVersion = 0;
let _savedBusinessAreaId = null;
let _loadedKeywords = [];

// ─── Private helpers ──────────────────────────────────────────────────────────

/** Show/hide the URL or Download sub-sections based on the current formSource value. */
function _onFormSourceChange() {
    const src = document.getElementById('formSource').value;
    document.getElementById('sourceUrlSection').style.display = (src === 'URL') ? 'block' : 'none';
    document.getElementById('sourceDownloadSection').style.display = (src === 'Download') ? 'block' : 'none';
}

/**
 * SPA navigation helper.
 * Calls the global `navigateTo` if it is still present (transitional refactor),
 * otherwise falls back to pushState + popstate so the router still picks it up.
 * @param {string} path
 */
function _navigate(path) {
    if (typeof window.navigateTo === 'function') {
        window.navigateTo(null, path);
    } else {
        window.history.pushState({}, '', path);
        window.dispatchEvent(new PopStateEvent('popstate'));
    }
}

function _hasActiveBusinessArea() {
    const id = document.getElementById('businessAreaValue').value;
    return _businessAreasState === 'ready' && getBusinessAreaOptions().some(area => area.id === id);
}

function _updateBusinessAreaActions() {
    const available = _businessAreasState === 'ready' && getBusinessAreaOptions().length > 0;
    const selected = _hasActiveBusinessArea();
    document.getElementById('submitBtn').disabled = !available || (_currentFormId !== null && !selected);
    document.getElementById('submitForReviewBtn').disabled = !selected ||
        document.getElementById('businessAreaValue').value !== _savedBusinessAreaId;
}

function _showBusinessAreaError(message, focus = true) {
    showFieldError('businessAreaInput', message);
    if (focus) document.getElementById('businessAreaInput').focus();
}

function _handleInvalidBusinessArea(message) {
    _businessAreasState = 'error';
    document.getElementById('businessAreaMessage').textContent =
        'The selected Business Area is no longer active. Retry loading and choose an active Business Area.';
    document.getElementById('retryBusinessAreasBtn').style.display = '';
    _showBusinessAreaError(message);
    _updateBusinessAreaActions();
}

function _onBusinessAreaChange() {
    if (_hasActiveBusinessArea()) {
        clearFieldError('businessAreaInput');
        document.getElementById('businessAreaMessage').textContent = '';
    } else if (_currentFormId) {
        _showBusinessAreaError('Select an active Business Area before saving or submitting.', false);
    }
    _updateBusinessAreaActions();
}

async function _loadFormBusinessAreas(existingArea = null) {
    const loadVersion = ++_businessAreaLoadVersion;
    _businessAreasState = 'loading';
    _updateBusinessAreaActions();
    const message = document.getElementById('businessAreaMessage');
    const retry = document.getElementById('retryBusinessAreasBtn');
    retry.style.display = 'none';
    message.textContent = 'Loading Business Areas...';

    const loaded = await loadBusinessAreas();
    if (loadVersion !== _businessAreaLoadVersion) return;
    _businessAreasState = loaded ? 'ready' : 'error';
    const options = getBusinessAreaOptions();
    const selected = existingArea && options.find(area => area.id === existingArea.id);
    if (selected) {
        document.getElementById('businessAreaInput').value = selected.label;
        document.getElementById('businessAreaValue').value = selected.id;
    }
    if (!loaded) {
        message.textContent = 'Unable to load Business Areas. Retry loading to save or submit.';
        retry.style.display = '';
    } else if (!options.length) {
        message.textContent = 'No active Business Areas are available. An administrator must create or activate a Business Area before you can save or submit.';
        if (_currentFormId) {
            _showBusinessAreaError('This form has no active Business Area. Select one after an administrator creates or activates it.', false);
        }
    } else if (_currentFormId && !_hasActiveBusinessArea()) {
        document.getElementById('businessAreaInput').value = existingArea?.name || '';
        message.textContent = existingArea?.name
            ? `The Business Area "${existingArea.name}" is no longer active. Select an active Business Area to continue.`
            : 'This form has no Business Area. Select an active Business Area to continue.';
        _showBusinessAreaError('Select an active Business Area before saving or submitting.', false);
    } else {
        message.textContent = '';
    }
    _updateBusinessAreaActions();
}

/** Wire up all event listeners for the create/edit form. Safe to call multiple times. */
function _initFormListeners() {
    const form = document.getElementById('formCreate');
    if (!form) return;

    // Prevent duplicate listeners by removing before re-adding
    form.removeEventListener('submit', handleFormSubmit);
    form.addEventListener('submit', handleFormSubmit);
    form.removeEventListener('business-area:change', _onBusinessAreaChange);
    form.addEventListener('business-area:change', _onBusinessAreaChange);
    const retryAreas = document.getElementById('retryBusinessAreasBtn');
    retryAreas.removeEventListener('click', _retryBusinessAreas);
    retryAreas.addEventListener('click', _retryBusinessAreas);

    const formSourceEl = document.getElementById('formSource');
    if (formSourceEl) {
        formSourceEl.removeEventListener('change', _onFormSourceChange);
        formSourceEl.addEventListener('change', _onFormSourceChange);
    }

    const addKeywordBtn = document.getElementById('addKeywordBtn');
    if (addKeywordBtn) {
        // Replace node to drop any stale listeners set before this module took over
        const clone = addKeywordBtn.cloneNode(true);
        addKeywordBtn.parentNode.replaceChild(clone, addKeywordBtn);
        clone.addEventListener('click', addKeyword);
    }

    const backBtn = document.querySelector('#createView .btn[data-action="back-to-list"], #createView .btn[onclick="resetForm()"]');
    if (backBtn) {
        const clone = backBtn.cloneNode(true);
        backBtn.parentNode.replaceChild(clone, backBtn);
        clone.removeAttribute('onclick');
        clone.addEventListener('click', () => _navigate(ROUTES.FORMS_LIST));
    }

    _initWorkflowButtonListeners();
}

function _retryBusinessAreas() {
    _loadFormBusinessAreas(_savedBusinessAreaId ? { id: _savedBusinessAreaId } : null);
}

/** Wire workflow action button listeners once per page lifetime. */
function _initWorkflowButtonListeners() {
    if (_workflowListenersAttached) return;
    _workflowListenersAttached = true;

    document.getElementById('submitForReviewBtn')
        ?.addEventListener('click', _submitFormForReview);
    document.getElementById('approvePublishBtn')
        ?.addEventListener('click', _approveAndPublish);
    document.getElementById('archiveFormBtn')
        ?.addEventListener('click', _archiveForm);
    document.getElementById('rejectFormBtn')
        ?.addEventListener('click', _openFormRejectModal);
    document.getElementById('confirmFormRejectBtn')
        ?.addEventListener('click', _confirmFormReject);
    // FEAT-0013: Delete and Restore buttons on edit page
    document.getElementById('deleteFormBtn')
        ?.addEventListener('click', _deleteFormFromEdit);
    document.getElementById('restoreFormBtn')
        ?.addEventListener('click', _restoreFormFromEdit);
    // FEAT-0016: Unpublish button and modal confirm
    document.getElementById('unpublishFormBtn')
        ?.addEventListener('click', _openFormUnpublishModal);
    document.getElementById('confirmFormUnpublishBtn')
        ?.addEventListener('click', _confirmFormUnpublish);
}

/**
 * Show/hide and label workflow action buttons based on form status and user permissions.
 * @param {string|null} status  Current form status, or null for create mode.
 */
function _updateWorkflowButtons(status) {
    const saveDraftBtn = document.getElementById('submitBtn');
    const submitForReviewBtn = document.getElementById('submitForReviewBtn');
    const approvePublishBtn = document.getElementById('approvePublishBtn');
    const rejectFormBtn = document.getElementById('rejectFormBtn');
    const archiveFormBtn = document.getElementById('archiveFormBtn');
    const deleteFormBtn = document.getElementById('deleteFormBtn');
    const restoreFormBtn = document.getElementById('restoreFormBtn');
    const unpublishFormBtn = document.getElementById('unpublishFormBtn');

    // Default: hide all workflow extras
    [submitForReviewBtn, approvePublishBtn, rejectFormBtn, archiveFormBtn, deleteFormBtn, restoreFormBtn, unpublishFormBtn].forEach(el => {
        if (el) el.style.display = 'none';
    });

    if (!status) {
        // Create mode — just show "Save draft"
        if (saveDraftBtn) saveDraftBtn.style.display = hasPermission('form:create') ? '' : 'none';
        return;
    }

    // FEAT-0013: Determine ownership for submit button
    const user = getCurrentUser();
    const userId = user?.id || '';
    const isOwner = _currentFormCreatedById === userId;

    if (status === 'draft') {
        if (saveDraftBtn) saveDraftBtn.style.display = hasPermission('form:edit') ? '' : 'none';
        if (submitForReviewBtn && isOwner && hasPermission('form:submit_for_review')) {
            submitForReviewBtn.style.display = '';
        }
        // FEAT-0013: Delete button for draft forms (owner or admin only)
        if (deleteFormBtn && hasPermission('form:delete') && (isOwner || isAdminUser())) {
            deleteFormBtn.style.display = '';
        }
    } else if (status === 'pending_review') {
        // Locked — no save/edit actions available to creators
        if (saveDraftBtn) saveDraftBtn.style.display = 'none';
        if (approvePublishBtn && hasPermission('form:approve') && hasPermission('form:review')) {
            approvePublishBtn.style.display = '';
        }
        if (rejectFormBtn && hasPermission('form:approve') && hasPermission('form:review')) {
            rejectFormBtn.style.display = '';
        }
    } else if (status === 'published') {
        if (saveDraftBtn) saveDraftBtn.style.display = 'none';
        if (archiveFormBtn && hasPermission('form:archive')) {
            archiveFormBtn.style.display = '';
        }
        // FEAT-0016: Unpublish button — requires both form:create and form:edit
        if (unpublishFormBtn && hasPermission('form:create') && hasPermission('form:edit')) {
            unpublishFormBtn.style.display = '';
        }
    } else if (status === 'archived') {
        if (saveDraftBtn) saveDraftBtn.style.display = 'none';
        // FEAT-0013: Restore button for archived forms
        if (restoreFormBtn && hasPermission('form:approve')) {
            restoreFormBtn.style.display = '';
        }
    } else {
        // unknown — no actions
        if (saveDraftBtn) saveDraftBtn.style.display = 'none';
    }
}

/**
 * Lock or unlock all form fields.
 * @param {boolean} locked
 */
function _setFormFieldsLocked(locked) {
    const selectors = [
        '#title', '#description', '#formSource', '#formSourceUrl',
        '#effectiveDate', '#isPublic', '#collectsPersonalInfo',
        '#businessAreaInput', '#formNumber',
    ];
    selectors.forEach(sel => {
        const el = document.querySelector(sel);
        if (el) el.disabled = locked;
    });
    // File upload area
    const uploadArea = document.getElementById('fileUploadArea');
    if (uploadArea) uploadArea.style.pointerEvents = locked ? 'none' : '';
    // Keywords input
    const keywordInput = document.getElementById('keywordInput');
    if (keywordInput) keywordInput.disabled = locked;
    const addKeywordBtn = document.getElementById('addKeywordBtn');
    if (addKeywordBtn) addKeywordBtn.disabled = locked;
    setKeywordsLocked(locked);
}

// ─── Workflow action handlers ─────────────────────────────────────────────────

async function _submitFormForReview() {
    if (!_currentFormId) return;
    if (!_hasActiveBusinessArea() || document.getElementById('businessAreaValue').value !== _savedBusinessAreaId) {
        _showBusinessAreaError('Save the form with an active Business Area before submitting.');
        return;
    }
    const btn = document.getElementById('submitForReviewBtn');
    btn.disabled = true;
    try {
        const response = await fetch(`${API_BASE}/staff/forms/${_currentFormId}/submit`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to submit for review');
        }
        showAlert('Form submitted for review successfully.', 'success');
        setTimeout(() => _navigate(ROUTES.FORMS_LIST), 1500);
    } catch (error) {
        if (error.message.includes('Business Area')) {
            _handleInvalidBusinessArea(error.message);
        } else {
            showAlert('Error: ' + error.message, 'danger');
        }
    } finally {
        _updateBusinessAreaActions();
    }
}

async function _approveAndPublish() {
    if (!_currentFormId) return;
    const btn = document.getElementById('approvePublishBtn');
    btn.disabled = true;
    try {
        const response = await fetch(`${API_BASE}/staff/forms/${_currentFormId}/approve`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to approve form');
        }
        showAlert('Form has been approved and published.', 'success');
        setTimeout(() => _navigate(ROUTES.FORMS_LIST), 1500);
    } catch (error) {
        showAlert('Error: ' + error.message, 'danger');
    } finally {
        btn.disabled = false;
    }
}

function _openFormRejectModal() {
    const reasonField = document.getElementById('formRejectReason');
    if (reasonField) {
        reasonField.value = '';
        reasonField.classList.remove('is-invalid');
    }
    window.bootstrap?.Modal.getOrCreateInstance(
        document.getElementById('formRejectModal')
    )?.show();
}

async function _confirmFormReject() {
    if (!_currentFormId) return;
    const reasonField = document.getElementById('formRejectReason');
    const reason = reasonField?.value?.trim() || '';
    if (!reason) {
        reasonField?.classList.add('is-invalid');
        return;
    }

    const btn = document.getElementById('confirmFormRejectBtn');
    btn.disabled = true;
    try {
        const response = await fetch(`${API_BASE}/staff/forms/${_currentFormId}/reject`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${getAuthToken()}`,
            },
            body: JSON.stringify({ reason_notes: reason }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to reject form');
        }
        window.bootstrap?.Modal.getInstance(
            document.getElementById('formRejectModal')
        )?.hide();
        showAlert('Form rejected and returned to draft.', 'warning');
        setTimeout(() => _navigate(ROUTES.FORMS_LIST), 1500);
    } catch (error) {
        showAlert('Error: ' + error.message, 'danger');
    } finally {
        btn.disabled = false;
    }
}

async function _archiveForm() {
    if (!_currentFormId) return;
    const btn = document.getElementById('archiveFormBtn');
    btn.disabled = true;
    try {
        const response = await fetch(`${API_BASE}/staff/forms/${_currentFormId}/archive`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to archive form');
        }
        showAlert('Form archived successfully.', 'success');
        setTimeout(() => _navigate(ROUTES.FORMS_LIST), 1500);
    } catch (error) {
        showAlert('Error: ' + error.message, 'danger');
    } finally {
        btn.disabled = false;
    }
}

// FEAT-0016: Open Unpublish confirmation modal
function _openFormUnpublishModal() {
    const reasonField = document.getElementById('formUnpublishReason');
    const errorDiv = document.getElementById('formUnpublishError');
    if (reasonField) {
        reasonField.value = '';
        reasonField.classList.remove('is-invalid');
    }
    if (errorDiv) errorDiv.style.display = 'none';
    window.bootstrap?.Modal.getOrCreateInstance(
        document.getElementById('formUnpublishModal')
    )?.show();
}

// FEAT-0016: Confirm Unpublish — calls POST /{form_id}/revert
async function _confirmFormUnpublish() {
    if (!_currentFormId) return;
    const reasonField = document.getElementById('formUnpublishReason');
    const errorDiv = document.getElementById('formUnpublishError');
    const reason = reasonField?.value?.trim() || '';

    if (!reason) {
        reasonField?.classList.add('is-invalid');
        return;
    }

    const btn = document.getElementById('confirmFormUnpublishBtn');
    btn.disabled = true;
    if (errorDiv) errorDiv.style.display = 'none';

    try {
        const response = await fetch(`${API_BASE}/staff/forms/${_currentFormId}/revert`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${getAuthToken()}`,
            },
            body: JSON.stringify({ reason_notes: reason }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to unpublish form');
        }
        window.bootstrap?.Modal.getOrCreateInstance(
            document.getElementById('formUnpublishModal')
        )?.hide();
        // Stay on edit page — reload form so all UI reflects Draft state
        await _loadFormForEdit(_currentFormId);
        showAlert('Form has been unpublished and returned to Draft.', 'success');
    } catch (error) {
        if (errorDiv) {
            errorDiv.textContent = 'Error: ' + error.message;
            errorDiv.style.display = '';
        }
    } finally {
        btn.disabled = false;
    }
}

// FEAT-0013: Delete from edit page (draft forms only)
async function _deleteFormFromEdit() {
    if (!_currentFormId) return;
    const title = document.getElementById('title')?.value || 'this form';
    if (!confirm(`Are you sure you want to delete "${title}"?`)) return;

    const btn = document.getElementById('deleteFormBtn');
    btn.disabled = true;
    try {
        const response = await fetch(`${API_BASE}/forms/${_currentFormId}`, {
            method: 'DELETE',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to delete form');
        }
        showAlert('Form deleted successfully.', 'success');
        setTimeout(() => _navigate(ROUTES.FORMS_LIST), 1500);
    } catch (error) {
        showAlert('Error: ' + error.message, 'danger');
    } finally {
        btn.disabled = false;
    }
}

// FEAT-0013: Restore from edit page (archived forms only — stays on page)
async function _restoreFormFromEdit() {
    if (!_currentFormId) return;
    const title = document.getElementById('title')?.value || 'this form';
    if (!confirm(`Restore "${title}" to published status?`)) return;

    const btn = document.getElementById('restoreFormBtn');
    btn.disabled = true;
    try {
        const response = await fetch(`${API_BASE}/staff/forms/${_currentFormId}/restore`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to restore form');
        }
        // Stay on page — re-fetch form so all derived UI state matches backend
        await _loadFormForEdit(_currentFormId);
        showAlert('Form restored to published status.', 'success');
    } catch (error) {
        showAlert('Error: ' + error.message, 'danger');
    } finally {
        btn.disabled = false;
    }
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Mount the blank "Create New Form" view.
 * Resets all state, wires up sub-modules, and loads dynamic dropdown data.
 */
export async function showCreateView() {
    resetFormState();
    document.getElementById('createView').style.display = 'block';

    // Sub-module init (safe to call on every visit — each call rebinds listeners)
    initKeywords();
    initFileUpload();
    initBusinessAreaCombobox();
    _initFormListeners();
    _setFormFieldsLocked(!hasPermission('form:create'));
    _updateWorkflowButtons(null);

    // Load dynamic dropdown data
    _loadFormBusinessAreas();
    loadFormNumberReservations();
}

/**
 * Mount the "Edit Form" view pre-populated with data from the API.
 * @param {string} formId  UUID of the form to edit.
 */
export async function showEditView(formId) {
    resetFormState();

    // Sub-module init
    initKeywords();
    initFileUpload();
    initBusinessAreaCombobox();
    _initFormListeners();

    // Fetch and populate form data
    await _loadFormForEdit(formId);
}

/**
 * Fetch an existing form from the API and populate all form fields.
 * @param {string} formId
 */
async function _loadFormForEdit(formId) {
    try {
        const response = await fetch(`${API_BASE}/forms/${formId}`);
        if (!response.ok) throw new Error('Form not found');
        const form = await response.json();

        _currentFormId = formId;
        _currentFormCreatedById = form.created_by?.id || null;  // FEAT-0013

        // Scalar fields
        document.getElementById('title').value = form.title;
        document.getElementById('description').value = form.description || '';
        document.getElementById('isPublic').checked = form.is_public;
        document.getElementById('collectsPersonalInfo').value = form.collects_personal_info || 'No';
        document.getElementById('effectiveDate').value = form.effective_date
            ? form.effective_date.split('T')[0]
            : '';
        document.getElementById('formSource').value = form.form_source || '';
        document.getElementById('formSourceUrl').value = form.form_source_url || '';

        // TASK-415: Show read-only form number in edit mode
        document.getElementById('formNumberSelectContainer').style.display = 'none';
        document.getElementById('formNumberRequiredStar').style.display = 'none';
        document.getElementById('formNumberReadonlyContainer').style.display = 'block';
        document.getElementById('formNumberReadonly').textContent = getFormNumberDisplay(form) || 'N/A';
        document.getElementById('formNumber').required = false;

        // TASK-416: Restore attachment state when editing a Download-type form
        if (form.form_source === 'Download' && form.form_attachment_url) {
            restoreUploadState(
                form.form_attachment_url,
                form.form_attachment_filename || 'Attachment',
                form.file_type || null,
            );
        }
        _onFormSourceChange();

        setKeywords(form.keywords || []);
        _loadedKeywords = getKeywords();

        // Workflow button state and field locking (FEAT-0001)
        _currentFormStatus = form.status;
        _savedBusinessAreaId = form.business_area?.id || null;
        _updateWorkflowButtons(form.status);
        const isLocked = form.status !== 'draft' || !hasPermission('form:edit');
        _setFormFieldsLocked(isLocked);

        // Label the submit button based on status
        const submitBtn = document.getElementById('submitBtn');
        if (form.status === 'draft') {
            if (submitBtn) submitBtn.innerHTML = '<i class="fas fa-save"></i> Save draft';
            document.getElementById('formPageHeading').textContent = 'Edit Form';
        } else {
            if (submitBtn) submitBtn.style.display = 'none';
            document.getElementById('formPageHeading').textContent =
                form.status === 'pending_review' ? 'Review Form' : 'View Form';
        }
        document.getElementById('formBreadcrumbCurrent').textContent = getFormNumberDisplay(form) || 'Edit Form';
        document.getElementById('formPageSubtitle').textContent =
            `${getFormNumberDisplay(form) || 'Form'}: ${form.title}`;
        const badge = document.getElementById('formStatusBadge');
        badge.textContent = form.status.replace(/_/g, ' ').replace(/\b\w/g, character => character.toUpperCase());
        badge.style.display = '';
        document.getElementById('pageTitle').textContent = `Edit Form - ${form.title} - BC Gov`;

        document.getElementById('listView').style.display = 'none';
        document.getElementById('createView').style.display = 'block';
        window.scrollTo(0, 0);
        await _loadFormBusinessAreas(form.business_area);
    } catch (error) {
        showAlert('Error loading form: ' + error.message, 'danger');
        setTimeout(() => _navigate(ROUTES.FORMS_LIST), 2000);
    }
}

/**
 * Handle create (POST) and edit (PUT) form submission.
 * Validates client-side before sending, maps API validation errors to field UI.
 * @param {Event} event  The form submit event.
 */
export async function handleFormSubmit(event) {
    event.preventDefault();
    clearAllFieldErrors();
    let firstInvalidField = null;
    const requireField = (fieldId, message) => {
        showFieldError(fieldId, message);
        const input = document.getElementById(fieldId) || (fieldId === 'fileUpload' && document.getElementById('formSource'));
        if (!firstInvalidField && input && !input.disabled) firstInvalidField = input.id;
    };

    // Validate form number selection on create only (TASK-413 / TASK-415)
    const formNumberValue = document.getElementById('formNumber').value;
    if (!_currentFormId && !formNumberValue) {
        requireField('formNumber', 'Please select a Form Number.');
    }
    if (!_hasActiveBusinessArea()) {
        requireField('businessAreaInput', 'Select an active Business Area before saving.');
    }
    if (!document.getElementById('title').value.trim()) {
        requireField('title', 'Enter a Form Title.');
    }
    if (!document.getElementById('description').value.trim()) {
        requireField('description', 'Enter a Description.');
    }

    const formSource = document.getElementById('formSource').value;
    const uploadedFileUrl = getUploadedFileUrl();
    const uploadedFileFilename = getUploadedFileFilename();

    // TASK-416: In create mode a file is always required; in edit mode,
    // formSource='Download' with no file means "clear the attachment" — allowed.
    if (!_currentFormId && formSource === 'Download' && !uploadedFileUrl) {
        requireField('fileUpload', 'Please upload a file before submitting.');
    }
    if (formSource === 'URL' && !document.getElementById('formSourceUrl').value.trim()) {
        requireField('formSourceUrl', 'Form URL is required when Form Source is URL.');
    }
    if (firstInvalidField) {
        document.getElementById(firstInvalidField)?.focus();
        _updateBusinessAreaActions();
        return;
    }

    // Editing + Download + no file → treat as clearing the attachment
    const effectiveFormSource = (_currentFormId && formSource === 'Download' && !uploadedFileUrl)
        ? null
        : (formSource || null);

    const formData = {
        title: document.getElementById('title').value,
        description: document.getElementById('description').value,
        is_public: document.getElementById('isPublic').checked,
        ...((!_currentFormId || JSON.stringify(getKeywords()) !== JSON.stringify(_loadedKeywords)) && { keywords: getKeywords() }),
        business_area_id: document.getElementById('businessAreaValue').value,
        effective_date: document.getElementById('effectiveDate').value || null,
        collects_personal_info: document.getElementById('collectsPersonalInfo').value,
        // TASK-110C source fields
        form_source: effectiveFormSource,
        form_source_url: effectiveFormSource === 'URL'
            ? document.getElementById('formSourceUrl').value
            : null,
        form_attachment_url: effectiveFormSource === 'Download' ? uploadedFileUrl : null,
        form_attachment_filename: effectiveFormSource === 'Download' ? uploadedFileFilename : null,
        // FEAT-0002: file type derived at upload time
        file_type: effectiveFormSource === 'Download' ? (getUploadedFileType() || null) : null,
        // TASK-413: Reservation linkage on create only (TASK-415 locks it on edit)
        ...(!_currentFormId && { form_number_reservation_id: formNumberValue || null }),
    };

    const token = getAuthToken();

    try {
        document.getElementById('submitBtn').disabled = true;

        let response;
        if (_currentFormId) {
            // PUT /api/v1/forms/{id}
            response = await fetch(`${API_BASE}/forms/${_currentFormId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`,
                },
                body: JSON.stringify(formData),
            });
        } else {
            // POST /api/v1/forms
            response = await fetch(`${API_BASE}/forms`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`,
                },
                body: JSON.stringify(formData),
            });
        }

        if (!response.ok) {
            const error = await response.json();
            if (typeof error.detail === 'string' && error.detail.includes('Business Area')) {
                _handleInvalidBusinessArea(error.detail);
            } else {
                showValidationErrors(error.detail);
            }
            throw new Error(
                typeof error.detail === 'string'
                    ? error.detail
                    : 'Validation failed \u2014 see errors above',
            );
        }

        await response.json(); // consume the saved form (caller can extend if needed)
        showAlert(
            _currentFormId ? 'Form updated successfully' : 'Form created successfully',
            'success',
        );
        _currentFormId = null;
        _formNumberReservationId = null;

        setTimeout(() => _navigate(ROUTES.FORMS_LIST), 1500);
    } catch (error) {
        // Only show a generic alert when no inline field errors are already visible
        const hasInlineErrors =
            document.getElementById('formErrors')?.style.display !== 'none' ||
            document.querySelector('.is-invalid');
        if (!hasInlineErrors) {
            showAlert('Error saving form: ' + error.message, 'danger');
        }
    } finally {
        _updateBusinessAreaActions();
    }
}

/**
 * Reset all form fields and module state to blank-create defaults.
 * Called at the start of both showCreateView() and showEditView().
 */
export function resetFormState() {
    const form = document.getElementById('formCreate');
    if (form) form.reset();

    ++_businessAreaLoadVersion;
    resetBusinessAreas();
    _businessAreasState = 'loading';
    _savedBusinessAreaId = null;
    setKeywords([]);
    _loadedKeywords = [];
    _currentFormId = null;
    _currentFormStatus = null;
    _currentFormCreatedById = null;  // FEAT-0013
    clearUploadState();
    _formNumberReservationId = null;

    const submitBtn = document.getElementById('submitBtn');
    if (submitBtn) {
        submitBtn.innerHTML = '<i class="fas fa-save"></i> Save draft';
        submitBtn.style.display = '';
    }

    // Hide workflow action buttons — they are shown per-status in _updateWorkflowButtons
    ['submitForReviewBtn', 'approvePublishBtn', 'rejectFormBtn', 'archiveFormBtn', 'deleteFormBtn', 'restoreFormBtn', 'unpublishFormBtn'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    _setFormFieldsLocked(false);

    const heading = document.getElementById('formPageHeading');
    if (heading) heading.textContent = 'Add New Form';
    document.getElementById('formBreadcrumbCurrent').textContent = 'Add New Form';
    document.getElementById('formPageSubtitle').textContent = 'Complete the form details below.';
    document.getElementById('formStatusBadge').style.display = 'none';
    document.getElementById('businessAreaMessage').textContent = '';
    document.getElementById('retryBusinessAreasBtn').style.display = 'none';

    // TASK-415: Reset to dropdown mode (as opposed to read-only edit mode)
    const formNumberSelect = document.getElementById('formNumberSelectContainer');
    if (formNumberSelect) formNumberSelect.style.display = 'block';
    const requiredStar = document.getElementById('formNumberRequiredStar');
    if (requiredStar) requiredStar.style.display = 'inline';
    const readonlyContainer = document.getElementById('formNumberReadonlyContainer');
    if (readonlyContainer) readonlyContainer.style.display = 'none';
    const formNumberEl = document.getElementById('formNumber');
    if (formNumberEl) formNumberEl.required = true;

    // Hide conditional source sections
    const sourceUrl = document.getElementById('sourceUrlSection');
    if (sourceUrl) sourceUrl.style.display = 'none';
    const sourceDl = document.getElementById('sourceDownloadSection');
    if (sourceDl) sourceDl.style.display = 'none';
    const uploadProgress = document.getElementById('uploadProgress');
    if (uploadProgress) uploadProgress.style.display = 'none';
    const uploadedFileInfo = document.getElementById('uploadedFileInfo');
    if (uploadedFileInfo) uploadedFileInfo.style.display = 'none';

    // Clear business area combobox
    const baInput = document.getElementById('businessAreaInput');
    if (baInput) baInput.value = '';
    const baValue = document.getElementById('businessAreaValue');
    if (baValue) baValue.value = '';
    closeBusinessAreaDropdown();

    clearAllFieldErrors();
    _updateBusinessAreaActions();
}

/**
 * Populate the "approved unused" form-number dropdown.
 * Shows a spinner while loading and an error/info message on failure or empty state.
 * Endpoint: GET /api/v1/reservations/approved-unused
 */
export async function loadFormNumberReservations() {
    const select = document.getElementById('formNumber');
    const spinner = document.getElementById('formNumberSpinner');
    const errorDiv = document.getElementById('formNumberError');
    if (!select) return;

    spinner.style.display = 'block';
    errorDiv.style.display = 'none';
    select.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/reservations/approved-unused`, {
            headers: { 'Authorization': `Bearer ${getAuthToken()}` },
        });

        if (!response.ok) {
            throw new Error('Failed to load approved form numbers');
        }

        const data = await response.json();
        _formNumberReservations = data.reservations || [];

        select.innerHTML = '<option value="">-- Select a Form Number --</option>';

        if (_formNumberReservations.length === 0) {
            select.innerHTML = '<option value="" disabled>No approved form numbers available</option>';
            select.disabled = true;
            errorDiv.style.display = 'block';
            errorDiv.innerHTML =
                '<i class="fas fa-info-circle"></i> No approved form numbers are currently available. ' +
                'Please <a href="/reserve">reserve a form number</a> first.';
            return;
        }

        // Sort newest first
        _formNumberReservations.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

        _formNumberReservations.forEach(res => {
            const opt = document.createElement('option');
            opt.value = res.id;

            let label = res.full_form_number;
            if (res.numbering_method === 'custom' && res.custom_number_reason) {
                label += ` \u2014 Custom: ${res.custom_number_reason}`;
            }
            opt.textContent = label;
            opt.dataset.reservationId = res.id;
            select.appendChild(opt);
        });

        select.disabled = false;
    } catch (error) {
        console.error('Error loading form numbers:', error);
        select.innerHTML = '<option value="" disabled>Error loading form numbers</option>';
        select.disabled = true;
        errorDiv.style.display = 'block';
        errorDiv.innerHTML =
            `<i class="fas fa-exclamation-circle"></i> Failed to load approved form numbers: ` +
            `${escapeHtml(error.message)}. ` +
            `<a href="#" data-action="retry-load-form-numbers">Retry</a>`;

        // Delegated retry handler (no inline onclick)
        errorDiv.querySelector('[data-action="retry-load-form-numbers"]')
            ?.addEventListener('click', (e) => {
                e.preventDefault();
                loadFormNumberReservations();
            });
    } finally {
        spinner.style.display = 'none';
    }
}
