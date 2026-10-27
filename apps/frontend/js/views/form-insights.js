import { API_BASE } from '../constants.js';
import { hasPermission } from '../auth.js';
import { formatDateTime, showNotification } from '../utils.js';

const PERIODS = [
    ['1d', '1 day', 1],
    ['7d', '7 days', 7],
    ['30d', '30 days', 30],
    ['90d', '90 days', 90],
    ['180d', '180 days', 180],
    ['1y', '1 year', 365],
    ['all', 'All time', null],
];
const METRICS = [
    ['download', 'Form downloads'],
    ['link_click', 'Source-link clicks'],
    ['detail_view', 'Form-detail views'],
];
const SOURCES = [
    ['Staff', 'Staff portal'],
    ['Public', 'Public portal'],
];

let generation = 0;
let formId = null;
let selectedPeriod = '30d';
let lastSuccess = null;
let lastRefreshAt = null;
let lastSuccessAt = null;
let retryRefresh = false;
let listenerBound = false;

function mount() {
    return document.getElementById('formInsightsMount');
}

function dateLabel(date) {
    return date.toLocaleDateString('en-CA', {
        year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC',
    });
}

function displayDates(result, receivedAt) {
    const cutoffDay = result.pct_day_cutoff?.match(/^(\d{4}-\d{2}-\d{2})T00:00:00-07:00$/)?.[1];
    const cutoff = new Date(`${cutoffDay}T00:00:00Z`);
    if (!cutoffDay || Number.isNaN(cutoff.getTime()) || cutoff.toISOString().slice(0, 10) !== cutoffDay) {
        throw new Error('Invalid statistics cutoff');
    }
    const through = new Date(cutoff);
    through.setUTCDate(through.getUTCDate() - 1);
    if (result.data_through !== through.toISOString().slice(0, 10)) {
        throw new Error('Invalid statistics data-through date');
    }
    const days = PERIODS.find(([period]) => period === result.period)?.[2];
    if (days === undefined) throw new Error('Invalid statistics period');
    if (result.period === '1d') {
        return {
            caption: `Today so far (${receivedAt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase()} ${dateLabel(through)})`,//`Today so far (${dateLabel(through)} PCT; as of ${formatDateTime(receivedAt.toISOString())} local time)`,
        };
    }
    if (days === null) {
        return {
            caption: `All time retained totals through ${dateLabel(through)} (PCT)`,
        };
    }
    const start = new Date(cutoff);
    start.setUTCDate(start.getUTCDate() - days);
    return {
        caption: `${PERIODS.find(([period]) => period === result.period)[1]}: ${dateLabel(start)} to ${dateLabel(through)} (PCT)`,
    };
}

function updateSelection() {
    mount().querySelectorAll('[data-insights-period]').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.insightsPeriod === selectedPeriod));
    });
}

function clearValues() {
    mount().querySelector('.form-insights__table-wrap').hidden = true;
    mount().querySelector('#formInsightsCaption').textContent = '';
    mount().querySelector('#formInsightsLastRefresh').textContent = '';
    mount().querySelector('#formInsightsLastRefresh').hidden = true;
    mount().querySelectorAll('[data-insights-value]').forEach(cell => { cell.textContent = ''; });
}

function showState(message, retry = false, alert = false) {
    const status = mount().querySelector('#formInsightsStatus');
    const error = mount().querySelector('#formInsightsError');
    status.textContent = alert ? '' : message;
    error.textContent = alert ? message : '';
    mount().querySelector('#formInsightsRetry').hidden = !retry;
}

function showResult(result, refreshedAt = null, receivedAt = new Date()) {
    const dates = displayDates(result, receivedAt);
    for (const [metric] of METRICS) {
        for (const [source] of SOURCES) {
            const value = result.totals?.[metric]?.[source];
            if (!Number.isSafeInteger(value) || value < 0) {
                throw new Error('Invalid statistics total');
            }
        }
    }
    for (const [metric] of METRICS) {
        for (const [source] of SOURCES) {
            mount().querySelector(`[data-insights-value="${metric}-${source}"]`).textContent =
                result.totals[metric][source].toLocaleString('en-CA');
        }
    }
    mount().querySelector('#formInsightsCaption').textContent = dates.caption;
    const refreshTime = mount().querySelector('#formInsightsLastRefresh');
    refreshTime.textContent = refreshedAt
        ? `Last refreshed ${formatDateTime(refreshedAt.toISOString())} (local time)`
        : '';
    refreshTime.hidden = !refreshedAt;
    mount().querySelector('.form-insights__table-wrap').hidden = false;
    showState('');
}

