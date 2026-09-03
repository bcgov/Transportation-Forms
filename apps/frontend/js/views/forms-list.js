// frontend/js/views/forms-list.js
// Manages the forms list/search/pagination view.
import { API_BASE, ROUTES } from '../constants.js';
import {
    escapeHtml,
    showAlert,
    getFormNumberDisplay,
    showNotification,
} from '../utils.js';
import {
    getBusinessAreaOptions,
    loadBusinessAreas,
    resetBusinessAreas,
} from './business-areas.js';
import {
    getAuthToken,
    hasPermission,
    hasPortalRoles,
    isAdminUser,
    isStaffViewerOnly,
} from '../auth.js';
import { getCurrentUser } from '../state.js';
import { openFormViewPopup, downloadFormAttachment } from '../shared/form-view-popup.js';

// ── Module-private pagination state ──────────────────────────────────────────
let _currentSkip = 0;
let _currentLimit = 24;
let _lastListTotal = 0;
let _formsRequestController = null;
let _isFormsRequestPending = false;
let _autocompleteRequestController = null;
let _autocompleteDebounceTimer = null;
let _isDismissingSearchSuggestions = false;
let _formsLifecycleGeneration = 0;
const ALLOWED_PAGE_SIZES = new Set([24, 48, 96]);
const MAX_FORM_ID_LENGTH = 128;
const MAX_FORM_NUMBER_LENGTH = 100;
const MAX_FORM_TITLE_LENGTH = 300;
const MAX_FORM_DESCRIPTION_LENGTH = 4000;
const MAX_FORM_FIELD_LENGTH = 255;
const MAX_FORM_URL_LENGTH = 2048;
const DEFAULT_RESULTS_LAYOUT = 'list';
const RESULTS_LAYOUTS = new Set(['list', 'grid']);
const RESULTS_LAYOUT_STORAGE_PREFIX = 'transportation-forms:forms-layout:v1:';
const FORM_WORKFLOW_STATES = new Set(['draft', 'pending_review', 'published', 'archived']);

// ── Module-private setup flag & navigate callback ─────────────────────────────
let _initialized = false;
let _navigate = null;
let _currentResultsLayout = DEFAULT_RESULTS_LAYOUT;
let _layoutPreferenceGeneration = 0;

// ── Filter combobox state ─────────────────────────────────────────────────────
let _selectedFilterChips = [];   // array of { key, label, category }
let _selectedBusinessAreaIds = [];

function _resetFormsListLifecycle() {
    _formsLifecycleGeneration += 1;
    _layoutPreferenceGeneration += 1;
    _formsRequestController?.abort();
    _autocompleteRequestController?.abort();
    clearTimeout(_autocompleteDebounceTimer);
    _formsRequestController = null;
    _isFormsRequestPending = false;
    _autocompleteRequestController = null;
    _autocompleteDebounceTimer = null;
    resetBusinessAreas();
    _selectedFilterChips = [];
    _selectedBusinessAreaIds = [];
    _currentSkip = 0;
    _currentLimit = 24;
    _lastListTotal = 0;
    const list = document.getElementById('formsList');
    if (list) list.replaceChildren();
    _updateResultsSummary(0);
    const paginationContainer = document.getElementById('paginationContainer');
    if (paginationContainer) {
        paginationContainer.hidden = true;
        paginationContainer.removeAttribute('aria-busy');
    }
    const paginationSummary = document.getElementById('paginationSummary');
    if (paginationSummary) paginationSummary.textContent = 'Showing 0-0 of 0';
    const previousPage = document.getElementById('prevPageBtn');
    const nextPage = document.getElementById('nextPageBtn');
    if (previousPage) previousPage.disabled = true;
    if (nextPage) nextPage.disabled = true;
    const searchInput = document.getElementById('searchInput');
    if (searchInput) searchInput.value = '';
    const clearSearchButton = document.getElementById('clearSearchButton');
    if (clearSearchButton) clearSearchButton.hidden = true;
    const pageSize = document.getElementById('pageSizeSelect');
    if (pageSize) pageSize.value = '24';
    const sort = document.getElementById('sortOrder');
    if (sort) sort.value = 'created_at:desc';
    _dismissSearchSuggestions();
    _renderFiltersMenu();
    _renderActiveFilters();
}

window.addEventListener('app:route-changing', event => {
    const path = event.detail?.path || '';
    if (path !== ROUTES.FORMS_LIST && !path.startsWith('/forms/')) {
        _resetFormsListLifecycle();
    }
});
window.addEventListener('auth:session-expired', _resetFormsListLifecycle);
window.addEventListener('auth:session-started', _resetFormsListLifecycle);
window.addEventListener('auth:session-cleared', _resetFormsListLifecycle);
window.addEventListener('auth:authorization-refreshed', _resetFormsListLifecycle);

/**
 * All available filter options, grouped by category.
 * Each entry maps a unique key to its display label and the API parameter it
 * produces.  Entries marked `exclusive: true` belong to categories where only
 * one selection is allowed at a time.
 */
