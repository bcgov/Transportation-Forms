// frontend/js/auth.js
// AuthService — all OIDC/Keycloak authentication logic extracted from index.html.
//
// Demo-mode shortcut (development only):
//   When the backend is started with AUTH_DEMO_MODE=true, it accepts
//   "Authorization: Bearer demo-token" and returns a pre-built admin TokenData.
//   To use it in the browser, run in the console BEFORE page load:
//     localStorage.setItem('tf_access_token', 'demo-token');
//   initializeAuth() will then call /auth/me with that token and receive a
//   real user object back — no special frontend branching required.

import { API_BASE, AUTH_STORAGE_ACCESS, AUTH_STORAGE_REFRESH, AUTH_STORAGE_USER, ROUTES } from './constants.js';
import { showAlert } from './utils.js';
import { getCurrentUser, setCurrentUser, isAuthInitialized, setAuthInitialized } from './state.js';
import { tryRefreshToken } from './token-refresh.js';

export { tryRefreshToken };

// ─── Session-expired event ────────────────────────────────────────────────────
// api.js dispatches 'auth:session-expired' when a 401 cannot be recovered via
// refresh. Listen here to ensure signOut() clears state and navigates home.
window.addEventListener('auth:session-expired', () => {
  _clearAuthSession();

  const currentPath = window.location.pathname + window.location.search;
  if (currentPath !== ROUTES.HOME && currentPath !== ROUTES.CALLBACK) {
    sessionStorage.setItem('tf_return_url', currentPath);
  }

  showAlert('Your session has expired. Please sign in again.', 'warning');
  if (window.location.pathname !== ROUTES.HOME) {
    window.history.replaceState({}, '', ROUTES.HOME);
    // Signal other modules that route needs re-evaluation
    window.dispatchEvent(new CustomEvent('auth:navigate-home'));
  }
});

// ─── Cross-tab storage event ──────────────────────────────────────────────────
window.addEventListener('storage', (event) => {
  if (event.key === AUTH_STORAGE_ACCESS) {
    if (!event.newValue && event.oldValue) {
      // The token was removed in another tab.
      _clearAuthSession();
      if (window.location.pathname !== ROUTES.HOME) {
        showAlert('You have been signed out in another tab.', 'info');
        window.history.replaceState({}, '', ROUTES.HOME);
        window.dispatchEvent(new CustomEvent('auth:navigate-home'));
      }
    } else if (event.newValue && !event.oldValue) {
      // User logged in from another tab, reload to fetch correct state and context
      window.location.reload();
    }
  }
});

// ─── Internal helpers ─────────────────────────────────────────────────────────

// FEAT-0020 / SEC-004: The refresh token now lives in an HttpOnly cookie set
// by the backend; it is intentionally NOT readable from JavaScript. The legacy
// localStorage key is cleared on every auth-state transition below as a
// migration safeguard so any value left over from a previous deploy cannot
// continue to be exposed.

function _saveAuthSession(accessToken, refreshToken, user) {
  localStorage.setItem(AUTH_STORAGE_ACCESS, accessToken);
  // FEAT-0020: Do NOT persist the refresh token in localStorage. It is
  // delivered to the browser as an HttpOnly cookie by /auth/callback and is
  // not (and must not be) accessible to JavaScript. Remove any legacy value.
  localStorage.removeItem(AUTH_STORAGE_REFRESH);
  localStorage.setItem(AUTH_STORAGE_USER, JSON.stringify(user || {}));
  setCurrentUser(user || null);
  window.dispatchEvent(new CustomEvent('auth:session-started'));
  updateAuthUi();
}

function _clearAuthSession() {
  localStorage.removeItem(AUTH_STORAGE_ACCESS);
  // FEAT-0020 migration safeguard: clear any legacy refresh token value.
  localStorage.removeItem(AUTH_STORAGE_REFRESH);
  localStorage.removeItem(AUTH_STORAGE_USER);
  setCurrentUser(null);
  updateAuthUi();
}

// ─── Exported auth API ────────────────────────────────────────────────────────

/**
 * Returns the stored access token, or an empty string if none exists.
 */
