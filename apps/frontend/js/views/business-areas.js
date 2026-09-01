// frontend/js/views/business-areas.js
// Manages the business area combobox (form modal) and filter tags UI (list view).
import { API_BASE } from '../constants.js';
import { showAlert } from '../utils.js';

// ── Module-private state ──────────────────────────────────────────────────────
let _businessAreaOptions = [];
let _businessAreasRequestController = null;
const MAX_BUSINESS_AREAS = 500;
const MAX_BUSINESS_AREA_ID_LENGTH = 128;
const MAX_BUSINESS_AREA_NAME_LENGTH = 200;
const MAX_BUSINESS_AREA_DESCRIPTION_LENGTH = 300;

// ── State accessors ───────────────────────────────────────────────────────────
export function getBusinessAreaOptions() {
    return [..._businessAreaOptions];
}

export function resetBusinessAreas() {
    _businessAreasRequestController?.abort();
    _businessAreasRequestController = null;
    _businessAreaOptions = [];
}

// ── API ───────────────────────────────────────────────────────────────────────

/**
 * Fetches /api/v1/business-areas and populates _businessAreaOptions.
 * Restores any previously confirmed selection in the form combobox.
 */
export async function loadBusinessAreas() {
    _businessAreasRequestController?.abort();
    _businessAreasRequestController = new AbortController();
    const { signal } = _businessAreasRequestController;
    const previousId = document.getElementById('businessAreaValue')?.value ?? '';
    const inputEl = document.getElementById('businessAreaInput');
    const valueEl = document.getElementById('businessAreaValue');

    try {
        const response = await fetch(`${API_BASE}/business-areas`, { signal });
        if (!response.ok) throw new Error('Failed to load business areas');
        const payload = await response.json();
        if (signal.aborted) return false;
        if (!Array.isArray(payload)) throw new Error('Invalid business areas response');
        const areas = payload.slice(0, MAX_BUSINESS_AREAS);
        const normalizedAreas = areas
            .filter(area => (
                area &&
                (typeof area.id === 'string' || typeof area.id === 'number') &&
                typeof area.name === 'string' &&
                area.name.trim()
            ))
            .map(area => {
                const id = String(area.id).slice(0, MAX_BUSINESS_AREA_ID_LENGTH);
                const name = area.name.trim().slice(0, MAX_BUSINESS_AREA_NAME_LENGTH);
                const description = typeof area.description === 'string'
                    ? area.description.trim().slice(0, MAX_BUSINESS_AREA_DESCRIPTION_LENGTH)
                    : '';
                return { id, label: description ? `${name} - ${description}` : name };
            })
            .filter(area => area.id);
        if (areas.length > 0 && normalizedAreas.length === 0) {
            throw new Error('Invalid business areas response');
        }
        const areasById = new Map();
        for (const area of normalizedAreas) {
            if (!areasById.has(area.id)) areasById.set(area.id, area);
        }
        _businessAreaOptions = [...areasById.values()];

        // Restore previously confirmed selection if it still exists in the list
        if (previousId) {
            const found = _businessAreaOptions.find(o => o.id === previousId);
            if (found) {
                if (inputEl) inputEl.value = found.label;
                if (valueEl) valueEl.value = found.id;
            }
        }
        return true;
    } catch (error) {
        if (signal.aborted || error.name === 'AbortError') return false;
        showAlert('Unable to load business areas. Please try again.', 'danger');
        return false;
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
        ? _businessAreaOptions.filter(option => option.label.toLowerCase().includes(query))
        : _businessAreaOptions;

    dropdown.replaceChildren();
    if (filtered.length === 0) {
        const emptyItem = document.createElement('li');
        emptyItem.className = 'dropdown-item disabled text-muted py-2';
        emptyItem.setAttribute('aria-disabled', 'true');
        emptyItem.textContent = query ? 'No matching business areas' : 'No business areas available';
        dropdown.appendChild(emptyItem);
        return;
    }

    filtered.forEach(option => {
        const item = document.createElement('li');
        item.className = 'dropdown-item py-2';
        item.style.cursor = 'pointer';
        item.setAttribute('role', 'option');
        item.setAttribute('tabindex', '-1');
        item.dataset.id = option.id;
        item.textContent = option.label;

        item.addEventListener('mousedown', event => event.preventDefault());
        item.addEventListener('click', () =>
            selectBusinessArea(option.id, option.label, inputId, dropdownId, hiddenId));
        item.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                selectBusinessArea(option.id, option.label, inputId, dropdownId, hiddenId);
            } else if (event.key === 'ArrowDown') {
                event.preventDefault();
                item.nextElementSibling?.focus();
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                const previous = item.previousElementSibling;
                if (previous?.getAttribute('role') === 'option') previous.focus();
                else document.getElementById(inputId)?.focus();
            } else if (event.key === 'Escape') {
                closeBusinessAreaDropdown(inputId, dropdownId);
                document.getElementById(inputId)?.focus();
            } else if (event.key === 'Tab') {
                closeBusinessAreaDropdown(inputId, dropdownId);
            }
        });
        dropdown.appendChild(item);
    });
}

export function selectBusinessArea(
    id,
    label,
    inputId = 'businessAreaInput',
    dropdownId = 'businessAreaDropdown',
    hiddenId = 'businessAreaValue',
) {
    const input = document.getElementById(inputId);
    const hidden = document.getElementById(hiddenId);
    if (input) input.value = label;
    if (hidden) hidden.value = id;
    closeBusinessAreaDropdown(inputId, dropdownId);
    input?.focus();
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