const _FILTER_OPTIONS = [
    // Visibility — mutually exclusive
    { key: 'vis:public',   label: 'Public only',       category: 'Visibility', apiParam: 'is_public', apiValue: 'true',  exclusive: true },
    { key: 'vis:internal', label: 'Internal only',      category: 'Visibility', apiParam: 'is_public', apiValue: 'false', exclusive: true },
    // Source — mutually exclusive
    { key: 'src:link',     label: 'Linked Form',        category: 'Source',     apiParam: 'form_source', apiValue: 'Link',     exclusive: true },
    { key: 'src:download', label: 'Downloadable Form',  category: 'Source',     apiParam: 'form_source', apiValue: 'Download', exclusive: true },
    // Workflow State — multi-select (OR within category)
    { key: 'ws:draft',          label: 'Draft',          category: 'Workflow State', apiParam: 'status', apiValue: 'draft',          exclusive: false },
    { key: 'ws:pending_review', label: 'Pending Review', category: 'Workflow State', apiParam: 'status', apiValue: 'pending_review', exclusive: false },
    { key: 'ws:published',      label: 'Published',      category: 'Workflow State', apiParam: 'status', apiValue: 'published',      exclusive: false },
    { key: 'ws:archived',       label: 'Archived',       category: 'Workflow State', apiParam: 'status', apiValue: 'archived',       exclusive: false },
];

function _boundedString(value, maxLength) {
    return typeof value === 'string' ? value.slice(0, maxLength) : '';
}

function _normalizeFormItem(item) {
    const reservation = item.form_number_reservation;
    const createdBy = item.created_by;
    const businessArea = item.business_area;
    return {
        id: _boundedString(item.id, MAX_FORM_ID_LENGTH),
        full_form_number: _boundedString(item.full_form_number, MAX_FORM_NUMBER_LENGTH),
        form_number: _boundedString(item.form_number, MAX_FORM_NUMBER_LENGTH),
        form_number_display: _boundedString(item.form_number_display, MAX_FORM_NUMBER_LENGTH),
        form_number_value: _boundedString(item.form_number_value, MAX_FORM_NUMBER_LENGTH),
        form_number_reservation: reservation && typeof reservation === 'object' ? {
            full_form_number: _boundedString(
                reservation.full_form_number,
                MAX_FORM_NUMBER_LENGTH
            ),
            form_number: _boundedString(reservation.form_number, MAX_FORM_NUMBER_LENGTH),
        } : null,
        title: _boundedString(item.title, MAX_FORM_TITLE_LENGTH),
        description: _boundedString(item.description, MAX_FORM_DESCRIPTION_LENGTH),
        status: _boundedString(item.status, MAX_FORM_FIELD_LENGTH),
        is_public: item.is_public === true,
        file_type: _boundedString(item.file_type, MAX_FORM_FIELD_LENGTH),
        form_source: _boundedString(item.form_source, MAX_FORM_FIELD_LENGTH),
        form_source_url: _boundedString(item.form_source_url, MAX_FORM_URL_LENGTH),
        form_attachment_url: _boundedString(item.form_attachment_url, MAX_FORM_URL_LENGTH),
        form_attachment_filename: _boundedString(
            item.form_attachment_filename,
            MAX_FORM_FIELD_LENGTH
        ),
        business_area: businessArea && typeof businessArea === 'object' ? {
            name: _boundedString(businessArea.name, MAX_FORM_FIELD_LENGTH),
        } : null,
        created_at: _boundedString(item.created_at, MAX_FORM_FIELD_LENGTH),
        updated_at: _boundedString(item.updated_at, MAX_FORM_FIELD_LENGTH),
        created_by: createdBy && typeof createdBy === 'object' ? {
            id: _boundedString(createdBy.id, MAX_FORM_ID_LENGTH),
        } : null,
    };
}

