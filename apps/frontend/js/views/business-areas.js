// frontend/js/views/business-areas.js
// Manages the business area combobox (form modal) and filter tags UI (list view).
import { API_BASE } from '../constants.js';
import { escapeHtml, showAlert } from '../utils.js';

// ── Module-private state ──────────────────────────────────────────────────────
let _businessAreaOptions = [];
let _selectedBusinessAreaFilters = [];

// ── State accessors ───────────────────────────────────────────────────────────
export function getBusinessAreaOptions() {
    return [..._businessAreaOptions];
}

export function getSelectedFilters() {
    return [..._selectedBusinessAreaFilters];
}

export function setSelectedFilters(arr) {
    _selectedBusinessAreaFilters = arr ? [...arr] : [];
}

// ── API ───────────────────────────────────────────────────────────────────────

/**
 * Fetches /api/v1/business-areas and populates _businessAreaOptions.
 * Restores any previously confirmed selection in the form combobox.
 */
export async function loadBusinessAreas() {
    const previousId = document.getElementById('businessAreaValue')?.value ?? '';
    const inputEl = document.getElementById('businessAreaInput');
    const valueEl = document.getElementById('businessAreaValue');

    if (inputEl) inputEl.value = '';
    if (valueEl) valueEl.value = '';
    _businessAreaOptions = [];

    try {
        const response = await fetch(`${API_BASE}/business-areas`);
        if (!response.ok) throw new Error('Failed to load business areas');
        const areas = await response.json();
        _businessAreaOptions = areas.map(area => ({
            id: area.id,
            label: area.name + (area.description ? ` \u2013 ${area.description}` : ''),
        }));

        // Restore previously confirmed selection if it still exists in the list
        if (previousId) {
            const found = _businessAreaOptions.find(o => o.id === previousId);
            if (found) {
                if (inputEl) inputEl.value = found.label;
                if (valueEl) valueEl.value = found.id;
            }
        }

        renderSelectedBusinessAreaFilters();
        const filterInput = document.getElementById('filterBusinessAreaInput');
        if (filterInput) {
            renderFilterBusinessAreaDropdown(filterInput.value.toLowerCase());
        }
    } catch (error) {
        console.error('Business areas load error:', error);
    }
}

// ── Form combobox ─────────────────────────────────────────────────────────────

/**
 * Wires up the form-modal business area combobox.
 * Defaults match the element IDs in index.html.
 */
export function initBusinessAreaCombobox(
    inputId = 'businessAreaInput',
    dropdownId = 'businessAreaDropdown',
    hiddenId = 'businessAreaValue',
    comboboxId = 'businessAreaCombobox',
) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    if (!input || !dropdown) return;

    input.addEventListener('input', () => {
        // Clear confirmed hidden value when the visible text no longer matches
        const hiddenEl = document.getElementById(hiddenId);
        const confirmedLabel = _businessAreaOptions.find(o => o.id === hiddenEl?.value);
        if (!confirmedLabel || confirmedLabel.label !== input.value) {
            if (hiddenEl) hiddenEl.value = '';
        }
        renderBusinessAreaDropdown(input.value.toLowerCase(), inputId, dropdownId, hiddenId);
        _setBusinessAreaDropdownVisible(true, inputId, dropdownId);
    });

    input.addEventListener('focus', () => {
        renderBusinessAreaDropdown(input.value.toLowerCase(), inputId, dropdownId, hiddenId);
        _setBusinessAreaDropdownVisible(true, inputId, dropdownId);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            const firstItem = dropdown.querySelector('[role="option"]');
            if (firstItem) firstItem.focus();
        } else if (e.key === 'Escape') {
            closeBusinessAreaDropdown(inputId, dropdownId);
        } else if (e.key === 'Tab') {
            closeBusinessAreaDropdown(inputId, dropdownId);
        }
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest(`#${comboboxId}`)) {
            closeBusinessAreaDropdown(inputId, dropdownId);
        }
    });
}

