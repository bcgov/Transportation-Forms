// frontend/js/token-refresh.js
// Shared token-refresh logic used by both api.js (fetch interceptor) and auth.js.
// Intentionally depends only on constants to avoid coupling the networking layer
// to auth UI concerns.
//
// FEAT-0020 / SEC-004: The refresh token lives in an HttpOnly cookie set by
// /auth/callback. JavaScript cannot read it, so we send `credentials: 'include'`
// to let the browser attach the cookie and let the backend recover it from the
// request. No refresh-token value is read from or sent through JavaScript.

import {
  API_BASE,
  AUTH_STORAGE_ACCESS,
  AUTH_STORAGE_REFRESH,
  AUTH_STORAGE_USER,
} from './constants.js';
import { setCurrentUser } from './state.js';
import { parseAuthorizationContext } from './authorization-context.js';

// Shared refresh promise — concurrent callers await the same request rather than
// each returning false and retrying with a stale token.
let _refreshPromise = null;

/**
 * Attempts a silent token refresh using the HttpOnly refresh-token cookie.
 * Returns true on success (new access token written to localStorage).
 *
 * Concurrent callers share a single in-flight request via a promise.
 */
export async function tryRefreshToken() {
  if (_refreshPromise) {
    return _refreshPromise;
  }

  _refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        return false;
      }

      const payload = await response.json();
      const accessToken = payload?.access_token;
      if (typeof accessToken !== 'string' || !accessToken) {
        return false;
      }

      const meResponse = await fetch(`${API_BASE}/auth/me`, {
        method: 'GET',
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (!meResponse.ok) {
        return false;
      }

      const user = await meResponse.json();
      if (!parseAuthorizationContext(user)) {
        localStorage.removeItem(AUTH_STORAGE_ACCESS);
        localStorage.removeItem(AUTH_STORAGE_USER);
        setCurrentUser(null);
        window.dispatchEvent(new CustomEvent('auth:session-cleared'));
        return false;
      }

      localStorage.setItem(AUTH_STORAGE_ACCESS, accessToken);
      localStorage.setItem(AUTH_STORAGE_USER, JSON.stringify(user));
      // FEAT-0020 migration safeguard: ensure any legacy refresh token value
      // left in localStorage from a previous build is removed.
      localStorage.removeItem(AUTH_STORAGE_REFRESH);
      setCurrentUser(user);
      window.dispatchEvent(new CustomEvent('auth:authorization-refreshed'));
      return true;
    } catch {
      return false;
    } finally {
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}