function _escapeAttribute(value) {
    return escapeHtml(value).replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function _defaultNavigate(path) {
    window.history.pushState({}, '', path);
    window.dispatchEvent(new PopStateEvent('popstate'));
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Show the forms list view.
 * @param {function} [navigateFn] - SPA navigation callback (path: string) => void.
 *   Falls back to pushState + popstate dispatch when omitted.
 */
export async function showFormsListView(navigateFn) {
    const lifecycleGeneration = _formsLifecycleGeneration;
    _navigate = navigateFn ?? _defaultNavigate;

    document.getElementById('listView').style.display = 'block';
    document.getElementById('pageTitle').textContent = 'Forms Library - BC Gov';

    if (!_initialized) {
        _initListViewEvents();
        _initialized = true;
    }

    const hasNoRoles = !hasPortalRoles();
    const requestAccessPanel = document.getElementById('requestAccessPanel');
    const formsLibraryContent = document.getElementById('formsLibraryContent');
    if (requestAccessPanel) {
        requestAccessPanel.style.display = hasNoRoles ? 'flex' : 'none';
    }
    if (formsLibraryContent) formsLibraryContent.hidden = hasNoRoles;
    if (hasNoRoles) return;

    await _restoreResultsLayoutPreference();
    if (lifecycleGeneration !== _formsLifecycleGeneration) return;
    _renderFiltersMenu();
    const selectedAreaIdsBeforeLoad = [..._selectedBusinessAreaIds];
    loadBusinessAreas().then(loaded => {
        if (lifecycleGeneration !== _formsLifecycleGeneration || !loaded) return;
        const validAreaIds = new Set(getBusinessAreaOptions().map(option => option.id));
        _selectedBusinessAreaIds = _selectedBusinessAreaIds.filter(id => validAreaIds.has(id));
        _renderFiltersMenu();
        _renderActiveFilters();
        const selectionChanged = selectedAreaIdsBeforeLoad.length !== _selectedBusinessAreaIds.length ||
            selectedAreaIdsBeforeLoad.some((id, index) => id !== _selectedBusinessAreaIds[index]);
        if (selectionChanged) loadForms();
    });
    loadForms();
}

/** Load (or reload) the forms list from the API, applying current filters & pagination. */
export async function loadForms(requestedSkip = _currentSkip) {
    _formsRequestController?.abort();
    const controller = new AbortController();
    _formsRequestController = controller;
    const { signal } = controller;
    const candidateSkip = Number.isSafeInteger(requestedSkip) && requestedSkip >= 0
        ? requestedSkip
        : 0;
    _isFormsRequestPending = true;
    _setPaginationPending();
    try {
        _renderResultsLoading();

        const params = new URLSearchParams();
        params.set('skip', String(candidateSkip));
        params.set('limit', String(_currentLimit));

        const query = document.getElementById('searchInput')?.value.trim() ?? '';
        if (query) params.set('q', query);

        _selectedBusinessAreaIds.forEach(id => params.append('business_area_ids', id));

        // Build filter params from chips
        _selectedFilterChips.forEach(chip => {
            const opt = _FILTER_OPTIONS.find(o => o.key === chip.key);
            if (opt) params.append(opt.apiParam, opt.apiValue);
        });

        // Sort — value format is "field:order" (e.g. "created_at:desc")
        const sortSelect = document.getElementById('sortOrder');
        const sortValue = sortSelect?.value || 'created_at:desc';
        const sortParts = sortValue.split(':');
        const sortField = sortParts[0] || 'created_at';
        const sortDir = sortParts[1] || 'desc';
        params.set('sort_field', sortField);
        params.set('sort_order', sortDir);

        const response = await fetch(`${API_BASE}/forms?${params.toString()}`, { signal });

        if (!response.ok) {
            throw new Error('Forms request failed');
        }

        const data = await response.json();
        if (signal.aborted) return;
        const items = data.items
            .filter(item => item && typeof item === 'object')
            .map(_normalizeFormItem)
            .filter(item => item.id);
        if (!_isValidFormsPage(data, candidateSkip, items.length)) {
            throw new Error('Invalid Forms response');
        }
        _currentSkip = candidateSkip;
        _lastListTotal = data.total;
        displayForms(items);
        _updatePaginationControls(_lastListTotal);
    } catch (error) {
        if (signal.aborted || error.name === 'AbortError') return;
        _currentSkip = 0;
        _lastListTotal = 0;
        displayForms([]);
        _updatePaginationControls(0);
        showAlert('Unable to load forms. Please try again.', 'danger');
    } finally {
        if (_formsRequestController === controller) {
            _formsRequestController = null;
            _isFormsRequestPending = false;
        }
    }
}

function _isValidFormsPage(data, requestedSkip, usableItemCount) {
    if (!Number.isSafeInteger(data?.total) || data.total < 0 || !Array.isArray(data.items)) {
        return false;
    }
    if (data.skip !== requestedSkip || data.limit !== _currentLimit) return false;
    const expectedItems = Math.min(_currentLimit, Math.max(0, data.total - requestedSkip));
    if (data.items.length !== expectedItems || usableItemCount !== expectedItems) return false;
    return data.total === 0 ? requestedSkip === 0 : requestedSkip < data.total;
}

/** Render the given array of form objects into #formsList. */
export function displayForms(forms) {
    const container = document.getElementById('formsList');
    if (!container) return;

    if (forms.length === 0) {
        container.innerHTML = `
            <li class="empty-state">
                <i class="fas fa-magnifying-glass" aria-hidden="true"></i>
                <h2>No forms match this view</h2>
                <p>Adjust your search or remove a filter.</p>
            </li>
        `;
        return;
    }

    container.innerHTML = forms.map(form => `
        <li class="forms-result-item">
            <article class="forms-result-card" aria-labelledby="form-title-${_escapeAttribute(form.id)}">
                <span class="forms-result-card__accent" aria-hidden="true"></span>
                <div class="forms-result-card__body">
                    <div class="forms-result-card__meta">
                        <button class="forms-result-card__number" type="button"
                            data-action="view-form" data-form-id="${_escapeAttribute(form.id)}"
                            aria-label="Open details for form ${_escapeAttribute(getFormNumberDisplay(form))} from form number">
                            ${escapeHtml(getFormNumberDisplay(form))}
                        </button>
                        ${form.business_area?.name ? `<span class="forms-result-card__business-area">${escapeHtml(form.business_area.name)}</span>` : ''}
                        <span class="forms-result-card__date">Updated ${escapeHtml(_formatUpdatedDate(form.updated_at))}</span>
                    </div>
                    <h2 class="forms-result-card__title" id="form-title-${_escapeAttribute(form.id)}">${escapeHtml(form.title)}</h2>
                    <p class="forms-result-card__description"${form.description ? ` title="${_escapeAttribute(form.description)}"` : ''}>${escapeHtml(form.description || 'No description')}</p>
                    <div class="forms-result-card__footer">
                        ${_renderFormSourceType(form)}
                        <span class="forms-result-card__status" data-status="${_escapeAttribute(form.status)}">${escapeHtml(_formatStatus(form.status))}</span>
                        <button class="forms-result-card__view" type="button"
                            data-action="view-form" data-form-id="${_escapeAttribute(form.id)}"
                            aria-label="View details for form ${_escapeAttribute(getFormNumberDisplay(form))}">
                            <i class="fas fa-eye" aria-hidden="true"></i> View details
                        </button>
                        ${_renderFormSourceButton(form)}
                        <div class="forms-result-card__actions" role="group"
                            aria-label="Available actions for ${_escapeAttribute(getFormNumberDisplay(form))}">
                            ${_renderFormActionButtons(form)}
                        </div>
                    </div>
                </div>
            </article>
        </li>
    `).join('');
}

function _renderResultsLoading() {
    const container = document.getElementById('formsList');
    if (!container) return;
    container.innerHTML = `
        <li class="spinner-container">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading forms...</span>
            </div>
        </li>
    `;
}

function _formatUpdatedDate(value) {
    if (!value) return 'date unavailable';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'date unavailable' : date.toLocaleDateString();
}

function _formatStatus(status) {
    if (!FORM_WORKFLOW_STATES.has(status)) return 'Unknown status';
    return status.split('_').map(word => word[0].toUpperCase() + word.slice(1)).join(' ');
}

/**
 * FEAT-0013: Render state-aware, permission-gated action buttons for a form card.
 * @param {object} form  Form object from the API (includes status, created_by, id).
 * @returns {string} HTML string of buttons.
 */
function _renderFormActionButtons(form) {
    const buttons = [];
    const id = _escapeAttribute(form.id);
    const formLabel = _escapeAttribute(getFormNumberDisplay(form));
    const status = form.status;
    const user = getCurrentUser();
    const isKnownStatus = FORM_WORKFLOW_STATES.has(status);
    if (!isKnownStatus || !user || !Array.isArray(user.permissions)) return '';
    const userId = user?.id || '';
    const isOwner = form.created_by?.id === userId;

    // Edit — draft + published, form:edit
    if ((status === 'draft' || status === 'published') && hasPermission('form:edit')) {
        buttons.push(`<button class="forms-result-card__action" type="button"
            data-action="navigate" data-route="/edit/${id}"
            aria-label="Edit form ${formLabel}">
            <i class="fas fa-edit" aria-hidden="true"></i> Edit</button>`);
    }

    // Submit — draft only, creator only, form:submit_for_review
    if (status === 'draft' && isOwner && hasPermission('form:submit_for_review')) {
        buttons.push(`<button class="forms-result-card__action forms-result-card__action--submit" type="button"
            data-action="submit-form" data-form-id="${id}"
            data-form-title="${_escapeAttribute(form.title)}"
            aria-label="Submit form ${formLabel} for review">
            <i class="fas fa-paper-plane" aria-hidden="true"></i> Submit</button>`);
    }

    // Archive — published only, form:archive
    if (status === 'published' && hasPermission('form:archive')) {
        buttons.push(`<button class="forms-result-card__action" type="button"
            data-action="archive-form" data-form-id="${id}"
            data-form-title="${_escapeAttribute(form.title)}"
            aria-label="Archive form ${formLabel}">
            <i class="fas fa-archive" aria-hidden="true"></i> Archive</button>`);
    }

    // Restore — archived only, form:approve
    if (status === 'archived' && hasPermission('form:approve')) {
        buttons.push(`<button class="forms-result-card__action" type="button"
            data-action="restore-form" data-form-id="${id}"
            data-form-title="${_escapeAttribute(form.title)}"
            aria-label="Restore form ${formLabel}">
            <i class="fas fa-undo" aria-hidden="true"></i> Restore</button>`);
    }

    // Delete — draft only, form:delete, owner or admin (matches backend enforcement)
    if (status === 'draft' && hasPermission('form:delete') && (isOwner || isAdminUser())) {
        buttons.push(`<button class="forms-result-card__action forms-result-card__action--danger" type="button"
            data-action="delete-form" data-form-id="${id}"
            data-form-title="${_escapeAttribute(form.title)}"
            aria-label="Delete form ${formLabel}">
            <i class="fas fa-trash" aria-hidden="true"></i> Delete</button>`);
    }

    return buttons.join('\n');
}

function _renderFormSourceType(form) {
    if (form.form_source === 'Download' && form.form_attachment_url) {
        const fileType = form.file_type || 'unknown';
        return `<span class="forms-result-card__source-type" data-source="download">${escapeHtml(fileType.toUpperCase())}</span>`;
    }
    if (form.form_source === 'URL' && _isSafeHttpUrl(form.form_source_url)) {
        return '<span class="forms-result-card__source-type" data-source="link">Online form</span>';
    }
    return '<span class="forms-result-card__source-type" data-source="none">No source</span>';
}

/**
 * US-009: Render the single per-card source action button next to the form
 * title. Exactly one button is emitted per card, chosen by `form_source`:
 *   - `form_source === 'Download'` with a file  → "Download" button.
 *   - `form_source === 'URL'` with a valid http(s) link → "Form Link" anchor.
 *   - anything else / missing target / unsafe scheme → disabled "No Attachment".
 *
 * The Download button reuses the shared `downloadFormAttachment` control so the
 * endpoint, headers, and file-selection logic never diverge from the View
 * Details popup (AC2 / BR-01). The Form Link opens in a new tab hardened with
 * `rel="noopener noreferrer"` and only follows http/https URLs (AC8 / BR-05).
 *
 * @param {object} form  Form object from the API.
 * @returns {string} HTML string for a single action button.
 */
function _renderFormSourceButton(form) {
    const id = _escapeAttribute(form.id);
    const formLabel = getFormNumberDisplay(form) || form.title || 'form';

    if (form.form_source === 'Download') {
        if (form.form_attachment_url) {
            const filename = _escapeAttribute(form.form_attachment_filename || '');
            return `<button type="button" class="btn btn-sm btn-outline-primary forms-list__source-btn"
                data-action="download-form-file" data-form-id="${id}"
                data-form-filename="${filename}"
                aria-label="Download form ${_escapeAttribute(formLabel)}">
                <i class="fas fa-download" aria-hidden="true"></i> Download</button>`;
        }
        return _renderNoAttachmentButton(formLabel, 'No file available');
    }

    if (form.form_source === 'URL') {
        if (_isSafeHttpUrl(form.form_source_url)) {
            const href = _escapeAttribute(form.form_source_url.trim());
            return `<a class="btn btn-sm btn-outline-primary forms-list__source-btn"
                href="${href}" target="_blank" rel="noopener noreferrer"
                data-action="open-form-link"
                aria-label="Open form link for ${_escapeAttribute(formLabel)}">
                <i class="fas fa-external-link-alt" aria-hidden="true"></i> Form Link</a>`;
        }
        return _renderNoAttachmentButton(formLabel, 'No link available');
    }

    return _renderNoAttachmentButton(formLabel, 'No file or URL attached');
}

/** US-009: Render the disabled "No Attachment" button with an accessible tooltip. */
function _renderNoAttachmentButton(formLabel, tooltip) {
    const safeTooltip = _escapeAttribute(tooltip);
    const safeFormLabel = _escapeAttribute(formLabel);
    return `<button type="button" class="btn btn-sm btn-outline-secondary forms-list__source-btn"
        disabled title="${safeTooltip}"
        aria-label="No attachment for form ${safeFormLabel} — ${safeTooltip}">
        <i class="fas fa-ban" aria-hidden="true"></i> No Attachment</button>`;
}

/**
 * US-009 (AC8 / BR-05): return true only for absolute http/https URLs. Values
 * with any other scheme (javascript:, data:, file:, …) or relative/malformed
 * values are rejected and treated as "No link available".
 * @param {string} value  Candidate URL.
 * @returns {boolean}
 */
function _isSafeHttpUrl(value) {
    if (typeof value !== 'string' || !value.trim()) return false;
    try {
        const url = new URL(value.trim());
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch (_error) {
        return false;
    }
}

/** Reset to page 0 and reload — called by the search button and Enter key. */
export function searchForms() {
    _currentSkip = 0;
    _dismissSearchSuggestions();
    loadForms();
}


/** Reset to page 0 and reload — called whenever any filter dropdown changes. */
export function applyFilters() {
    _currentSkip = 0;
    loadForms();
}

// ── Private helpers ───────────────────────────────────────────────────────────

function _initListViewEvents() {
    // Delegated click handler for all rendered form cards
    const formsList = document.getElementById('formsList');
    if (formsList) {
        formsList.addEventListener('click', _handleFormsListClick);
    }

    // Delegated click handler for search autocomplete suggestions
    const suggestions = document.getElementById('searchSuggestions');
    if (suggestions) {
        suggestions.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-action="select-suggestion"]');
            if (btn) _selectSearchSuggestion(btn.dataset.value);
        });
    }

    document.getElementById('sortOrder')?.addEventListener('change', applyFilters);
    document.getElementById('pageSizeSelect')?.addEventListener('change', _onPageSizeChange);
    document.getElementById('prevPageBtn')?.addEventListener('click', _goToPreviousPage);
    document.getElementById('nextPageBtn')?.addEventListener('click', _goToNextPage);
    document.querySelector('.forms-density-control')?.addEventListener('click', event => {
        const button = event.target.closest('[data-density-view]');
        if (button) _selectResultsLayout(button.dataset.densityView);
    });
    _initListSearchAutocomplete();
    _initFiltersMenu();

    // Access request button (in requestAccessPanel above the list)
    document.getElementById('requestAccessBtn')?.addEventListener('click', async () => {
        const { submitAccessRequest } = await import('./admin/access-requests.js');
        submitAccessRequest();
    });

}