export function renderBusinessAreaDropdown(
    query,
    inputId = 'businessAreaInput',
    dropdownId = 'businessAreaDropdown',
    hiddenId = 'businessAreaValue',
) {
    const dropdown = document.getElementById(dropdownId);
    if (!dropdown) return;

    const filtered = query
        ? _businessAreaOptions.filter(o => o.label.toLowerCase().includes(query))
        : _businessAreaOptions;

    dropdown.innerHTML = '';
    if (filtered.length === 0) {
        const li = document.createElement('li');
        li.className = 'dropdown-item disabled text-muted py-2';
        li.setAttribute('aria-disabled', 'true');
        li.textContent = query ? 'No matching business areas' : 'No business areas available';
        dropdown.appendChild(li);
        return;
    }

    filtered.forEach(option => {
        const li = document.createElement('li');
        li.className = 'dropdown-item py-2';
        li.style.cursor = 'pointer';
        li.setAttribute('role', 'option');
        li.setAttribute('tabindex', '-1');
        li.setAttribute('data-id', option.id);
        li.textContent = option.label;

        li.addEventListener('mousedown', (e) => e.preventDefault());
        li.addEventListener('click', () =>
            selectBusinessArea(option.id, option.label, inputId, dropdownId, hiddenId));
        li.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                selectBusinessArea(option.id, option.label, inputId, dropdownId, hiddenId);
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                const next = li.nextElementSibling;
                if (next && next.getAttribute('role') === 'option') next.focus();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prev = li.previousElementSibling;
                if (prev && prev.getAttribute('role') === 'option') prev.focus();
                else document.getElementById(inputId)?.focus();
            } else if (e.key === 'Escape') {
                closeBusinessAreaDropdown(inputId, dropdownId);
                document.getElementById(inputId)?.focus();
            } else if (e.key === 'Tab') {
                closeBusinessAreaDropdown(inputId, dropdownId);
            }
        });
        dropdown.appendChild(li);
    });
}

export function selectBusinessArea(
    id,
    label,
    inputId = 'businessAreaInput',
    dropdownId = 'businessAreaDropdown',
    hiddenId = 'businessAreaValue',
) {
    const inputEl = document.getElementById(inputId);
    const hiddenEl = document.getElementById(hiddenId);
    if (inputEl) inputEl.value = label;
    if (hiddenEl) hiddenEl.value = id;
    closeBusinessAreaDropdown(inputId, dropdownId);
    inputEl?.focus();
}

function _setBusinessAreaDropdownVisible(visible, inputId, dropdownId) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    if (input) input.setAttribute('aria-expanded', String(visible));
    if (dropdown) dropdown.style.display = visible ? 'block' : 'none';
}

export function closeBusinessAreaDropdown(
    inputId = 'businessAreaInput',
    dropdownId = 'businessAreaDropdown',
) {
    _setBusinessAreaDropdownVisible(false, inputId, dropdownId);
}

// ── Filter combobox ───────────────────────────────────────────────────────────

/**
 * Wires up the list-view filter combobox for business area multi-select.
 * Calls `onFilterChange` whenever the active filter set changes.
 */
export function initFilterBusinessAreaCombobox(onFilterChange) {
    const input = document.getElementById('filterBusinessAreaInput');
    const dropdown = document.getElementById('filterBusinessAreaDropdown');
    if (!input || !dropdown) return;

    input.addEventListener('input', () => {
        renderFilterBusinessAreaDropdown(input.value.toLowerCase());
        _setFilterBusinessAreaDropdownVisible(true);
    });

    input.addEventListener('focus', () => {
        renderFilterBusinessAreaDropdown(input.value.toLowerCase());
        _setFilterBusinessAreaDropdownVisible(true);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            const firstItem = dropdown.querySelector('[role="option"]');
            if (firstItem) firstItem.focus();
        } else if (e.key === 'Escape' || e.key === 'Tab') {
            closeFilterBusinessAreaDropdown();
        }
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('#filterBusinessAreaCombobox')) {
            closeFilterBusinessAreaDropdown();
        }
    });

    // Store callback for internal use by add/remove helpers
    _filterChangeCallback = onFilterChange ?? null;
}

