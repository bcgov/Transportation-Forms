// frontend/js/token-refresh.js
// Shared token-refresh logic used by both api.js (fetch interceptor) and auth.js.
// Intentionally depends only on constants to avoid coupling the networking layer
// to auth UI concerns.

import { API_BASE, AUTH_STORAGE_ACCESS, AUTH_STORAGE_REFRESH } from './constants.js';

// Shared refresh promise — concurrent callers await the same request rather than
// each returning false and retrying with a stale token.
let _refreshPromise = null;

/**
 * Attempts a silent token refresh using the stored refresh token.
 * Returns true on success (new access token written to sessionStorage).
 *
 * Concurrent callers share a single in-flight request via a promise.
 */
export async function tryRefreshToken() {
  if (_refreshPromise) {
    return _refreshPromise;
  }

  const refreshToken = sessionStorage.getItem(AUTH_STORAGE_REFRESH) || '';
  if (!refreshToken) {
    return false;
  }

  _refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) {
        return false;
      }

      const payload = await response.json();
      sessionStorage.setItem(AUTH_STORAGE_ACCESS, payload.access_token);
      return true;
    } catch {
      return false;
    } finally {
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}