async function _getResultsLayoutStorageKey() {
    const userId = getCurrentUser()?.id;
    if (typeof userId !== 'string' || !userId || !globalThis.crypto?.subtle) return null;
    try {
        const input = new TextEncoder().encode(userId.slice(0, MAX_FORM_ID_LENGTH));
        const digest = await crypto.subtle.digest('SHA-256', input);
        const digestHex = Array.from(new Uint8Array(digest), byte =>
            byte.toString(16).padStart(2, '0')
        ).join('');
        return `${RESULTS_LAYOUT_STORAGE_PREFIX}${digestHex}`;
    } catch (_error) {
        return null;
    }
}

async function _restoreResultsLayoutPreference() {
    const generation = ++_layoutPreferenceGeneration;
    let layout = DEFAULT_RESULTS_LAYOUT;
    try {
        const storageKey = await _getResultsLayoutStorageKey();
        if (generation !== _layoutPreferenceGeneration) return;
        const storedLayout = storageKey ? localStorage.getItem(storageKey) : null;
        if (RESULTS_LAYOUTS.has(storedLayout)) layout = storedLayout;
    } catch (_error) {
        layout = DEFAULT_RESULTS_LAYOUT;
    }
    if (generation === _layoutPreferenceGeneration) _applyResultsLayout(layout);
}

