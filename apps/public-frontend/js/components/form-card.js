/*
 * <form-card> Custom Element — US-002.
 *
 * Light DOM (per AC10) so styles inherit from the vendored BC Bootstrap.
 *
 * Usage:
 *   const card = document.createElement('form-card');
 *   card.dataset.form = JSON.stringify(formItem);
 *   list.appendChild(card);
 *
 * Required fields on the form item:
 *   form_number, title, description, business_area, file_type,
 *   effective_date, updated_at
 *
 * Internal identifiers from the database are NEVER touched and not rendered
 * (AC12 — guaranteed by the public API surface, which doesn't expose them;
 * we additionally only read the allow-listed fields below).
 */

import { escapeHtml, formatDate, formatFileType, truncate, byteLength } from '../utils.js';
import { HISTORY_STATE_CAP_BYTES } from '../constants.js';
import { downloadFormFile } from '../api.js';

const ALLOWED_FIELDS = [
  'form_number', 'title', 'description', 'business_area',
  'file_type', 'effective_date', 'updated_at', 'keywords',
];

class FormCard extends HTMLElement {
  connectedCallback() {
    this._render();
    this.addEventListener('click', this._onClick);
  }

  disconnectedCallback() {
    this.removeEventListener('click', this._onClick);
  }

  static get observedAttributes() { return ['data-form']; }
  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _readForm() {
    const raw = this.dataset.form;
    if (!raw) return null;
    let parsed;
    try { parsed = JSON.parse(raw); } catch { return null; }
    // Allow-list project fields — never render anything we didn't ask for.
    const safe = {};
    for (const k of ALLOWED_FIELDS) safe[k] = parsed[k] ?? null;
    return safe;
  }

  _render() {
    const f = this._readForm();
    if (!f) { this.innerHTML = ''; return; }

    const num = f.form_number || '—';
    const title = f.title || '';
    const desc = truncate(f.description || '', 160);
    const ba = f.business_area || '';
    const ft = formatFileType(f.file_type);
    const eff = formatDate(f.effective_date);
    const hasNumber = !!f.form_number;

    // "View more" is a real anchor (AC3); when form_number is null it's a
    // disabled span with aria-disabled (AC2).
    const viewMore = hasNumber
      ? `<a class="form-card__more" href="/forms/${escapeHtml(f.form_number)}"
            data-route-state='${escapeHtml(JSON.stringify(this._stateForDetail(f)))}'>View more</a>`
      : `<span class="form-card__more text-muted" aria-disabled="true"
              title="Form number not yet assigned">View more</span>`;

    const downloadLabel = hasNumber
      ? `Download ${escapeHtml(num)}${ft ? ` (${escapeHtml(ft)})` : ''}`
      : 'Download (unavailable)';

    // Download is its own tab stop (AC6). Use a <button> not inside the
    // "View more" anchor to keep the two stops distinct.
    const downloadBtn = hasNumber
      ? `<button type="button" class="btn btn-link p-0 form-card__download"
                data-action="download" aria-label="${downloadLabel}">⬇</button>`
      : `<button type="button" class="btn btn-link p-0 form-card__download"
                disabled aria-disabled="true" aria-label="${downloadLabel}">⬇</button>`;

    this.innerHTML = `
      <div class="form-card__header">
        <span class="form-card__num">${escapeHtml(num)}</span>
        ${ba ? `<span class="text-muted">·</span><span class="form-card__ba">${escapeHtml(ba)}</span>` : ''}
        ${ft ? `<span class="badge ms-auto">${escapeHtml(ft)}</span>` : ''}
      </div>
      <h3 class="form-card__title">${escapeHtml(title)}</h3>
      <p class="form-card__desc">${escapeHtml(desc)}${desc ? ' ' : ''}${viewMore}</p>
      <div class="form-card__actions">
        ${eff ? `<small class="text-muted"><time datetime="${escapeHtml(f.effective_date || '')}">Effective ${escapeHtml(eff)}</time></small>` : ''}
        ${downloadBtn}
      </div>
    `;
  }

  _stateForDetail(f) {
    // Cache full record in history.state when navigating to detail (US-003 AC1).
    // Bail out if the payload is too large (AC15).
    if (byteLength(f) > HISTORY_STATE_CAP_BYTES) return null;
    return f;
  }

  _onClick = (e) => {
    const target = e.target.closest('[data-action], a, button');
    if (!target) return;
    if (target.dataset.action === 'download') {
      e.preventDefault();
      const f = this._readForm();
      if (f && f.form_number) downloadFormFile(f.form_number);
    }
    // For "View more" anchors the global router click handler takes over.
  };
}

if (!customElements.get('form-card')) {
  customElements.define('form-card', FormCard);
}

export { FormCard };
