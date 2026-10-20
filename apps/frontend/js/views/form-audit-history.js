import { API_BASE } from '../constants.js';
import { hasPermission } from '../auth.js';

let generation = 0;
let formId = null;
let nextCursor = null;
let detailId = null;
let modal = null;
let listenerBound = false;

function pctTime(instant, stacked = false) {
    const date = new Date(instant);
    if (Number.isNaN(date.getTime())) throw new Error('Invalid audit timestamp');
    const shifted = new Date(date.getTime() - 7 * 60 * 60 * 1000);
    const time = document.createElement('time');
    time.dateTime = date.toISOString();
    const day = new Intl.DateTimeFormat('en-CA', {
        dateStyle: 'medium', timeZone: 'UTC',
    }).format(shifted);
    const clock = `${new Intl.DateTimeFormat('en-CA', {
        timeStyle: 'short', timeZone: 'UTC',
    }).format(shifted)} PCT`;
    const visible = `${day} ${clock}`;
    time.setAttribute('aria-label', `${visible}; instant ${time.dateTime}`);
    if (stacked) {
        time.className = 'form-audit__time';
        for (const part of [day, clock]) {
            const line = document.createElement('span');
            line.textContent = part;
            time.append(line);
            if (part === day) time.append(document.createTextNode(' '));
        }
    } else {
        time.textContent = visible;
    }
    return time;
}

function label(name) {
    const names = {
        'Form created': 'Form created',
        'Form saved': 'Form saved',
        'Form submitted': 'Submitted for review',
        'Form approved': 'Form approved',
        'Form rejected': 'Form rejected',
        'Changes requested': 'Changes requested',
        'Form published': 'Form published',
        'Form reverted': 'Form reverted to draft',
        'Form archived': 'Form archived',
        'Form restored': 'Form restored',
    };
    return names[name] || name.replace(/_/g, ' ');
}

function fieldLabel(name) {
    const names = {
        title: 'Form Title',
        description: 'Description',
        is_public: 'Public Visibility',
        keywords: 'Keywords',
        business_area_id: 'Business Area',
        effective_date: 'Effective Date',
        collects_personal_info: 'Collects Personal Information',
        form_source: 'Form Source',
        form_source_url: 'Form URL',
        form_attachment_url: 'Attachment object reference',
        form_attachment_filename: 'Attachment filename',
        file_type: 'File type',
        form_number_reservation_id: 'Form Number',
        status: 'Status',
        created_by_id: 'Form owner',
    };
    return names[name] || name.replace(/_/g, ' ');
}

function fieldNames(fields) {
    const names = fields.map(field => fieldLabel(field).toLowerCase().replace(/\burl\b/g, 'URL'));
    if (names.length < 3) return names.join(' and ');
    return `${names.slice(0, -1).join(', ')}, and ${names.at(-1)}`;
}

function eventPresentation(event) {
    if (event.event_name === 'Form created') {
        return { title: label(event.event_name), summary: 'created this form as a draft.' };
    }
    const fields = fieldNames(event.changed_fields);
    if (event.event_name === 'Form saved') {
        const sourceFields = new Set([
            'form_source', 'form_source_url', 'form_attachment_url',
            'form_attachment_filename', 'file_type',
        ]);
        const sourceOnly = event.changed_fields.length > 0
            && event.changed_fields.every(field => sourceFields.has(field));
        const title = sourceOnly ? 'Form source updated' : 'Form details saved';
        return { title, summary: fields ? `changed ${fields}.` : 'saved changes to this form.' };
    }
    const actions = {
        'Form submitted': 'submitted the saved form for review',
        'Form approved': 'approved the form',
        'Form rejected': 'rejected the form',
        'Changes requested': 'requested changes to the form',
        'Form published': 'published the form',
        'Form reverted': 'returned the form to draft',
        'Form archived': 'archived the form',
        'Form restored': 'restored the form',
    };
    const action = actions[event.event_name];
    return {
        title: label(event.event_name),
        summary: `${action || `recorded ${label(event.event_name)}`}.`
            + (fields ? ` Changed fields: ${fields}.` : ''),
    };
}

function mount() {
    return document.getElementById('auditHistoryMount');
}

function showStatus(message, error = false) {
    const status = document.getElementById('auditHistoryStatus');
    status.textContent = message;
    status.setAttribute('role', error ? 'alert' : 'status');
    document.getElementById('auditHistoryRetry').hidden = !error;
}

async function getJson(url) {
    const response = await fetch(url);
    if (!response.ok) {
        const failure = new Error('Audit history could not be loaded.');
        failure.unavailable = response.status === 404;
        throw failure;
    }
    return response.json();
}