async function requestPeriod(period, refresh = false) {
    const ticket = ++generation;
    selectedPeriod = period;
    retryRefresh = false;
    updateSelection();
    clearValues();
    showState('Loading form activity...');
    const refreshButton = mount().querySelector('#formInsightsRefresh');
    refreshButton.disabled = true;
    try {
        const url = new URL(`${API_BASE}/staff/forms/${encodeURIComponent(formId)}/stats`, window.location.origin);
        url.searchParams.set('period', period);
        if (refresh) url.searchParams.set('refresh', 'true');
        const response = await fetch(url.toString());
        if (ticket !== generation) return;
        if (!response.ok) {
            const failure = new Error('Unable to load form activity.');
            failure.status = response.status;
            throw failure;
        }
        const result = await response.json();
        if (ticket !== generation) return;
        if (result.period !== period) throw new Error('Unexpected statistics period');
        const receivedAt = new Date();
        const refreshedAt = refresh ? receivedAt : null;
        showResult(result, refreshedAt, receivedAt);
        lastSuccess = result;
        lastRefreshAt = refreshedAt;
        lastSuccessAt = receivedAt;
    } catch (error) {
        if (ticket !== generation) return;
        if (error.status === 403 && lastSuccess && lastSuccess.period !== period) {
            selectedPeriod = lastSuccess.period;
            updateSelection();
            showResult(lastSuccess, lastRefreshAt, lastSuccessAt);
            showNotification('You do not have permission to view statistics.', 'danger');
        } else {
            lastSuccess = null;
            lastRefreshAt = null;
            lastSuccessAt = null;
            retryRefresh = refresh;
            clearValues();
            showState(
                error.status === 404 ? 'Form activity is unavailable.' : 'Unable to load form activity.',
                error.status !== 404,
                true,
            );
        }
    } finally {
        if (ticket === generation) refreshButton.disabled = false;
    }
}

export function clearFormInsights() {
    ++generation;
    formId = null;
    selectedPeriod = '30d';
    lastSuccess = null;
    lastRefreshAt = null;
    lastSuccessAt = null;
    retryRefresh = false;
    mount()?.replaceChildren();
}

window.addEventListener('auth:session-cleared', clearFormInsights);

export function loadFormInsights(id) {
    clearFormInsights();
    if (!hasPermission('form:stats') || !hasPermission('form:edit')) return;
    formId = id;
    const host = mount();
    host.innerHTML = `
        <section class="form-page__surface form-insights" aria-labelledby="formInsightsHeading">
            <header class="form-insights__heading">
                <div><h2 id="formInsightsHeading">Form Insights</h2>
                    <p>Engagement history for this form.</p></div>
                <div class="form-insights__refresh">
                    <button type="button" id="formInsightsRefresh" class="btn btn-outline-primary">
                        <i class="fas fa-arrows-rotate" aria-hidden="true"></i> Refresh
                    </button>
                    <span id="formInsightsLastRefresh" class="form-insights__updated" role="status" aria-live="polite" hidden></span>
                </div>
            </header>
            <section class="form-insights__section" aria-labelledby="formInsightsActivityHeading">
                <div class="form-insights__section-heading">
                    <div><h3 id="formInsightsActivityHeading">Form activity</h3>
                        <p>Qualified actions, separated by portal source.</p></div>
                    <div class="form-insights__periods" role="group" aria-label="Statistics time scale">
                        ${PERIODS.map(([period, label]) => `<button type="button" data-insights-period="${period}" aria-pressed="${period === '30d'}">${label}</button>`).join('')}
                    </div>
                </div>
                <p id="formInsightsStatus" role="status" aria-live="polite"></p>
                <p id="formInsightsError" role="alert"></p>
                <button type="button" id="formInsightsRetry" class="btn btn-outline-primary" hidden>Retry form activity</button>
                <div class="form-insights__table-wrap" hidden>
                    <table class="form-insights__table">
                        <caption id="formInsightsCaption"></caption>
                        <thead><tr><th scope="col">Engagement</th>
                            ${SOURCES.map(([source, label]) => `<th scope="col"><span class="form-insights__source form-insights__source--${source.toLowerCase()}">${label}</span></th>`).join('')}
                        </tr></thead>
                        <tbody>${METRICS.map(([metric, label]) => `<tr><th scope="row">${label}</th>
                            ${SOURCES.map(([source]) => `<td data-insights-value="${metric}-${source}"></td>`).join('')}
                        </tr>`).join('')}</tbody>
                    </table>
                </div>
            </section>
        </section>`;
    if (!listenerBound) {
        listenerBound = true;
        host.addEventListener('click', event => {
            const button = event.target.closest('[data-insights-period]');
            if (button && button.dataset.insightsPeriod !== selectedPeriod) {
                void requestPeriod(button.dataset.insightsPeriod);
            }
            if (event.target.closest('#formInsightsRefresh')) void requestPeriod(selectedPeriod, true);
            if (event.target.id === 'formInsightsRetry') void requestPeriod(selectedPeriod, retryRefresh);
        });
    }
    void requestPeriod('30d');
}
