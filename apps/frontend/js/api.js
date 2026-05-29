// frontend/js/api.js
import { API_BASE, AUTH_STORAGE_ACCESS, AUTH_STORAGE_REFRESH, AUTH_STORAGE_USER } from './constants.js';
import { setCurrentUser } from './state.js';
import { tryRefreshToken } from './token-refresh.js';

let _authInterceptorInstalled = false;
// Prevents duplicate session-expired events when multiple concurrent requests
// all fail after a refresh. Reset when a new session starts.
let _sessionExpiredDispatched = false;

window.addEventListener('auth:session-started', () => {
  _sessionExpiredDispatched = false;
});

function _getAccessToken() {
  return localStorage.getItem(AUTH_STORAGE_ACCESS) || '';
}

function _clearAuthSession() {
  localStorage.removeItem(AUTH_STORAGE_ACCESS);
  // FEAT-0020 migration safeguard: clear any legacy refresh-token value.
  localStorage.removeItem(AUTH_STORAGE_REFRESH);
  localStorage.removeItem(AUTH_STORAGE_USER);
  setCurrentUser(null);
  // Notify the rest of the app that the session was cleared
  window.dispatchEvent(new CustomEvent('auth:session-cleared'));
}

export function installAuthFetchInterceptor() {
  if (_authInterceptorInstalled) return;

  const originalFetch = window.fetch.bind(window);

  window.fetch = async function (input, init = {}) {
    const requestUrl = typeof input === 'string' ? input : input.url;
    const isApiRequest = requestUrl.includes('/api/v1/');
    const isAuthRequest = requestUrl.includes('/api/v1/auth/');

    const headers = new Headers(init.headers || {});
    if (isApiRequest && !isAuthRequest && !headers.has('Authorization') && _getAccessToken()) {
      headers.set('Authorization', `Bearer ${_getAccessToken()}`);
    }

    const requestInit = { ...init, headers };
    let response = await originalFetch(input, requestInit);

    if (isApiRequest && response.status === 401 && !isAuthRequest && !requestInit.__retried) {
      const refreshed = await tryRefreshToken();
      if (refreshed) {
        const retryHeaders = new Headers(requestInit.headers || {});
        retryHeaders.set('Authorization', `Bearer ${_getAccessToken()}`);
        response = await originalFetch(input, {
          ...requestInit,
          __retried: true,
          headers: retryHeaders,
        });
      }

      if (response.status === 401 && !_sessionExpiredDispatched) {
        _sessionExpiredDispatched = true;
        _clearAuthSession();
        if (window.location.pathname !== '/callback') {
          window.dispatchEvent(new CustomEvent('auth:session-expired'));
          window.history.replaceState({}, '', '/');
        }
      }
    }

    return response;
  };

  _authInterceptorInstalled = true;
}
