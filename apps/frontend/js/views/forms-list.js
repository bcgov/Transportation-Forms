// frontend/js/views/forms-list.js
// Manages the forms list/search/pagination view.
import { API_BASE, ROUTES } from '../constants.js';
import {
    escapeHtml,
    formatDateTime,
    showAlert,
    showSpinner,
    getErrorDetail,
    getFormNumberDisplay,
    showNotification,
} from '../utils.js';
import {
    getSelectedFilters,
    initFilterBusinessAreaCombobox,
    loadBusinessAreas,
} from './business-areas.js';
import { hasPermission, getAuthToken, isAdminUser } from '../auth.js';
import { getCurrentUser } from '../state.js';

// ── Module-private pagination state ──────────────────────────────────────────
let _currentSkip = 0;
let _currentLimit = 25;
let _lastListTotal = 0;

// ── Module-private setup flag & navigate callback ─────────────────────────────
let _initialized = false;
let _navigate = null;

// ── Filter combobox state ─────────────────────────────────────────────────────
let _selectedFilterChips = [];   // array of { key, label, category }

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
export function showFormsListView(navigateFn) {
    _navigate = navigateFn ?? _defaultNavigate;

    document.getElementById('listView').style.display = 'block';
    document.getElementById('pageTitle').textContent = 'Manage Forms - BC Gov';

    if (!_initialized) {
        _initListViewEvents();
        _initialized = true;
    }

    loadBusinessAreas();
    loadForms();
}

/** Load (or reload) the forms list from the API, applying current filters & pagination. */
export async function loadForms() {
    try {
        showSpinner('#formsList', true);

        const params = new URLSearchParams();
        params.set('skip', String(_currentSkip));
        params.set('limit', String(_currentLimit));

        const query = document.getElementById('searchInput')?.value.trim() ?? '';
        if (query) params.set('q', query);

        const selectedFilters = getSelectedFilters();
        selectedFilters.forEach(id => params.append('business_area_ids', id));

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

        const response = await fetch(`${API_BASE}/forms?${params.toString()}`);

        if (!response.ok) {
            const detail = await getErrorDetail(response, `HTTP ${response.status}`);
            throw new Error(detail);
        }

        const data = await response.json();
        _lastListTotal = data.total || 0;
        displayForms(data.items || []);
        _updatePaginationControls(_lastListTotal);
    } catch (error) {
        showAlert('Error loading forms: ' + error.message, 'danger');
        console.error(error);
        _updatePaginationControls(0);
    }
}

