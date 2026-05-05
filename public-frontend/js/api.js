/*
 * Same-origin API client for the public-backend.
 *
 * Responsibilities:
 *  - Build absolute paths against API_BASE (always relative — US-001 AC14).
 *  - Honour `If-None-Match` revalidation (US-001 AC13).
 *  - Surface RFC 7807 problem+json detail strings (US-014 AC13).
 *  - Distinguish 429, 5xx, network, and abort cases for the UI (US-006).
 *  - Use a per-request AbortController; never auto-retry server errors.
 *
 * No new dependencies. Pure fetch().
 */

import { API_BASE } from './constants.js';

const _etagCache = new Map();   // url -> { etag, body }

export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'unknown', detail = '' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;       // 'rate-limit' | 'server' | 'client' | 'network' | 'abort' | 'unknown'
    this.detail = detail;
  }
}

function _classify(status) {
  if (status === 429) return 'rate-limit';
  if (status >= 500) return 'server';
  if (status >= 400) return 'client';
  return 'unknown';
}

/**
 * Fetch JSON with ETag revalidation.
 * Returns either the parsed JSON or, on a 304, the previously cached body.
 *
 * @param {string} path — path under API_BASE (or absolute starting with /)
 * @param {object} [opts]
 * @param {AbortSignal} [opts.signal]
 * @param {boolean} [opts.useEtag=true]
 */
export async function fetchJson(path, opts = {}) {
  const url = path.startsWith('/api/') ? path : `${API_BASE}${path}`;
  const headers = { 'Accept': 'application/json' };
  const useEtag = opts.useEtag !== false;
  const cached = useEtag ? _etagCache.get(url) : null;
  if (cached && cached.etag) {
    headers['If-None-Match'] = cached.etag;
  }

  let res;
  try {
    res = await fetch(url, { headers, credentials: 'omit', signal: opts.signal });
  } catch (err) {
    if (err && err.name === 'AbortError') {
      throw new ApiError('Request was cancelled', { kind: 'abort' });
    }
    throw new ApiError('Network failure', { kind: 'network' });
  }

  if (res.status === 304 && cached) {
    return { data: cached.body, etag: cached.etag, fromCache: true };
  }

  if (!res.ok) {
    let detail = '';
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/problem+json') || ct.includes('application/json')) {
      try { const body = await res.json(); detail = body && (body.detail || body.title) || ''; } catch { /* ignore */ }
    }
    throw new ApiError(detail || `Request failed (${res.status})`, {
      status: res.status,
      kind: _classify(res.status),
      detail,
    });
  }

  let data = null;
  if (res.status !== 204) {
    try { data = await res.json(); } catch {
      throw new ApiError('Malformed JSON response', { status: res.status, kind: 'server' });
    }
  }
  const etag = res.headers.get('etag');
  if (useEtag && etag) _etagCache.set(url, { etag, body: data });
  return { data, etag, fromCache: false };
}

/**
 * Fire-and-forget download. Browser handles the binary; we just navigate.
 * Implemented via a hidden anchor so middle/Cmd-click and keyboard activation
 * all work consistently (US-004 AC11).
 */
export function downloadFormFile(formNumber) {
  if (!formNumber) return;
  const a = document.createElement('a');
  a.href = `${API_BASE}/forms/${encodeURIComponent(formNumber)}/file`;
  a.rel = 'noopener';
  // Let the server set Content-Disposition; the browser will name the file.
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** Test-only: clear the in-memory ETag cache. */
export function _clearEtagCache() { _etagCache.clear(); }