// Internal reference to the caller-provided change callback
let _filterChangeCallback = null;

export function renderFilterBusinessAreaDropdown(query) {
    const dropdown = document.getElementById('filterBusinessAreaDropdown');
    if (!dropdown) return;

    const filtered = (
        query
            ? _businessAreaOptions.filter(o => o.label.toLowerCase().includes(query))
            : _businessAreaOptions
    ).filter(o => !_selectedBusinessAreaFilters.includes(o.id));

    dropdown.innerHTML = '';
    if (filtered.length === 0) {
        const li = document.createElement('li');
        li.className = 'dropdown-item disabled text-muted py-2';
        li.setAttribute('aria-disabled', 'true');
        li.textContent = query ? 'No matching business areas' : 'No more business areas available';
        dropdown.appendChild(li);
        return;
    }

    filtered.forEach(option => {
        const li = document.createElement('li');
        li.className = 'dropdown-item py-2';
        li.style.cursor = 'pointer';
        li.setAttribute('role', 'option');
        li.setAttribute('tabindex', '-1');
        li.textContent = option.label;

        li.addEventListener('mousedown', (e) => e.preventDefault());
        li.addEventListener('click', () => addBusinessAreaFilter(option.id));
        li.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                addBusinessAreaFilter(option.id);
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                const next = li.nextElementSibling;
                if (next && next.getAttribute('role') === 'option') next.focus();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prev = li.previousElementSibling;
                if (prev && prev.getAttribute('role') === 'option') prev.focus();
                else document.getElementById('filterBusinessAreaInput')?.focus();
            } else if (e.key === 'Escape' || e.key === 'Tab') {
                closeFilterBusinessAreaDropdown();
            }
        });
        dropdown.appendChild(li);
    });
}

export function addBusinessAreaFilter(id) {
    if (!_selectedBusinessAreaFilters.includes(id)) {
        _selectedBusinessAreaFilters.push(id);
    }
    const inputEl = document.getElementById('filterBusinessAreaInput');
    if (inputEl) inputEl.value = '';
    renderSelectedBusinessAreaFilters();
    renderFilterBusinessAreaDropdown('');
    closeFilterBusinessAreaDropdown();
    _filterChangeCallback?.();
}

export function removeBusinessAreaFilter(id) {
    _selectedBusinessAreaFilters = _selectedBusinessAreaFilters.filter(v => v !== id);
    renderSelectedBusinessAreaFilters();
    _filterChangeCallback?.();
}

export function renderSelectedBusinessAreaFilters() {
    const container = document.getElementById('selectedBusinessAreaFilters');
    if (!container) return;

    container.innerHTML = _selectedBusinessAreaFilters.map(id => {
        const option = _businessAreaOptions.find(o => o.id === id);
        if (!option) return '';
        return `
            <span class="badge bg-primary me-1 mb-1">
                ${escapeHtml(option.label)}
                <button type="button" class="btn-close btn-close-white btn-sm ms-1" aria-label="Remove"
                    data-action="remove-ba-filter" data-filter-id="${escapeHtml(String(id))}"
                    style="font-size: 0.55rem;"></button>
            </span>
        `;
    }).join('');

    // Delegated listener — no inline onclick
    container.querySelectorAll('[data-action="remove-ba-filter"]').forEach(btn => {
        btn.addEventListener('click', () => removeBusinessAreaFilter(btn.dataset.filterId));
    });
}

function _setFilterBusinessAreaDropdownVisible(visible) {
    const input = document.getElementById('filterBusinessAreaInput');
    const dropdown = document.getElementById('filterBusinessAreaDropdown');
    if (input) input.setAttribute('aria-expanded', String(visible));
    if (dropdown) dropdown.style.display = visible ? 'block' : 'none';
}

export function closeFilterBusinessAreaDropdown() {
    _setFilterBusinessAreaDropdownVisible(false);
}