/** Render the given array of form objects into #formsList. */
export function displayForms(forms) {
    const container = document.getElementById('formsList');
    if (!container) return;

    if (forms.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-inbox"></i>
                <h4>No Forms Found</h4>
                <p>Create your first form to get started.</p>
                <button class="btn btn-bc-primary" data-action="navigate" data-route="/create">
                    Add New Form
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = forms.map(form => `
        <div class="card">
            <div class="card-body">
                <div class="row">
                    <div class="col-md-8">
                        <h5 class="card-title">
                            ${escapeHtml(getFormNumberDisplay(form))} - ${escapeHtml(form.title)}
                        </h5>
                        <p class="card-text text-muted">${escapeHtml(form.description || 'No description')}</p>
                        <div>
                            <span class="badge ${form.is_public ? 'bg-success' : 'bg-warning'}">
                                ${form.is_public ? 'Public' : 'Private'}
                            </span>
                            <span class="badge bg-info">${escapeHtml(form.status)}</span>
                            ${form.file_type ? `<span class="badge bg-secondary">${escapeHtml(form.file_type)}</span>` : ''}
                        </div>
                    </div>
                    <div class="col-md-4 text-end">
                        <small class="text-muted d-block">
                            Created: ${new Date(form.created_at).toLocaleDateString()}
                        </small>
                        <div class="mt-2">
                            ${_renderFormActionButtons(form)}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `).join('');
}

/**
 * FEAT-0013: Render state-aware, permission-gated action buttons for a form card.
 * @param {object} form  Form object from the API (includes status, created_by, id).
 * @returns {string} HTML string of buttons.
 */
function _renderFormActionButtons(form) {
    const buttons = [];
    const id = escapeHtml(form.id);
    const status = form.status;
    const user = getCurrentUser();
    const userId = user?.id || '';
    const isOwner = form.created_by?.id === userId;

    // View — all states, form:read
    if (hasPermission('form:read')) {
        buttons.push(`<button class="btn btn-sm btn-outline-primary"
            data-action="view-form" data-form-id="${id}">
            <i class="fas fa-eye"></i> View</button>`);
    }

    // Edit — draft + published, form:edit
    if ((status === 'draft' || status === 'published') && hasPermission('form:edit')) {
        buttons.push(`<button class="btn btn-sm btn-outline-warning"
            data-action="navigate" data-route="/edit/${id}">
            <i class="fas fa-edit"></i> Edit</button>`);
    }

    // Submit — draft only, creator only, form:submit_for_review
    if (status === 'draft' && isOwner && hasPermission('form:submit_for_review')) {
        buttons.push(`<button class="btn btn-sm btn-outline-success"
            data-action="submit-form" data-form-id="${id}"
            data-form-title="${escapeHtml(form.title)}">
            <i class="fas fa-paper-plane"></i> Submit</button>`);
    }

    // Archive — published only, form:archive
    if (status === 'published' && hasPermission('form:archive')) {
        buttons.push(`<button class="btn btn-sm btn-outline-secondary"
            data-action="archive-form" data-form-id="${id}"
            data-form-title="${escapeHtml(form.title)}">
            <i class="fas fa-archive"></i> Archive</button>`);
    }

    // Restore — archived only, form:approve
    if (status === 'archived' && hasPermission('form:approve')) {
        buttons.push(`<button class="btn btn-sm btn-outline-info"
            data-action="restore-form" data-form-id="${id}"
            data-form-title="${escapeHtml(form.title)}">
            <i class="fas fa-undo"></i> Restore</button>`);
    }

    // Delete — draft only, form:delete, owner or admin (matches backend enforcement)
    if (status === 'draft' && hasPermission('form:delete') && (isOwner || isAdminUser())) {
        buttons.push(`<button class="btn btn-sm btn-outline-danger"
            data-action="delete-form" data-form-id="${id}"
            data-form-title="${escapeHtml(form.title)}">
            <i class="fas fa-trash"></i> Delete</button>`);
    }

    return buttons.join('\n');
}

/** Reset to page 0 and reload — called by the search button and Enter key. */
export function searchForms() {
    _currentSkip = 0;
    const suggestions = document.getElementById('searchSuggestions');
    if (suggestions) suggestions.style.display = 'none';
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

    // Sort dropdown
    document.getElementById('sortOrder')?.addEventListener('change', applyFilters);

    // Page size selector
    document.getElementById('pageSizeSelect')?.addEventListener('change', _onPageSizeChange);

    // Prev / Next pagination buttons
    document.getElementById('prevPageBtn')?.addEventListener('click', _goToPreviousPage);
    document.getElementById('nextPageBtn')?.addEventListener('click', _goToNextPage);

    // Search autocomplete
    _initListSearchAutocomplete();

    // Search button
    document.querySelector('[data-action="search-forms"]')?.addEventListener('click', searchForms);

    // Access request button (in requestAccessPanel above the list)
    document.getElementById('requestAccessBtn')?.addEventListener('click', async () => {
        const { submitAccessRequest } = await import('./admin/access-requests.js');
        submitAccessRequest();
    });

    // Filter business area combobox — pass applyFilters as the change callback
    initFilterBusinessAreaCombobox(applyFilters);

    // FEAT-0014: consolidated filter combobox
    _initFilterCombobox();
}

function _handleFormsListClick(e) {
    const viewBtn = e.target.closest('[data-action="view-form"]');
    const deleteBtn = e.target.closest('[data-action="delete-form"]');
    const navBtn = e.target.closest('[data-action="navigate"]');
    const submitBtn = e.target.closest('[data-action="submit-form"]');
    const archiveBtn = e.target.closest('[data-action="archive-form"]');
    const restoreBtn = e.target.closest('[data-action="restore-form"]');

    if (viewBtn) {
        _viewForm(viewBtn.dataset.formId);
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

    summary.textContent = `Showing ${start}–${end} of ${total}`;
    paginationContainer.style.display = 'flex';

    prevBtn.disabled = _currentSkip <= 0;
    nextBtn.disabled = _currentSkip + _currentLimit >= total;
}

function _onPageSizeChange() {
    const pageSizeSelect = document.getElementById('pageSizeSelect');
    if (pageSizeSelect) {
        _currentLimit = parseInt(pageSizeSelect.value, 10);
    }
    _currentSkip = 0;
    loadForms();
}

function _goToPreviousPage() {
    if (_currentSkip <= 0) return;
    _currentSkip = Math.max(0, _currentSkip - _currentLimit);
    loadForms();
}

function _goToNextPage() {
    if (_currentSkip + _currentLimit >= _lastListTotal) return;
    _currentSkip += _currentLimit;
    loadForms();
}

// ── Search autocomplete ───────────────────────────────────────────────────────

function _initListSearchAutocomplete() {
    const input = document.getElementById('searchInput');
    const suggestions = document.getElementById('searchSuggestions');
    if (!input || !suggestions) return;

    let debounceTimer = null;

    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const query = input.value.trim();
        if (query.length < 2) {
            suggestions.style.display = 'none';
            suggestions.innerHTML = '';
            return;
        }
        debounceTimer = setTimeout(() => _fetchSearchSuggestions(query), 250);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            searchForms();
        } else if (e.key === 'Escape') {
            suggestions.style.display = 'none';
        }
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('#searchInput') && !e.target.closest('#searchSuggestions')) {
            suggestions.style.display = 'none';
        }
    });
}