function failed(error, ticket) {
    if (ticket !== generation) return;
    document.getElementById('auditLastEdited').replaceChildren();
    document.getElementById('auditLastEdited').hidden = true;
    document.getElementById('auditHistoryList').replaceChildren();
    document.getElementById('auditHistoryMore').hidden = true;
    nextCursor = null;
    showStatus(error.unavailable ? 'Audit history unavailable.' : 'Unable to load audit history.', !error.unavailable);
}

function renderLastEdited(editor) {
    const container = document.getElementById('auditLastEdited');
    container.replaceChildren();
    container.hidden = true;
    if (!editor) return;
    if (typeof editor.actor_label !== 'string' || !editor.occurred_at) {
        throw new Error('Invalid audit summary');
    }
    const icon = document.createElement('span');
    icon.className = 'form-audit__summary-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = '<i class="fas fa-clock-rotate-left"></i>';
    const content = document.createElement('p');
    const text = document.createElement('strong');
    text.textContent = `Last edited by ${editor.actor_label}`;
    content.append(text, document.createElement('br'), pctTime(editor.occurred_at));
    container.append(icon, content);
    container.hidden = false;
}

function renderRows(events) {
    const list = document.getElementById('auditHistoryList');
    for (const event of events) {
        if (typeof event.id !== 'string' || typeof event.event_name !== 'string'
            || typeof event.actor_label !== 'string' || !event.occurred_at
            || !Array.isArray(event.changed_fields)) {
            throw new Error('Invalid audit event');
        }
        if (list.querySelector(`[data-audit-id="${CSS.escape(event.id)}"]`)) continue;
        const item = document.createElement('li');
        item.className = 'form-audit__event';
        item.dataset.auditId = event.id;
        const presentation = eventPresentation(event);
        const timestamp = pctTime(event.occurred_at, true);
        const point = document.createElement('span');
        point.className = 'form-audit__point';
        point.setAttribute('aria-hidden', 'true');
        const icon = document.createElement('i');
        const sourceChange = event.event_name === 'Form saved'
            && event.changed_fields.some(field => ['form_source', 'form_source_url', 'form_attachment_url'].includes(field));
        const icons = {
            'Form created': 'fa-file-circle-plus',
            'Form submitted': 'fa-paper-plane',
            'Form approved': 'fa-check',
            'Form rejected': 'fa-xmark',
            'Changes requested': 'fa-pen',
            'Form published': 'fa-globe',
            'Form reverted': 'fa-rotate-left',
            'Form archived': 'fa-box-archive',
            'Form restored': 'fa-rotate-right',
        };
        icon.className = `fas ${sourceChange ? 'fa-link' : icons[event.event_name] || 'fa-pen'}`;
        point.append(icon);
        const content = document.createElement('div');
        content.className = 'form-audit__content';
        const name = document.createElement('strong');
        name.textContent = presentation.title;
        const summary = document.createElement('p');
        const actor = document.createElement('span');
        actor.className = 'form-audit__actor';
        actor.textContent = event.actor_label;
        summary.append(actor, document.createTextNode(` ${presentation.summary}`));
        if (event.event_name !== 'Form created' && event.event_name !== 'Form submitted') {
            const details = document.createElement('a');
            details.href = '#auditDetailModal';
            details.dataset.auditDetail = event.id;
            details.setAttribute('aria-label', `View details for event ${list.children.length + 1}: ${presentation.title} at ${timestamp.getAttribute('aria-label')}`);
            details.textContent = 'View details';
            summary.append(document.createTextNode(' '), details);
        }
        content.append(name, summary);
        item.append(timestamp, point, content);
        list.append(item);
    }
}

async function loadPage(cursor = null) {
    const ticket = generation;
    const more = document.getElementById('auditHistoryMore');
    more.disabled = true;
    showStatus(cursor ? 'Loading more audit history...' : 'Loading audit history...');
    try {
        const url = new URL(`${API_BASE}/staff/forms/${encodeURIComponent(formId)}/audit/events`, location.origin);
        url.searchParams.set('limit', '10');
        if (cursor) url.searchParams.set('cursor', cursor);
        const page = await getJson(url.toString());
        if (ticket !== generation) return;
        if (!Array.isArray(page.events)
            || (page.next_cursor !== null && page.next_cursor !== undefined && typeof page.next_cursor !== 'string')) {
            throw new Error('Invalid audit history response');
        }
        renderRows(page.events);
        nextCursor = page.next_cursor || null;
        more.hidden = !nextCursor;
        more.disabled = false;
        showStatus(document.getElementById('auditHistoryList').children.length ? '' : 'No audit history');
    } catch (error) {
        failed(error, ticket);
    }
}

async function loadInitial() {
    const ticket = generation;
    showStatus('Loading audit history...');
    try {
        const summary = await getJson(`${API_BASE}/staff/forms/${encodeURIComponent(formId)}/audit/summary`);
        if (ticket !== generation) return;
        if (!summary || !Object.hasOwn(summary, 'last_edited_by')) {
            throw new Error('Invalid audit summary response');
        }
        renderLastEdited(summary.last_edited_by);
        await loadPage();
    } catch (error) {
        failed(error, ticket);
    }
}