async function _selectResultsLayout(layout) {
    if (!RESULTS_LAYOUTS.has(layout)) return;
    const generation = ++_layoutPreferenceGeneration;
    _applyResultsLayout(layout);
    try {
        const storageKey = await _getResultsLayoutStorageKey();
        if (generation === _layoutPreferenceGeneration && storageKey) {
            localStorage.setItem(storageKey, layout);
        }
    } catch (_error) {
        // The selected layout remains usable when durable storage is unavailable.
    }
}

function _applyResultsLayout(layout) {
    _currentResultsLayout = RESULTS_LAYOUTS.has(layout) ? layout : DEFAULT_RESULTS_LAYOUT;
    const list = document.getElementById('formsList');
    if (list) list.dataset.layout = _currentResultsLayout;
    document.querySelectorAll('[data-density-view]').forEach(button => {
        const isSelected = button.dataset.densityView === _currentResultsLayout;
        button.classList.toggle('is-active', isSelected);
        button.setAttribute('aria-pressed', String(isSelected));
    });
}

function _handleFormsListClick(e) {
    const viewBtn = e.target.closest('[data-action="view-form"]');
    const deleteBtn = e.target.closest('[data-action="delete-form"]');
    const navBtn = e.target.closest('[data-action="navigate"]');
    const submitBtn = e.target.closest('[data-action="submit-form"]');
    const archiveBtn = e.target.closest('[data-action="archive-form"]');
    const restoreBtn = e.target.closest('[data-action="restore-form"]');
    const downloadBtn = e.target.closest('[data-action="download-form-file"]');

    if (viewBtn) {
        _viewForm(viewBtn.dataset.formId, viewBtn);
    } else if (downloadBtn) {
        // US-009 — reuse the shared internal Download control (AC2 / BR-01).
        downloadFormAttachment(downloadBtn.dataset.formId, downloadBtn.dataset.formFilename);
    } else if (deleteBtn) {
        _deleteForm(deleteBtn.dataset.formId, deleteBtn.dataset.formTitle);
    } else if (submitBtn) {
        _submitForm(submitBtn.dataset.formId, submitBtn.dataset.formTitle);
    } else if (archiveBtn) {
        _archiveFormFromList(archiveBtn.dataset.formId, archiveBtn.dataset.formTitle);
    } else if (restoreBtn) {
        _restoreFormFromList(restoreBtn.dataset.formId, restoreBtn.dataset.formTitle);
    } else if (navBtn) {
        _navigate(navBtn.dataset.route);
    }
}

