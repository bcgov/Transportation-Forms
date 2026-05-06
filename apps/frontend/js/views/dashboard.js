// frontend/js/views/dashboard.js
// Dashboard/home view — shows summary statistics from /api/v1/stats/dashboard.

import { API_BASE } from '../constants.js';
import { showAlert } from '../utils.js';
import { isAdminUser, hasPortalRoles } from '../auth.js';
import { getCurrentUser } from '../state.js';

// ─── DOM element IDs ──────────────────────────────────────────────────────────

const VIEW_ID = 'dashboardView';
const STAT_PUBLISHED = 'stat-published-forms';
const STAT_AWAITING_APPROVAL = 'stat-forms-awaiting-approval';
const STAT_RESERVATIONS = 'stat-reservations-awaiting-approval';
const ERROR_ID = 'dashboardStatsError';
const PAGE_TITLE_ID = 'pageTitle';

// ─── View entry point ─────────────────────────────────────────────────────────

/**
 * Show the dashboard view and load the latest summary statistics.
 * Called by the router when navigating to /dashboard.
 */
export async function showDashboardView() {
    document.getElementById(VIEW_ID).style.display = 'block';
    document.getElementById(PAGE_TITLE_ID).textContent = 'Dashboard - BC Gov';

    await loadDashboardStats();
}

// ─── Stats loader ─────────────────────────────────────────────────────────────

/**
 * Fetch summary statistics from GET /api/v1/stats/dashboard and populate the
 * three stat cards. On error, show the inline error banner.
 *
 * API endpoint  : GET /api/v1/stats/dashboard
 * Response shape: { published_forms, forms_awaiting_approval, reservations_awaiting_approval }
 */
export async function loadDashboardStats() {
    // Reset to placeholder while loading
    document.getElementById(STAT_PUBLISHED).textContent = '—';
    document.getElementById(STAT_AWAITING_APPROVAL).textContent = '—';
    document.getElementById(STAT_RESERVATIONS).textContent = '—';

    const errorEl = document.getElementById(ERROR_ID);
    errorEl.style.display = 'none';
    errorEl.textContent = '';

    try {
        const response = await fetch(`${API_BASE}/stats/dashboard`);
        if (!response.ok) {
            throw new Error('Failed to load dashboard stats');
        }
        const data = await response.json();
        document.getElementById(STAT_PUBLISHED).textContent = data.published_forms;
        document.getElementById(STAT_AWAITING_APPROVAL).textContent = data.forms_awaiting_approval;
        document.getElementById(STAT_RESERVATIONS).textContent = data.reservations_awaiting_approval;
    } catch (err) {
        errorEl.textContent = 'Failed to load dashboard statistics. Please try again.';
        errorEl.style.display = 'block';
    }
}