function valueNode(value) {
    const node = document.createElement('span');
    node.className = 'form-audit__value';
    node.textContent = value === null || value === undefined
        ? '—' : typeof value === 'string' ? value : JSON.stringify(value);
    return node;
}

async function openDetails(id, trigger) {
    const ticket = generation;
    detailId = id;
    const dialog = document.getElementById('auditDetailModal');
    const content = document.getElementById('auditDetailContent');
    content.replaceChildren();
    content.textContent = 'Loading audit details...';
    modal = window.bootstrap.Modal.getOrCreateInstance(dialog);
    dialog.addEventListener('hidden.bs.modal', () => trigger.isConnected && trigger.focus(), { once: true });
    modal.show();
    try {
        const event = await getJson(`${API_BASE}/staff/forms/${encodeURIComponent(formId)}/audit/events/${encodeURIComponent(id)}`);
        if (ticket !== generation || detailId !== id) return;
        if (typeof event.event_name !== 'string' || typeof event.actor_label !== 'string'
            || !event.occurred_at || !Array.isArray(event.changes)) {
            throw new Error('Invalid audit detail response');
        }
        content.replaceChildren();
        const heading = document.createElement('h3');
        heading.className = 'h5';
        heading.textContent = label(event.event_name);
        const metadata = document.createElement('p');
        metadata.append(document.createTextNode(`${event.actor_label} — `), pctTime(event.occurred_at));
        content.append(heading, metadata);
        if (event.reason?.trim()) {
            const reason = document.createElement('p');
            reason.textContent = `Reason: ${event.reason}`;
            content.append(reason);
        }
        for (const change of event.changes) {
            const field = document.createElement('section');
            const title = document.createElement('h4');
            title.className = 'h6';
            title.textContent = fieldLabel(change.field);
            const previous = document.createElement('p');
            previous.append(document.createTextNode('Previous: '), valueNode(change.old_value));
            const next = document.createElement('p');
            next.append(document.createTextNode('New: '), valueNode(change.new_value));
            field.append(title, previous, next);
            content.append(field);
        }
    } catch (_error) {
        if (ticket !== generation || detailId !== id) return;
        content.replaceChildren();
        const message = document.createElement('p');
        message.setAttribute('role', 'alert');
        message.textContent = 'Unable to load audit details.';
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'btn btn-outline-primary';
        retry.textContent = 'Retry details';
        retry.addEventListener('click', () => openDetails(id, trigger), { once: true });
        content.append(message, retry);
    }
}

export function clearAuditHistory() {
    ++generation;
    detailId = null;
    nextCursor = null;
    formId = null;
    modal?.hide();
    modal?.dispose();
    modal = null;
    mount()?.replaceChildren();
}

window.addEventListener('auth:session-cleared', clearAuditHistory);

export function loadAuditHistory(id) {
    clearAuditHistory();
    if (!hasPermission('form:audit') || !hasPermission('form:edit')) return;
    formId = id;
    const host = mount();
    host.innerHTML = `
        <section class="form-page__surface form-audit" aria-labelledby="auditHistoryHeading">
            <h2 id="auditHistoryHeading">Audit History</h2>
            <div id="auditLastEdited" class="form-audit__summary" hidden></div>
            <p id="auditHistoryStatus" role="status" aria-live="polite">Loading audit history...</p>
            <button type="button" id="auditHistoryRetry" class="btn btn-outline-primary" hidden>Retry audit history</button>
            <ul id="auditHistoryList" class="form-audit__timeline" aria-label="Form activity"></ul>
            <button type="button" id="auditHistoryMore" class="btn btn-outline-primary" hidden>Load more</button>
        </section>
        <div class="modal fade" id="auditDetailModal" tabindex="-1" aria-labelledby="auditDetailHeading" aria-hidden="true">
            <div class="modal-dialog modal-dialog-scrollable"><div class="modal-content">
                <div class="modal-header"><h2 class="modal-title h5" id="auditDetailHeading">Audit event details</h2>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close audit details"></button>
                </div>
                <div class="modal-body" id="auditDetailContent"></div>
                <div class="modal-footer"><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button></div>
            </div></div>
        </div>`;
    if (!listenerBound) {
        listenerBound = true;
        host.addEventListener('click', event => {
            const detail = event.target.closest('[data-audit-detail]');
            if (detail) {
                event.preventDefault();
                openDetails(detail.dataset.auditDetail, detail);
            }
            if (event.target.id === 'auditHistoryMore' && nextCursor) loadPage(nextCursor);
            if (event.target.id === 'auditHistoryRetry') loadInitial();
        });
    }
    void loadInitial();
}