function _updatePaginationControls(total) {
    const paginationContainer = document.getElementById('paginationContainer');
    const summary = document.getElementById('paginationSummary');
    const prevBtn = document.getElementById('prevPageBtn');
    const nextBtn = document.getElementById('nextPageBtn');

    if (!paginationContainer || !summary || !prevBtn || !nextBtn) return;

    const start = total === 0 ? 0 : _currentSkip + 1;
    const end = total === 0 ? 0 : Math.min(_currentSkip + _currentLimit, total);

    _updateResultsSummary(total);
    summary.textContent = `Showing ${start}-${end} of ${total}`;
    paginationContainer.hidden = false;
    paginationContainer.removeAttribute('aria-busy');

    prevBtn.disabled = _currentSkip <= 0;
    nextBtn.disabled = _currentSkip + _currentLimit >= total;
}

function _setPaginationPending() {
    const paginationContainer = document.getElementById('paginationContainer');
    const prevBtn = document.getElementById('prevPageBtn');
    const nextBtn = document.getElementById('nextPageBtn');
    paginationContainer?.setAttribute('aria-busy', 'true');
    if (prevBtn) prevBtn.disabled = true;
    if (nextBtn) nextBtn.disabled = true;
}

function _updateResultsSummary(total) {
    const summary = document.getElementById('resultsSummary');
    if (!summary) return;
    const strong = document.createElement('strong');
    strong.textContent = `${total} ${total === 1 ? 'form' : 'forms'}`;
    summary.replaceChildren(strong, document.createTextNode(' available'));
}

function _onPageSizeChange() {
    const pageSizeSelect = document.getElementById('pageSizeSelect');
    if (pageSizeSelect) {
        const requestedLimit = Number.parseInt(pageSizeSelect.value, 10);
        _currentLimit = ALLOWED_PAGE_SIZES.has(requestedLimit) ? requestedLimit : 24;
        pageSizeSelect.value = String(_currentLimit);
    }
    _currentSkip = 0;
    loadForms();
}

function _goToPreviousPage() {
    if (_isFormsRequestPending || _currentSkip <= 0) return;
    loadForms(Math.max(0, _currentSkip - _currentLimit));
}

function _goToNextPage() {
    if (_isFormsRequestPending || _currentSkip + _currentLimit >= _lastListTotal) return;
    loadForms(_currentSkip + _currentLimit);
}

// ── Search autocomplete ───────────────────────────────────────────────────────

function _initListSearchAutocomplete() {
    const input = document.getElementById('searchInput');
    const suggestions = document.getElementById('searchSuggestions');
    if (!input || !suggestions) return;

    const clearSearchButton = document.getElementById('clearSearchButton');
    clearSearchButton?.addEventListener('click', () => {
        input.value = '';
        _dismissSearchSuggestions();
        clearSearchButton.hidden = true;
        _currentSkip = 0;
        input.focus();
        loadForms();
    });

    input.addEventListener('input', () => {
        clearTimeout(_autocompleteDebounceTimer);
        _autocompleteRequestController?.abort();
        const query = input.value.trim();
        if (clearSearchButton) clearSearchButton.hidden = query.length === 0;
        if (query.length < 2) {
            _dismissSearchSuggestions();
            return;
        }
        _autocompleteDebounceTimer = setTimeout(() => _fetchSearchSuggestions(query), 250);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            searchForms();
        } else if (e.key === 'ArrowDown') {
            const firstSuggestion = suggestions.querySelector('button');
            if (firstSuggestion) {
                e.preventDefault();
                firstSuggestion.focus();
            }
        } else if (e.key === 'Escape') {
            _dismissSearchSuggestions();
        } else if (e.key === 'Tab') {
            _dismissSearchSuggestions();
        }
    });

    suggestions.addEventListener('keydown', (e) => {
        const buttons = Array.from(suggestions.querySelectorAll('button'));
        const currentIndex = buttons.indexOf(document.activeElement);
        if (e.key === 'ArrowDown' && buttons.length > 0) {
            e.preventDefault();
            buttons[(currentIndex + 1) % buttons.length].focus();
        } else if (e.key === 'ArrowUp' && buttons.length > 0) {
            e.preventDefault();
            buttons[(currentIndex - 1 + buttons.length) % buttons.length].focus();
        } else if (e.key === 'Escape') {
            _dismissSearchSuggestions();
            input.focus();
        }
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('#searchInput') && !e.target.closest('#searchSuggestions')) {
            _dismissSearchSuggestions();
        }
    });

    input.closest('.forms-search-wrap')?.addEventListener('focusout', (event) => {
        const nextTarget = event.relatedTarget;
        if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) {
            _dismissSearchSuggestions();
        }
    });
}

