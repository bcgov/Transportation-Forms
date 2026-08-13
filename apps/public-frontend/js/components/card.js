/*
 * Form card renderer + shared business-area / file-type presentation helpers.
 *
 * Replaces the former <form-card> custom element (FEAT-0028 US-006). Renders a
 * plain <article class="form-card-v2"> so styling inherits from main.css and no
 * custom-element registration is needed.
 *
 * Only the eight allow-listed public fields are ever read or rendered
 * (US-006 BR-001). Internal identifiers are never touched.
 */

import { escapeHtml, formatDate, formatFileType, truncate, byteLength } from '../utils.js';
import { HISTORY_STATE_CAP_BYTES } from '../constants.js';

const ALLOWED_FIELDS = [
  'form_number', 'title', 'description', 'business_area',
  'file_type', 'effective_date', 'updated_at', 'keywords',
];

/** Project an API item down to the allow-listed fields only. */
export function pickAllowed(raw) {
  const safe = {};
  for (const k of ALLOWED_FIELDS) safe[k] = raw && raw[k] != null ? raw[k] : null;
  return safe;
}

/**
 * Map a business-area name to its presentation tokens.
 * Matching is case-insensitive (US-006 Data rule). Unknown/empty → default.
 */
export function baInfo(businessArea) {
  const name = String(businessArea || '').trim();
  const key = name.toLowerCase();
  if (key === 'compliance') return { badgeClass: 'compliance', accentClass: 'ba-compliance', icon: 'bi-shield-check', label: name };
  if (key === 'permits')    return { badgeClass: 'permits',    accentClass: 'ba-permits',    icon: 'bi-card-checklist', label: name };
  if (key === 'licensing')  return { badgeClass: 'licensing',  accentClass: 'ba-licensing',  icon: 'bi-award', label: name };
  return { badgeClass: 'default', accentClass: '', icon: 'bi-folder2-open', label: name };
}

/** Map a file-type to its pill tokens (label, colour class, icon). */
export function fileTypeInfo(fileType) {
  const key = String(fileType || '').toLowerCase();
  const label = formatFileType(fileType) || 'Unknown';
  if (key === 'pdf')                 return { label, cls: 'pdf',  icon: 'bi-file-earmark-pdf' };
  if (key === 'docx' || key === 'doc') return { label, cls: 'docx', icon: 'bi-file-earmark-word' };
  if (key === 'xlsx' || key === 'xls') return { label, cls: 'xlsx', icon: 'bi-file-earmark-excel' };
  if (key === 'pptx' || key === 'ppt') return { label, cls: '',     icon: 'bi-file-earmark-ppt' };
  return { label, cls: '', icon: 'bi-file-earmark' };
}

/** Cache the full record in history.state for cache-first detail render. */
function stateForDetail(f) {
  if (byteLength(f) > HISTORY_STATE_CAP_BYTES) return null;
  return f;
}

/**
 * Render a single form card as an <li> ready to append to #resultsList.
 * @param {object} raw — an API form item
 * @returns {HTMLLIElement}
 */
export function renderFormCard(raw) {
  const f = pickAllowed(raw);
  const ba = baInfo(f.business_area);
  const ft = fileTypeInfo(f.file_type);
  const hasNumber = !!f.form_number;
  const num = f.form_number || '—';
  const title = f.title || '';
  const desc = truncate(f.description || '', 200);
  const upd = formatDate(f.updated_at);
  const eff = formatDate(f.effective_date);
  const detailHref = hasNumber ? `/forms/${encodeURIComponent(f.form_number)}` : '';
  const routeState = escapeHtml(JSON.stringify(stateForDetail(f)));

  const numEl = hasNumber
    ? `<a class="form-num-link" href="${escapeHtml(detailHref)}" data-route-state='${routeState}' aria-label="Form number ${escapeHtml(num)}">${escapeHtml(num)}</a>`
    : `<span class="form-num-link" aria-disabled="true" title="Form number not yet assigned">${escapeHtml(num)}</span>`;

  const viewMore = hasNumber
    ? `<a class="btn-view-more" href="${escapeHtml(detailHref)}" data-route-state='${routeState}' aria-label="View more details about ${escapeHtml(num)}"><i class="bi bi-eye" aria-hidden="true"></i> View details</a>`
    : `<span class="btn-view-more" aria-disabled="true" title="Form number not yet assigned"><i class="bi bi-eye" aria-hidden="true"></i> View details</span>`;

  const downloadBtn = hasNumber
    ? `<button type="button" class="btn-download" data-action="download" data-form-number="${escapeHtml(f.form_number)}" aria-label="Download ${escapeHtml(num)}${ft.label ? ` (${escapeHtml(ft.label)})` : ''}"><i class="bi bi-download" aria-hidden="true"></i> Download</button>`
    : `<button type="button" class="btn-download" disabled aria-disabled="true" aria-label="Download (unavailable)"><i class="bi bi-download" aria-hidden="true"></i> Download</button>`;

  const li = document.createElement('li');
  li.setAttribute('role', 'listitem');
  li.innerHTML = `
    <article class="form-card-v2${ba.accentClass ? ` ${ba.accentClass}` : ''}">
      <div class="card-accent" aria-hidden="true"></div>
      <div class="card-body-inner">
        <div class="card-meta-row">
          ${numEl}
          ${f.business_area ? `<span class="ba-badge ${ba.badgeClass}"><i class="bi ${ba.icon}" aria-hidden="true"></i> ${escapeHtml(ba.label)}</span>` : ''}
          ${upd ? `<time class="card-date" datetime="${escapeHtml(f.updated_at || '')}">Updated ${escapeHtml(upd)}</time>` : ''}
        </div>
        <h2 class="form-card-v2__title">${escapeHtml(title)}</h2>
        ${desc ? `<p class="card-desc">${escapeHtml(desc)}</p>` : ''}
        <div class="card-footer-row">
          <span class="file-type-pill${ft.cls ? ` ${ft.cls}` : ''}"><i class="bi ${ft.icon}" aria-hidden="true"></i> ${escapeHtml(ft.label)}</span>
          ${eff ? `<span class="file-type-pill"><i class="bi bi-calendar3" aria-hidden="true"></i><span class="visually-hidden">Effective:</span> <time datetime="${escapeHtml(f.effective_date || '')}">${escapeHtml(eff)}</time></span>` : ''}
          ${viewMore}
          ${downloadBtn}
        </div>
      </div>
    </article>
  `;
  return li;
}