export function getAuthToken() {
  return localStorage.getItem(AUTH_STORAGE_ACCESS) || '';
}

/**
 * Returns true when an access token is present in localStorage.
 */
export function isAuthenticated() {
  return Boolean(getAuthToken());
}

/**
 * Returns true when the current user has the "admin" role.
 */
export function isAdminUser() {
  const user = getCurrentUser();
  const roles = Array.isArray(user?.roles) ? user.roles : [];
  return roles.some(role => String(role || '').toLowerCase() === 'admin');
}

/**
 * Returns true when the current user has at least one portal role assigned.
 * Used to decide whether to show the staff-facing dashboard vs. the public list.
 */
export function hasPortalRoles() {
  const user = getCurrentUser();
  const roles = Array.isArray(user?.roles) ? user.roles : [];
  return roles.length > 0;
}

/**
 * Returns true when the current user's JWT permissions array contains the
 * specified granular permission string (e.g. 'form:approve').
 *
 * @param {string} permission  The exact permission string to check.
 * @returns {boolean}
 */
export function hasPermission(permission) {
  const user = getCurrentUser();
  const permissions = Array.isArray(user?.permissions) ? user.permissions : [];
  return permissions.includes(permission);
}

/**
 * Validates the stored access token against /auth/me, attempting a token
 * refresh on 401. Clears the session if validation ultimately fails.
 *
 * Guards against double-initialisation via isAuthInitialized() / setAuthInitialized().
 */
export async function initializeAuth() {
  if (isAuthInitialized()) {
    return;
  }

  const accessToken = getAuthToken();
  if (!accessToken) {
    _clearAuthSession();
    setAuthInitialized(true);
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/auth/me`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    if (response.ok) {
      const user = await response.json();
      setCurrentUser(user);
      localStorage.setItem(AUTH_STORAGE_USER, JSON.stringify(user));
      setAuthInitialized(true);
      return;
    }

    if (response.status === 401) {
      const refreshed = await tryRefreshToken();
      if (refreshed) {
        const meResponse = await fetch(`${API_BASE}/auth/me`, {
          method: 'GET',
          headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (meResponse.ok) {
          const user = await meResponse.json();
          setCurrentUser(user);
          localStorage.setItem(AUTH_STORAGE_USER, JSON.stringify(user));
          setAuthInitialized(true);
          return;
        }
      }
    }

    _clearAuthSession();
  } catch (error) {
    console.error('Auth initialization failed:', error);
    _clearAuthSession();
  } finally {
    setAuthInitialized(true);
  }
}

/**
 * Fetches a Keycloak authorization URL from the backend and redirects the
 * browser to the Keycloak login page.
 */
export async function startLogin() {
  try {
    const frontendRedirectUri = window.location.origin + ROUTES.CALLBACK;
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ frontend_redirect_uri: frontendRedirectUri }),
    });

    if (!response.ok) {
      throw new Error('Failed to initiate sign-in');
    }

    const payload = await response.json();
    if (!payload.authorization_url) {
      throw new Error('Authorization URL missing from response');
    }

    window.location.href = payload.authorization_url;
  } catch (error) {
    showAlert('Unable to start sign-in flow. Check Keycloak configuration.', 'danger');
  }
}

/**
 * Handles the OIDC authorization_code callback at /callback.
 * Reads `code` and `state` from the query string, exchanges them for tokens,
 * and persists the session. Navigates to dashboard or home depending on roles.
 *
 * Callers should invoke routeHandler() after this function completes (it
 * dispatches 'auth:callback-complete' so the router can react without a direct
 * dependency).
 */
export async function handleAuthCallback() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const state = params.get('state');

  if (!code || !state) {
    showAlert('Invalid authentication callback.', 'danger');
    window.history.replaceState({}, '', ROUTES.HOME);
    window.dispatchEvent(new CustomEvent('auth:navigate-home'));
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/auth/callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ code, state }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Authentication callback failed');
    }

    const payload = await response.json();
    _saveAuthSession(payload.access_token, payload.refresh_token, payload.user);
    showAlert('Signed in successfully.', 'success');

    let dest = hasPortalRoles() ? ROUTES.DASHBOARD : ROUTES.HOME;
    const returnUrl = sessionStorage.getItem('tf_return_url');
    if (returnUrl) {
      sessionStorage.removeItem('tf_return_url');
      if (hasPortalRoles()) {
        dest = returnUrl;
      }
    }

    window.history.replaceState({}, '', dest);
    window.dispatchEvent(new CustomEvent('auth:callback-complete'));
  } catch (error) {
    console.error('Auth callback failed:', error);
    _clearAuthSession();
    showAlert('Sign-in failed. Please try again.', 'danger');
    window.history.replaceState({}, '', ROUTES.HOME);
    window.dispatchEvent(new CustomEvent('auth:navigate-home'));
  }
}

/**
 * Calls the backend logout endpoint (to invalidate the Keycloak session and
 * clear the HttpOnly refresh-token cookie), clears local session state, and
 * navigates to the home/welcome page.
 *
 * FEAT-0020: The refresh token is no longer kept in localStorage; the backend
 * reads it from the HttpOnly cookie and clears that cookie on the response.
 */
export async function signOut() {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAuthToken()}`,
      },
      credentials: 'include',
      body: JSON.stringify({}),
    });
  } catch (error) {
    console.error('Logout request failed:', error);
  }

  _clearAuthSession();
  showAlert('Signed out successfully.', 'success');
  window.history.replaceState({}, '', ROUTES.HOME);
  window.dispatchEvent(new CustomEvent('auth:navigate-home'));
}

