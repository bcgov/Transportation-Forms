// frontend/js/main.js
import { installAuthFetchInterceptor } from './api.js';
import { initializeAuth, updateAuthUi, signOut, startLogin } from './auth.js';
import { initRouter, routeHandler } from './router.js';
import { initSidebarNavigation } from './sidebar.js';

document.addEventListener('DOMContentLoaded', async () => {
  // 1. Install fetch interceptor FIRST (before any API calls)
  installAuthFetchInterceptor();

  // 2. Wire up router event listeners (popstate, data-route clicks).
  //    The initial routeHandler() call inside initRouter() returns early because
  //    auth has not been initialised yet (isAuthInitialized() === false).
  initSidebarNavigation();
  initRouter();

  // 3. Global delegated action handler for auth buttons (sign-out, start-login).
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-action="sign-out"]')) {
      e.preventDefault();
      signOut();
    } else if (e.target.closest('[data-action="start-login"]')) {
      e.preventDefault();
      startLogin();
    }
  });

  // 4. Initialize auth (checks stored token, fetches /auth/me, sets currentUser)
  await initializeAuth();

  // 5. Update navbar/UI with current auth state
  updateAuthUi();

  // 6. Now that auth is initialised, run the initial route handler for real.
  await routeHandler(window.location.pathname);
});
