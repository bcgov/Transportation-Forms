// frontend/js/utils.js
// Single source of truth for all reusable display/format/DOM helpers.

import { STATUS_LABELS } from './constants.js';

export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

export function formatDateTime(value) {
    if (!value) return '-';
    const dt = new Date(value);
    return Number.isNaN(dt.getTime()) ? '-' : dt.toLocaleString();
}

export async function getErrorDetail(response, fallbackMessage) {
    try {
        const payload = await response.json();
        if (typeof payload?.detail === 'string') {
            return payload.detail;
        }
    } catch (_error) {
    }
    return fallbackMessage;
}

export function parsePermissions(value) {
    return value
        .split(',')
        .map(item => item.trim())
        .filter(item => item.length > 0);
}

export function formatReservationStatus(status) {
    return STATUS_LABELS[status] || status;
}

export function getFormNumberDisplay(form) {
    const possibleValues = [
        form?.full_form_number,
        form?.form_number,
        form?.form_number_display,
        form?.form_number_value,
        form?.form_number_reservation?.full_form_number,
        form?.form_number_reservation?.form_number,
    ];

    for (const value of possibleValues) {
        if (typeof value === 'string' && value.trim()) {
            return value.trim();
        }
    }

    return 'N/A';
}

export function showAlert(message, type = 'info') {
    showNotification(message, type);
    // const alertDiv = document.createElement('div');
    // alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    // alertDiv.textContent = message;
    // const closeBtn = document.createElement('button');
    // closeBtn.type = 'button';
    // closeBtn.className = 'btn-close';
    // closeBtn.setAttribute('data-bs-dismiss', 'alert');
    // alertDiv.appendChild(closeBtn);
    // document.getElementById('alertContainer').appendChild(alertDiv);

    // setTimeout(() => alertDiv.remove(), 5000);
}

export function showNotification(message, type = 'info') {
    const safeType = ['success', 'danger', 'warning', 'info'].includes(type) ? type : 'info';
    const typeIcons = {
        success: 'fa-check-circle',
        danger: 'fa-times-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };
    const typeColors = {
        success: '#198754',
        danger: '#dc3545',
        warning: '#fd7e14',
        info: '#0d6efd'
    };

    const toastId = 'toast-' + Date.now();
    const toastHtml = `
        <div id="${toastId}" class="toast notification-toast" role="alert" aria-live="assertive" aria-atomic="true" data-bs-delay="6000">
            <div class="toast-header" style="border-left: 4px solid ${typeColors[safeType]};">
                <i class="fas ${typeIcons[safeType]} me-2" style="color: ${typeColors[safeType]};"></i>
                <strong class="me-auto">Notification</strong>
                <small class="text-muted">just now</small>
                <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
            <div class="toast-body">${escapeHtml(message)}</div>
        </div>
    `;

    const container = document.getElementById('notificationContainer');
    container.insertAdjacentHTML('beforeend', toastHtml);

    const toastEl = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastEl);
    toast.show();

    // Clean up DOM after hidden
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

export function showSpinner(selector, show) {
    const container = document.querySelector(selector);
    if (show) {
        container.innerHTML = `
            <div class="spinner-container">
                <div class="spinner-border" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;
    }
}