async function _fetchSearchSuggestions(query) {
    const suggestions = document.getElementById('searchSuggestions');
    if (!suggestions) return;
    try {
        const response = await fetch(
            `${API_BASE}/forms/autocomplete?q=${encodeURIComponent(query)}&max_suggestions=10`
        );
        if (!response.ok) {
            suggestions.style.display = 'none';
            return;
        }

        const payload = await response.json();
        const items = payload.suggestions || [];

        if (items.length === 0) {
            suggestions.style.display = 'none';
            suggestions.innerHTML = '';
            return;
        }

        suggestions.innerHTML = items.map(item => `
            <li>
                <button class="dropdown-item" type="button"
                        data-action="select-suggestion"
                        data-value="${escapeHtml(item)}">
                    ${escapeHtml(item)}
                </button>
            </li>
        `).join('');
        suggestions.style.display = 'block';
    } catch (_error) {
        suggestions.style.display = 'none';
    }
}

function _selectSearchSuggestion(value) {
    const input = document.getElementById('searchInput');
    const suggestions = document.getElementById('searchSuggestions');
    if (input) input.value = value;
    if (suggestions) suggestions.style.display = 'none';
    searchForms();
}

// ── Form card actions ─────────────────────────────────────────────────────────

async function _viewForm(formId) {
    try {
        const response = await fetch(`${API_BASE}/forms/${formId}`);
        if (!response.ok) throw new Error('Form not found');
        const form = await response.json();

        document.getElementById('formModalTitle').textContent = form.title;
        document.getElementById('formModalBody').innerHTML = `
            <dl class="row">
                <dt class="col-sm-3">Title:</dt>
                <dd class="col-sm-9">${escapeHtml(form.title)}</dd>

                <dt class="col-sm-3">Form Number:</dt>
                <dd class="col-sm-9">${escapeHtml(getFormNumberDisplay(form))}</dd>

                <dt class="col-sm-3">Description:</dt>
                <dd class="col-sm-9">${escapeHtml(form.description || 'N/A')}</dd>

                <dt class="col-sm-3">Status:</dt>
                <dd class="col-sm-9"><span class="badge bg-info">${escapeHtml(form.status)}</span></dd>

                <dt class="col-sm-3">Public:</dt>
                <dd class="col-sm-9">${form.is_public ? 'Yes' : 'No'}</dd>

                <dt class="col-sm-3">Does this form collect personal info?</dt>
                <dd class="col-sm-9">${escapeHtml(form.collects_personal_info || 'No')}</dd>

                <dt class="col-sm-3">Form Source:</dt>
                <dd class="col-sm-9">${escapeHtml(form.form_source || 'N/A')}</dd>

                ${form.form_source === 'URL' ? `
                <dt class="col-sm-3">Source URL:</dt>
                <dd class="col-sm-9">
                    <a href="${escapeHtml(form.form_source_url)}" target="_blank" rel="noopener noreferrer">
                        ${escapeHtml(form.form_source_url)}
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
                    ${form.keywords?.length
                        ? form.keywords.map(k => escapeHtml(k)).join(', ')
                        : 'None'}
                </dd>

                <dt class="col-sm-3">Created:</dt>
                <dd class="col-sm-9">${formatDateTime(form.created_at)}</dd>

                <dt class="col-sm-3">Updated:</dt>
                <dd class="col-sm-9">${formatDateTime(form.updated_at)}</dd>
            </dl>
        `;

        // Wire download-attachment button (uses fetch to get a pre-signed URL,
        // avoiding the problem of navigating to a raw S3 object key).
        const downloadBtn = document.getElementById('formModalBody')
            ?.querySelector('[data-action="download-attachment"]');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', () => {
                _downloadFormAttachment(downloadBtn.dataset.formId, form.form_attachment_filename);
            }, { once: true });
        }

        // eslint-disable-next-line no-undef
        new bootstrap.Modal(document.getElementById('formModal')).show();
    } catch (error) {
        showAlert('Error loading form: ' + error.message, 'danger');
    }
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

// ── FEAT-0014: Consolidated filter combobox ───────────────────────────────────

/**
 * Returns the filter options visible to the current user.
 * Users who are staff-viewer-only OR have no roles assigned see only
 * "Published" under Workflow State (US-006); backend enforces access control.
 */
function _getVisibleFilterOptions() {
    const user = getCurrentUser();
    if (!user) return _FILTER_OPTIONS; // auth not yet loaded; backend enforces access control

    const roles = Array.isArray(user.roles) ? user.roles.map(r => String(r).toLowerCase()) : [];
    const isStaffViewerOnly = roles.length === 1 && roles[0] === 'staff_viewer';
    const hasNoRoles = roles.length === 0;

    if (isStaffViewerOnly || hasNoRoles) {
        return _FILTER_OPTIONS.filter(
            o => o.category !== 'Workflow State' || o.key === 'ws:published'
        );
    }
    return _FILTER_OPTIONS;
}

function _initFilterCombobox() {
    const input = document.getElementById('filterComboboxInput');
    const dropdown = document.getElementById('filterComboboxDropdown');
    if (!input || !dropdown) return;

    input.addEventListener('input', () => {
        _renderFilterDropdown(input.value.trim().toLowerCase());
        _setFilterDropdownVisible(true);
    });

    input.addEventListener('focus', () => {
        _renderFilterDropdown(input.value.trim().toLowerCase());
        _setFilterDropdownVisible(true);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            const firstItem = dropdown.querySelector('[role="option"]');
            if (firstItem) firstItem.focus();
        } else if (e.key === 'Escape' || e.key === 'Tab') {
            _closeFilterDropdown();
        }
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('#filterCombobox')) {
            _closeFilterDropdown();
        }
    });

    // Delegated chip removal
    const chipContainer = document.getElementById('selectedFilterChips');
    if (chipContainer) {
        chipContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-action="remove-filter-chip"]');
            if (btn) _removeFilterChip(btn.dataset.key);
        });
    }
}

function _renderFilterDropdown(query) {
    const dropdown = document.getElementById('filterComboboxDropdown');
    if (!dropdown) return;
    dropdown.innerHTML = '';

    const visible = _getVisibleFilterOptions();
    const selectedKeys = new Set(_selectedFilterChips.map(c => c.key));

    // Group by category, preserving insertion order
    const groups = new Map();
    for (const opt of visible) {
        if (selectedKeys.has(opt.key)) continue;
        if (query && !opt.label.toLowerCase().includes(query)) continue;
        if (!groups.has(opt.category)) groups.set(opt.category, []);
        groups.get(opt.category).push(opt);
    }

    if (groups.size === 0) {
        const li = document.createElement('li');
        li.className = 'dropdown-item disabled text-muted py-2';
        li.setAttribute('role', 'presentation');
        li.setAttribute('aria-disabled', 'true');
        li.textContent = query ? 'No matching filters' : 'No more filters available';
        dropdown.appendChild(li);
        return;
    }

    for (const [category, options] of groups) {
        // Non-selectable category header
        const header = document.createElement('li');
        header.className = 'dropdown-header fw-bold text-uppercase small text-muted px-3 pt-2 pb-1';
        header.textContent = category;
        header.setAttribute('role', 'presentation');
        dropdown.appendChild(header);

        for (const opt of options) {
            const li = document.createElement('li');
            li.className = 'dropdown-item py-2';
            li.style.cursor = 'pointer';
            li.setAttribute('role', 'option');
            li.setAttribute('tabindex', '-1');
            li.textContent = opt.label;

            li.addEventListener('mousedown', (e) => e.preventDefault());
            li.addEventListener('click', () => _addFilterChip(opt));
            li.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    _addFilterChip(opt);
                } else if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    let next = li.nextElementSibling;
                    while (next && next.getAttribute('role') !== 'option') next = next.nextElementSibling;
                    if (next) next.focus();
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    let prev = li.previousElementSibling;
                    while (prev && prev.getAttribute('role') !== 'option') prev = prev.previousElementSibling;
                    if (prev) prev.focus();
                    else document.getElementById('filterComboboxInput')?.focus();
                } else if (e.key === 'Escape' || e.key === 'Tab') {
                    _closeFilterDropdown();
                }
            });
            dropdown.appendChild(li);
        }
    }
}

function _addFilterChip(opt) {
    // Enforce mutual exclusivity for exclusive categories
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

    const inputEl = document.getElementById('filterComboboxInput');
    if (inputEl) inputEl.value = '';
    _renderFilterChips();
    _renderFilterDropdown('');
    _closeFilterDropdown();
    applyFilters();
}

function _removeFilterChip(key) {
    _selectedFilterChips = _selectedFilterChips.filter(c => c.key !== key);
    _renderFilterChips();
    applyFilters();
}

function _renderFilterChips() {
    const container = document.getElementById('selectedFilterChips');
    if (!container) return;

    container.innerHTML = _selectedFilterChips.map(chip => `
        <span class="badge bg-primary me-1 mb-1">
            ${escapeHtml(chip.label)}
            <button type="button" class="btn-close btn-close-white btn-sm ms-1" aria-label="Remove"
                data-action="remove-filter-chip" data-key="${escapeHtml(chip.key)}"
                style="font-size: 0.55rem;"></button>
        </span>
    `).join('');
}

function _setFilterDropdownVisible(visible) {
    const input = document.getElementById('filterComboboxInput');
    const dropdown = document.getElementById('filterComboboxDropdown');
    if (input) input.setAttribute('aria-expanded', String(visible));
    if (dropdown) dropdown.style.display = visible ? 'block' : 'none';
}

function _closeFilterDropdown() {
    _setFilterDropdownVisible(false);
}

/**
 * Stream the form's attachment from the admin API into a Blob and trigger a
 * download via a hidden anchor.
 *
 * SECURITY: this endpoint streams the file bytes directly from the backend;
 * no S3 URL, bucket name, object key, or pre-signed URL is exposed to the
 * browser at any point.  The Authorization header is automatically attached
 * by the API fetch interceptor for any URL under `/api/v1/`.
 *
 * The server sets `Content-Disposition: attachment; filename="…"`.  We
 * parse the filename from the header when available so the saved file
 * matches the original upload, and fall back to the supplied label.
 */
async function _downloadFormAttachment(formId, fallbackFilename) {
    let objectUrl = null;
    try {
        const response = await fetch(`${API_BASE}/forms/${formId}/file`, {
            headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!response.ok) {
            // Try to surface RFC-7807 / detail message if present without
            // leaking binary payloads back to the user.
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

        // Prefer the server-supplied filename from Content-Disposition.
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
        // Always release the object URL to avoid leaking blob memory.
        if (objectUrl) {
            // Defer revoke until after the browser has started the download.
            setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
        }
    }
}
