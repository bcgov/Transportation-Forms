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
import { clearAllFieldErrors, showFieldError, showValidationErrors } from '../validation.js';
import { initKeywords, getKeywords, setKeywords, addKeyword } from './keywords.js';
import {
    initFileUpload,
    getUploadedFileUrl,
    getUploadedFileFilename,
    clearUploadState,
    restoreUploadState,
} from './file-upload.js';
import { loadBusinessAreas, initBusinessAreaCombobox, getBusinessAreaOptions, closeBusinessAreaDropdown } from './business-areas.js';
import { getAuthToken } from '../auth.js';

// ─── Module-private state ─────────────────────────────────────────────────────

let _currentFormId = null;
let _formNumberReservationId = null;
let _formNumberReservations = [];

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

/** Wire up all event listeners for the create/edit form. Safe to call multiple times. */
function _initFormListeners() {
    const form = document.getElementById('formCreate');
    if (!form) return;

    // Prevent duplicate listeners by removing before re-adding
    form.removeEventListener('submit', handleFormSubmit);
    form.addEventListener('submit', handleFormSubmit);

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

    // Load dynamic dropdown data
    loadBusinessAreas();
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
            );
        }
        _onFormSourceChange();

        // TASK-418: Pre-select the saved business area once the dropdown has loaded
        loadBusinessAreas().then(() => {
            const options = getBusinessAreaOptions();
            const firstArea = (form.business_areas || [])[0];
            if (firstArea) {
                const selected = options.find(o => o.id === firstArea.id);
                if (selected) {
                    document.getElementById('businessAreaInput').value = selected.label;
                    document.getElementById('businessAreaValue').value = selected.id;
                }
            }
        });

        setKeywords(form.keywords || []);

        document.getElementById('submitBtn').textContent = 'Update Form';
        document.querySelector('#createView h2').textContent = 'Edit Form';
        document.getElementById('pageTitle').textContent = `Edit Form - ${form.title} - BC Gov`;

        document.getElementById('listView').style.display = 'none';
        document.getElementById('createView').style.display = 'block';
        window.scrollTo(0, 0);
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

    // Validate form number selection on create only (TASK-413 / TASK-415)
    const formNumberValue = document.getElementById('formNumber').value;
    if (!_currentFormId && !formNumberValue) {
        showFieldError('formNumber', 'Please select a Form Number.');
        return;
    }

    const formSource = document.getElementById('formSource').value;
    const uploadedFileUrl = getUploadedFileUrl();
    const uploadedFileFilename = getUploadedFileFilename();

    // TASK-416: In create mode a file is always required; in edit mode,
    // formSource='Download' with no file means "clear the attachment" — allowed.
    if (!_currentFormId && formSource === 'Download' && !uploadedFileUrl) {
        showFieldError('fileUpload', 'Please upload a file before submitting.');
        return;
    }
    if (formSource === 'URL' && !document.getElementById('formSourceUrl').value.trim()) {
        showFieldError('formSourceUrl', 'Form URL is required when Form Source is URL.');
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
        keywords: getKeywords(),
        business_area_ids: (() => {
            const v = document.getElementById('businessAreaValue').value;
            return v ? [v] : [];
        })(),
        effective_date: document.getElementById('effectiveDate').value || null,
        collects_personal_info: document.getElementById('collectsPersonalInfo').value,
        // TASK-110C source fields
        form_source: effectiveFormSource,
        form_source_url: effectiveFormSource === 'URL'
            ? document.getElementById('formSourceUrl').value
            : null,
        form_attachment_url: effectiveFormSource === 'Download' ? uploadedFileUrl : null,
        form_attachment_filename: effectiveFormSource === 'Download' ? uploadedFileFilename : null,
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
            showValidationErrors(error.detail);
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
        document.getElementById('submitBtn').disabled = false;
    }
}

/**
 * Reset all form fields and module state to blank-create defaults.
 * Called at the start of both showCreateView() and showEditView().
 */
export function resetFormState() {
    const form = document.getElementById('formCreate');
    if (form) form.reset();

    setKeywords([]);
    _currentFormId = null;
    clearUploadState();
    _formNumberReservationId = null;

    const submitBtn = document.getElementById('submitBtn');
    if (submitBtn) submitBtn.textContent = 'Create Form';

    const heading = document.querySelector('#createView h2');
    if (heading) heading.textContent = 'Add New Form';

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