/**
 * Syncs all auth-related UI elements (navbar user pill, nav visibility,
 * sign-out button, admin links) to the current authentication state.
 */
export function updateAuthUi() {
  const signOutBtn = document.getElementById('signOutBtn');
  const authUserDisplay = document.getElementById('authUserDisplay');
  const authUserInitials = document.getElementById('authUserInitials');
  const authDropdownContainer = document.getElementById('authDropdownContainer');
  const navDropdownContainer = document.getElementById('navMenuToggle')?.closest('.dropdown');
  const navAccordion = document.getElementById('navAccordion');
  const adminAccordionItem = document.querySelector('#accAdmin')?.closest('.accordion-item');

  if (isAuthenticated()) {
    if (signOutBtn) signOutBtn.style.display = 'block';

    const user = getCurrentUser();
    const displayName = user?.name || user?.email || 'Signed in';
    const initials = displayName
      .split(' ')
      .filter(Boolean)
      .map(w => w[0])
      .join('')
      .slice(0, 2)
      .toUpperCase();

    if (authUserInitials) authUserInitials.textContent = initials || '?';
    if (authUserDisplay) authUserDisplay.textContent = displayName;
    if (authDropdownContainer) authDropdownContainer.style.display = '';

    if (hasPortalRoles()) {
      if (navDropdownContainer) navDropdownContainer.style.display = '';
      const mainNavLinks = document.getElementById('mainNavLinks');
      if (mainNavLinks) mainNavLinks.style.display = '';
      if (navAccordion) navAccordion.style.display = '';
      if (adminAccordionItem) adminAccordionItem.style.display = isAdminUser() ? '' : 'none';
    } else {
      if (navDropdownContainer) navDropdownContainer.style.display = 'none';
      const mainNavLinks = document.getElementById('mainNavLinks');
      if (mainNavLinks) mainNavLinks.style.display = 'none';
      if (navAccordion) navAccordion.style.display = 'none';
    }
  } else {
    if (signOutBtn) signOutBtn.style.display = 'none';
    if (authUserInitials) authUserInitials.textContent = '?';
    if (authUserDisplay) authUserDisplay.textContent = '';
    if (authDropdownContainer) authDropdownContainer.style.display = 'none';
    if (navDropdownContainer) navDropdownContainer.style.display = 'none';
    const mainNavLinks = document.getElementById('mainNavLinks');
    if (mainNavLinks) mainNavLinks.style.display = 'none';
    if (navAccordion) navAccordion.style.display = 'none';
  }
}