async function _fetchSearchSuggestions(query) {
    const suggestions = document.getElementById('searchSuggestions');
    if (!suggestions) return;
    _autocompleteRequestController?.abort();
    _autocompleteRequestController = new AbortController();
    _autocompleteDebounceTimer = null;
    const { signal } = _autocompleteRequestController;
    try {
        const response = await fetch(
            `${API_BASE}/forms/autocomplete?q=${encodeURIComponent(query)}&max_suggestions=10`,
            { signal }
        );
        if (!response.ok) {
            _setSearchSuggestions([], false);
            return;
        }

        const payload = await response.json();
        if (signal.aborted) return;
        if (document.getElementById('searchInput')?.value.trim() !== query) return;
        if (document.activeElement !== document.getElementById('searchInput')) return;
        const items = Array.isArray(payload.suggestions)
            ? payload.suggestions
                .filter(item => typeof item === 'string' && item.trim())
                .slice(0, 10)
                .map(item => item.slice(0, 300))
            : [];
        _setSearchSuggestions(items, items.length > 0);
    } catch (error) {
        if (!signal.aborted && error.name !== 'AbortError') _setSearchSuggestions([], false);
    }
}

function _dismissSearchSuggestions() {
    if (_isDismissingSearchSuggestions) return;
    _isDismissingSearchSuggestions = true;
    try {
        clearTimeout(_autocompleteDebounceTimer);
        _autocompleteDebounceTimer = null;
        _autocompleteRequestController?.abort();
        _autocompleteRequestController = null;
        _setSearchSuggestions([], false);
    } finally {
        _isDismissingSearchSuggestions = false;
    }
}

function _setSearchSuggestions(items, visible) {
    const suggestions = document.getElementById('searchSuggestions');
    const input = document.getElementById('searchInput');
    if (!suggestions || !input) return;
    suggestions.replaceChildren();
    for (const value of items) {
        const item = document.createElement('li');
        item.setAttribute('role', 'presentation');
        const button = document.createElement('button');
        button.className = 'dropdown-item';
        button.type = 'button';
        button.setAttribute('role', 'option');
        button.dataset.action = 'select-suggestion';
        button.dataset.value = value.slice(0, 300);
        button.textContent = value.slice(0, 300);
        item.appendChild(button);
        suggestions.appendChild(item);
    }
    suggestions.hidden = !visible;
    suggestions.style.removeProperty('display');
    input.setAttribute('aria-expanded', String(visible));
}

function _selectSearchSuggestion(value) {
    const input = document.getElementById('searchInput');
    if (input) input.value = value;
    _dismissSearchSuggestions();
    input?.focus();
    searchForms();
}

// ── Form card actions ─────────────────────────────────────────────────────────

async function _viewForm(formId, openerElement = null) {
    // FEAT-0027 US-006 / US-008 — delegate to the shared View Details popup
    // component so the same UI is presented from every entry point.
    await openFormViewPopup({
        formId,
        mode: 'default',
        openerElement,
    });
}

async function _deleteForm(formId, formTitle) {
    const title = formTitle || 'this form';
    if (!confirm(`Are you sure you want to delete "${title}"?`)) return;

    try {
        const response = await fetch(`${API_BASE}/forms/${formId}`, {
            method: 'DELETE',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to delete form');
        }

        showAlert('Form deleted successfully', 'success');
        loadForms();
    } catch (error) {
        showAlert('Error deleting form: ' + error.message, 'danger');
    }
}

async function _submitForm(formId, formTitle) {
    const title = formTitle || 'this form';
    if (!confirm(`Submit "${title}" for review?`)) return;

    try {
        const response = await fetch(`${API_BASE}/staff/forms/${formId}/submit`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to submit form');
        }

        showAlert('Form submitted for review successfully.', 'success');
        loadForms();
    } catch (error) {
        showAlert('Error submitting form: ' + error.message, 'danger');
    }
}

async function _archiveFormFromList(formId, formTitle) {
    const title = formTitle || 'this form';
    if (!confirm(`Archive "${title}"? It will no longer be publicly available.`)) return;

    try {
        const response = await fetch(`${API_BASE}/staff/forms/${formId}/archive`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to archive form');
        }

        showAlert('Form archived successfully.', 'success');
        loadForms();
    } catch (error) {
        showAlert('Error archiving form: ' + error.message, 'danger');
    }
}

async function _restoreFormFromList(formId, formTitle) {
    const title = formTitle || 'this form';
    if (!confirm(`Restore "${title}" to published status?`)) return;

    try {
        const response = await fetch(`${API_BASE}/staff/forms/${formId}/restore`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to restore form');
        }

        showAlert('Form restored to published status.', 'success');
        loadForms();
    } catch (error) {
        showAlert('Error restoring form: ' + error.message, 'danger');
    }
}

// ── FEAT-0014 / FEAT-0030: Unified filters menu ───────────────────────────────

/**
 * Returns the filter options visible to the current user.
 * Users who are staff-viewer-only OR have no roles assigned see only
 * "Published" under Workflow State (US-006); backend enforces access control.
 */
function _getVisibleFilterOptions() {
    const user = getCurrentUser();
    if (!user) return [];

    const roles = Array.isArray(user.roles) ? user.roles : [];
    const hasNoRoles = roles.length === 0;

    if (isStaffViewerOnly() || hasNoRoles) {
        return _FILTER_OPTIONS.filter(
            o => o.category !== 'Workflow State' || o.key === 'ws:published'
        );
    }
    return _FILTER_OPTIONS;
}

function _initFiltersMenu() {
    const button = document.getElementById('filtersButton');
    const menu = document.getElementById('filtersMenu');
    const activeFilters = document.getElementById('activeFilters');
    if (!button || !menu || !activeFilters) return;

    button.addEventListener('click', (event) => {
        event.stopPropagation();
        _setFiltersMenuOpen(menu.hidden);
    });
    menu.addEventListener('change', (event) => {
        const checkbox = event.target.closest('input[type="checkbox"][data-filter-key]');
        if (checkbox) _setFilterSelected(checkbox.dataset.filterKey, checkbox.checked);
    });
    activeFilters.addEventListener('click', (event) => {
        const removeButton = event.target.closest('[data-action="remove-active-filter"]');
        if (removeButton) _setFilterSelected(removeButton.dataset.filterKey, false);
    });
    document.addEventListener('click', (event) => {
        if (!event.target.closest('.forms-filter-wrap')) _setFiltersMenuOpen(false);
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !menu.hidden) {
            _setFiltersMenuOpen(false);
            button.focus();
        }
    });
}

function _setFiltersMenuOpen(open) {
    const button = document.getElementById('filtersButton');
    const menu = document.getElementById('filtersMenu');
    if (!button || !menu) return;
    menu.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
}

function _getUnifiedFilterOptions() {
    const businessAreas = getBusinessAreaOptions().map(option => ({
        key: `area:${option.id}`,
        label: option.label,
        category: 'Business Area',
        kind: 'business-area',
        value: option.id,
        exclusive: false,
    }));
    return [...businessAreas, ..._getVisibleFilterOptions().map(option => ({
        ...option,
        kind: 'filter',
        value: option.key,
    }))];
}

function _renderFiltersMenu() {
    const menu = document.getElementById('filtersMenu');
    if (!menu) return;
    menu.replaceChildren();
    const groups = new Map();
    for (const option of _getUnifiedFilterOptions()) {
        if (!groups.has(option.category)) groups.set(option.category, []);
        groups.get(option.category).push(option);
    }

    for (const [category, options] of groups) {
        const group = document.createElement('div');
        group.className = 'forms-filter-group';
        const heading = document.createElement('p');
        heading.className = 'forms-filter-menu__title';
        heading.textContent = category;
        group.appendChild(heading);

        for (const option of options) {
            const label = document.createElement('label');
            label.className = 'forms-filter-option';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.dataset.filterKey = option.key;
            checkbox.checked = option.kind === 'business-area'
                ? _selectedBusinessAreaIds.includes(option.value)
                : _selectedFilterChips.some(chip => chip.key === option.key);
            label.append(checkbox, document.createTextNode(option.label));
            group.appendChild(label);
        }
        menu.appendChild(group);
    }
}

function _setFilterSelected(key, selected) {
    const option = _getUnifiedFilterOptions().find(item => item.key === key);
    if (!option) return;
    if (option.kind === 'business-area') {
        _selectedBusinessAreaIds = selected
            ? [...new Set([..._selectedBusinessAreaIds, option.value])]
            : _selectedBusinessAreaIds.filter(id => id !== option.value);
    } else if (selected) {
        _addFilterOption(option);
    } else {
        _selectedFilterChips = _selectedFilterChips.filter(chip => chip.key !== option.key);
    }
    _renderActiveFilters();
    const checkbox = document.querySelector(
        `#filtersMenu input[data-filter-key="${CSS.escape(option.key)}"]`
    );
    if (checkbox) checkbox.checked = selected;
    if (option.exclusive && selected) {
        _renderFiltersMenu();
        window.requestAnimationFrame(() => {
            document.querySelector(
                `#filtersMenu input[data-filter-key="${CSS.escape(option.key)}"]`
            )?.focus();
        });
    }
    applyFilters();
}

function _addFilterOption(opt) {
    if (opt.exclusive) {
        const existing = _selectedFilterChips.find(
            c => c.category === opt.category && c.key !== opt.key
        );
        if (existing) {
            _selectedFilterChips = _selectedFilterChips.filter(c => c.key !== existing.key);
            showNotification(
                `"${existing.label}" was replaced by "${opt.label}" (only one ${opt.category.toLowerCase()} filter at a time).`,
                'info'
            );
        }
    }

    if (!_selectedFilterChips.find(c => c.key === opt.key)) {
        _selectedFilterChips.push({
            key: opt.key,
            label: opt.label,
            category: opt.category,
        });
    }
}

function _renderActiveFilters() {
    const container = document.getElementById('activeFilters');
    if (!container) return;
    container.replaceChildren();
    const selectedAreas = getBusinessAreaOptions()
        .filter(option => _selectedBusinessAreaIds.includes(option.id))
        .map(option => ({ key: `area:${option.id}`, label: option.label }));
    const selected = [...selectedAreas, ..._selectedFilterChips];
    for (const filter of selected) {
        const chip = document.createElement('span');
        chip.className = 'forms-filter-chip';
        chip.appendChild(document.createTextNode(filter.label));
        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.dataset.action = 'remove-active-filter';
        removeButton.dataset.filterKey = filter.key;
        removeButton.setAttribute('aria-label', `Remove ${filter.label} filter`);
        removeButton.textContent = 'X';
        chip.appendChild(removeButton);
        container.appendChild(chip);
    }
    container.hidden = selected.length === 0;
}

