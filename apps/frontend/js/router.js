// frontend/js/router.js
// SPA client-side router — extracted and modularised from index.html.
//
// Route lifecycle:
//   initRouter() → popstate / click delegation → routeHandler(path)
//     → auth/admin guards → dynamic import of view module → updateNavbar()

import { ROUTES } from './constants.js';
import { showAlert, showSpinner } from './utils.js';
import { getCurrentUser, isAuthInitialized } from './state.js';
import {
  isAuthenticated,
  isAdminUser,
  hasPortalRoles,
  hasPermission,
  updateAuthUi,
  handleAuthCallback,
  startLogin,
} from './auth.js';

// ─── Module-private state ─────────────────────────────────────────────────────
let _currentRoute = null;
let _routeParams = {};

// ─── Public getters ───────────────────────────────────────────────────────────

export function getCurrentRoute() {
  return _currentRoute;
}

export function getRouteParams() {
  return { ..._routeParams };
}

// ─── Navigation ───────────────────────────────────────────────────────────────

/**
 * Pushes `path` onto the history stack and runs the route handler.
 * Unauthenticated navigation to any protected path is silently redirected to HOME.
 */
export async function navigateTo(path, params = {}) {
  if (!isAuthenticated() && path !== ROUTES.CALLBACK) {
    window.history.pushState({}, '', ROUTES.HOME);
    await routeHandler(ROUTES.HOME);
    return;
  }
  window.history.pushState({}, '', path);
  await routeHandler(path, params);
}

// ─── View helpers ─────────────────────────────────────────────────────────────

/**
 * Loose UUID shape check for the FEAT-0027 US-008 deep-link. Anything that
 * fails this test collapses into the same "not found / no permission" toast
 * as a 404 / 403 response so callers cannot distinguish the failure branches.
 */
function _isUuidLike(value) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

/**
 * Hides every top-level view element by ID so that only the active view
 * needs to set itself visible.
 */
export function hideAllViews() {
  const viewIds = [
    'welcomeView',
    'dashboardView',
    'listView',
    'createView',
    'reserveView',
    'myReservationsView',
    'approvalsView',
    'reservationDetailView',
    'rolesView',
    'roleDetailView',
    'usersView',
    'userDetailView',
    'accessRequestsView',
    'businessAreasView',
    'businessAreaCreateView',
    'businessAreaDetailView',
    'prefixesView',
    'prefixCreateView',
    'prefixDetailView',
    'cmsPageNewView',
    'cmsPagesListView',
    'cmsPageEditView',
    'cmsRedirectsView',
  ];
  for (const id of viewIds) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  }
}

// ─── Navbar ───────────────────────────────────────────────────────────────────

/** Map of route names → nav-link element IDs. */
const _ROUTE_LINK_MAP = {
  dashboard: 'dashboardLink',
  list: 'manageFormsLink',
  create: 'createFormLink',
  edit: 'createFormLink',
  reserve: 'reserveNumberLink',
  'my-reservations': 'myReservationsLink',
  approvals: 'approvalsLink',
  roles: 'rolesLink',
  'role-detail': 'rolesLink',
  users: 'usersLink',
  'user-detail': 'usersLink',
  'access-requests': 'accessRequestsLink',
  'business-areas': 'businessAreasLink',
  prefixes: 'prefixesLink',
  'prefix-create': 'prefixesLink',
  'prefix-detail': 'prefixesLink',
  'cms-page-new': 'cmsPagesLink',
  'cms-pages-list': 'cmsPagesLink',
  'cms-page-edit': 'cmsPagesLink',
  'cms-redirects': 'cmsRedirectsLink',
};

/**
 * Removes the active class from all navbar links, then re-applies it to
 * the link that corresponds to `_currentRoute`.
 *
 * @param {object|null} user - Current user (reserved for future use).
 */
export function updateNavbar(user) {
  document
    .querySelectorAll('#navbarColor01 .nav-link, #navbarColor01 .dropdown-item')
    .forEach(link => link.classList.remove('active'));

  const linkId = _ROUTE_LINK_MAP[_currentRoute];
  if (linkId) {
    const el = document.getElementById(linkId);
    if (el) el.classList.add('active');
  }
}

// ─── Admin route guard ────────────────────────────────────────────────────────

/**
 * Returns true when `path` requires admin privileges.
 */
export function isAdminRoute(path) {
  return (
    path === ROUTES.ROLES ||
    path.startsWith('/roles/') ||
    path === ROUTES.USERS ||
    path.startsWith('/users/') ||
    path === ROUTES.ACCESS_REQUESTS ||
    path.startsWith('/access-requests/') ||
    path === ROUTES.BUSINESS_AREAS ||
    path.startsWith('/business-areas/') ||
    path === ROUTES.PREFIXES ||
    path === ROUTES.PREFIX_CREATE ||
    path.startsWith('/prefixes/') ||
    path === ROUTES.CMS_PAGES ||
    path === ROUTES.CMS_PAGE_NEW ||
    path.startsWith('/admin/cms/')
  );
}

// ─── Core route handler ───────────────────────────────────────────────────────

/**
 * Resolves `path` to a view, applying auth and admin guards.
 * View modules are lazily imported to avoid circular dependencies.
 */
export async function routeHandler(path, params = {}) {
  path = path ?? window.location.pathname;

  // Wait until auth initialisation has completed.
  if (!isAuthInitialized()) {
    return;
  }

  hideAllViews();

  // ── Unauthenticated guard ──────────────────────────────────────────────────
  if (!isAuthenticated() && path !== ROUTES.CALLBACK) {
    // FEAT-0027 US-008 AC9 — remember the deep-link target so the app can
    // resume there once the user completes the login flow. Uses the same
    // sessionStorage key already consumed by auth.js on callback.
    if (path && path !== ROUTES.HOME && path.startsWith('/forms/')) {
      try {
        sessionStorage.setItem('tf_return_url', path);
      } catch (_e) { /* ignore quota / private-mode errors */ }
    }
    _currentRoute = 'welcome';
    _routeParams = {};
    const { showWelcomeView } = await import('./views/welcome.js');
    await showWelcomeView();
    updateNavbar();
    return;
  }

  // ── Admin guard ───────────────────────────────────────────────────────────
  if (isAuthenticated() && isAdminRoute(path)) {
    // Business Area admin pages are accessible to non-admin users that hold
    // the matching backend permission. Mirror the API contract precisely so
    // the SPA never surfaces a page the API will subsequently 403:
    //   * /business-areas/new           → business_area:create
    //   * /business-areas, /business-areas/{id} → business_area:manage
    const isBusinessAreaCreateRoute = path === `${ROUTES.BUSINESS_AREAS}/new`;
    const isBusinessAreaListOrDetail =
      !isBusinessAreaCreateRoute &&
      (path === ROUTES.BUSINESS_AREAS || path.startsWith('/business-areas/'));

    const canCreateBA = hasPermission('business_area:create');
    const canManageBA = hasPermission('business_area:manage');

    // CMS admin pages (pages + redirects) are gated on ``cms:manage`` —
    // the same permission the backend requires (see ``routes/cms_pages.py``).
    // Users holding this permission (e.g. the ``content_editor`` role) must
    // be allowed through even without the full admin role.
    const isCmsRoute =
      path === ROUTES.CMS_PAGES ||
      path === ROUTES.CMS_PAGE_NEW ||
      path.startsWith('/admin/cms/');
    const canManageCms = hasPermission('cms:manage');

    const isAllowed =
      isAdminUser() ||
      (isBusinessAreaCreateRoute && canCreateBA) ||
      (isBusinessAreaListOrDetail && canManageBA) ||
      (isCmsRoute && canManageCms);

    if (!isAllowed) {
      showAlert('You do not have permission to access that page.', 'warning');
      window.history.replaceState({}, '', ROUTES.HOME);
      _currentRoute = 'list';
      _routeParams = {};
      const { showListView } = await import('./views/list.js');
      await showListView();
      updateNavbar();
      return;
    }
  }

  // ── Route dispatch ─────────────────────────────────────────────────────────

  if (path === ROUTES.HOME || path === '') {
    // Portal users land on the dashboard; public users see the forms list.
    if (hasPortalRoles()) {
      window.history.replaceState({}, '', ROUTES.DASHBOARD);
      await routeHandler(ROUTES.DASHBOARD);
      return;
    }
    _currentRoute = 'list';
    _routeParams = {};
    const { showListView } = await import('./views/list.js');
    await showListView();

  } else if (path === ROUTES.DASHBOARD) {
    // Non-portal users cannot access the dashboard.
    if (!hasPortalRoles()) {
      window.history.replaceState({}, '', ROUTES.HOME);
      await routeHandler(ROUTES.HOME);
      return;
    }
    _currentRoute = 'dashboard';
    _routeParams = {};
    const { showDashboardView } = await import('./views/dashboard.js');
    await showDashboardView();

  } else if (path === ROUTES.FORMS_LIST) {
    _currentRoute = 'list';
    _routeParams = {};
    const { showListView } = await import('./views/list.js');
    await showListView();

  } else if (path.startsWith('/forms/')) {
    // FEAT-0027 US-008 — deep-link `/forms/<form_uuid>` opens the Forms list
    // and auto-opens the View Details popup for that form. All failure branches
    // (invalid UUID, form does not exist, caller lacks form:read) surface the
    // SAME generic toast to avoid the information leak in CC-BR-05 / AC7 / AC8.
    const formId = path.replace('/forms/', '').replace(/\/$/, '');
    _currentRoute = 'list';
    _routeParams = { deepLinkFormId: formId };
    const { showListView } = await import('./views/list.js');
    await showListView();
    const { openFormViewPopup, DEEPLINK_DENIED_TOAST } =
      await import('./shared/form-view-popup.js');
    const { showNotification } = await import('./utils.js');
    if (!formId || !_isUuidLike(formId)) {
      showNotification(DEEPLINK_DENIED_TOAST, 'warning');
    } else {
      await openFormViewPopup({ formId });
    }

  } else if (path === ROUTES.CALLBACK) {
    // OIDC authorization_code callback — auth.js dispatches 'auth:callback-complete'
    // once tokens are exchanged; the listener below will then navigate to DASHBOARD.
    _currentRoute = 'callback';
    _routeParams = {};
    await handleAuthCallback();
    return; // navigation is driven by the auth:callback-complete event

  } else if (path === ROUTES.FORM_CREATE) {
    _currentRoute = 'create';
    _routeParams = {};
    const { showCreateView } = await import('./views/create.js');
    await showCreateView();

  } else if (path === ROUTES.RESERVE) {
    _currentRoute = 'reserve';
    _routeParams = {};
    const { showReserveView } = await import('./views/reserve.js');
    await showReserveView();

  } else if (path === ROUTES.MY_RESERVATIONS) {
    _currentRoute = 'my-reservations';
    _routeParams = {};
    const { showMyReservationsView } = await import('./views/my-reservations.js');
    await showMyReservationsView();

  } else if (path === ROUTES.APPROVALS) {
    _currentRoute = 'approvals';
    _routeParams = {};
    const { showApprovalsView } = await import('./views/approvals.js');
    await showApprovalsView();

  } else if (path === ROUTES.ROLES) {
    _currentRoute = 'roles';
    _routeParams = {};
    const { showRolesView } = await import('./views/roles.js');
    await showRolesView();

  } else if (path.startsWith('/roles/')) {
    const roleId = path.replace('/roles/', '');
    _currentRoute = 'role-detail';
    _routeParams = { roleId };
    const { showRoleDetailView } = await import('./views/roles.js');
    await showRoleDetailView(roleId);

  } else if (path === ROUTES.USERS) {
    _currentRoute = 'users';
    _routeParams = {};
    const { showUsersView } = await import('./views/users.js');
    await showUsersView();

  } else if (path.startsWith('/users/')) {
    const userId = path.replace('/users/', '');
    _currentRoute = 'user-detail';
    _routeParams = { userId };
    const { showUserDetailView } = await import('./views/users.js');
    await showUserDetailView(userId);

  } else if (path === ROUTES.ACCESS_REQUESTS || path.startsWith('/access-requests/')) {
    _currentRoute = 'access-requests';
    _routeParams = {};
    const { showAccessRequestsView } = await import('./views/access-requests.js');
    await showAccessRequestsView();

  } else if (path === ROUTES.BUSINESS_AREAS) {
    _currentRoute = 'business-areas';
    _routeParams = {};
    const { showBusinessAreasAdminView } = await import('./views/admin/business-areas.js');
    await showBusinessAreasAdminView();

  } else if (path.startsWith('/business-areas/')) {
    const areaId = path.replace('/business-areas/', '').replace(/\/$/, '');
    if (areaId && areaId === 'new') {
        _currentRoute = 'business-area-create';
        _routeParams = {};
        const { showBusinessAreaCreateView } = await import('./views/admin/business-areas.js');
        await showBusinessAreaCreateView();
    } else if (areaId) {
        _currentRoute = 'business-area-detail';
        _routeParams = { areaId };
        const { showBusinessAreaDetailView } = await import('./views/admin/business-areas.js');
        await showBusinessAreaDetailView(areaId);
    } else {
        // Trailing slash with no ID: treat as the list view.
        window.history.replaceState({}, '', ROUTES.BUSINESS_AREAS);
        _currentRoute = 'business-areas';
        _routeParams = {};
        const { showBusinessAreasAdminView } = await import('./views/admin/business-areas.js');
        await showBusinessAreasAdminView();
    }

  } else if (path.startsWith('/reservations/')) {
    const reservationId = path.replace('/reservations/', '');
    _currentRoute = 'reservation-detail';
    _routeParams = { reservationId };
    const { showReservationDetailView } = await import('./views/reservation-detail.js');
    await showReservationDetailView(reservationId, params.returnTo);

  } else if (path.startsWith('/edit/')) {
    const formId = path.replace('/edit/', '');
    _currentRoute = 'edit';
    _routeParams = { formId };
    const { showEditView } = await import('./views/create.js');
    await showEditView(formId);

  } else if (path === ROUTES.PREFIXES) {
    _currentRoute = 'prefixes';
    _routeParams = {};
    const { showPrefixesView } = await import('./views/prefixes.js');
    await showPrefixesView();

  } else if (path === ROUTES.PREFIX_CREATE) {
    _currentRoute = 'prefix-create';
    _routeParams = {};
    const { showPrefixCreateView } = await import('./views/prefixes.js');
    await showPrefixCreateView();

  } else if (path.startsWith('/prefixes/')) {
    const prefixId = path.replace('/prefixes/', '');
    if (prefixId && prefixId !== 'new') {
      _currentRoute = 'prefix-detail';
      _routeParams = { prefixId };
      const { showPrefixDetailView } = await import('./views/prefixes.js');
      await showPrefixDetailView(prefixId);
    }

  } else if (path === ROUTES.CMS_PAGE_NEW) {
    _currentRoute = 'cms-page-new';
    _routeParams = {};
    const { showCmsPageNewView } = await import('./views/admin/cms-page-new.js');
    await showCmsPageNewView();

  } else if (path === ROUTES.CMS_PAGES) {
    _currentRoute = 'cms-pages-list';
    _routeParams = {};
    const { showCmsPagesListView } = await import('./views/admin/cms-pages.js');
    await showCmsPagesListView();

  } else if (path === ROUTES.CMS_REDIRECTS) {
    _currentRoute = 'cms-redirects';
    _routeParams = {};
    const { showCmsRedirectsView } = await import('./views/admin/cms-redirects.js');
    await showCmsRedirectsView();

  } else if (path.startsWith('/admin/cms/pages/')) {
    const pageId = path.replace('/admin/cms/pages/', '');
    if (pageId && pageId !== 'new') {
      _currentRoute = 'cms-page-edit';
      _routeParams = { pageId };
      const { showCmsPageEditView } = await import('./views/admin/cms-page-edit.js');
      await showCmsPageEditView(pageId);
    }

  } else {
    // Unknown path — redirect to the appropriate root by role.
    const fallback = hasPortalRoles() ? ROUTES.DASHBOARD : ROUTES.HOME;
    window.history.replaceState({}, '', fallback);
    await routeHandler(fallback);
    return;
  }

  updateNavbar();
}

// ─── Router bootstrap ─────────────────────────────────────────────────────────

/**
 * Wires up all router event listeners and handles the initial page route.
 * Call once after auth has been initialised.
 */
export function initRouter() {
  // auth.js signals that the session has expired / user signed out → go home.
  window.addEventListener('auth:navigate-home', () => navigateTo(ROUTES.HOME));

  // auth.js signals that the OIDC callback exchange completed → resume at
  // the return URL (FEAT-0027 US-008 AC9) if auth.js has replaced the browser
  // URL with a stored deep-link, otherwise fall back to the dashboard.
  window.addEventListener('auth:callback-complete', () => {
    const currentPath = window.location.pathname;
    if (currentPath && currentPath !== ROUTES.HOME && currentPath !== ROUTES.CALLBACK) {
      routeHandler(currentPath);
    } else {
      navigateTo(ROUTES.DASHBOARD);
    }
  });

  // Browser back / forward buttons.
  window.addEventListener('popstate', () => routeHandler(window.location.pathname));

  // Intercept clicks on elements carrying a `data-route` attribute so that
  // inline onclick handlers are not needed in the HTML.
  // Also reads `data-return-to` so views like my-reservations can pass context
  // to the detail view (e.g. which page the back button should return to).
  document.addEventListener('click', e => {
    const link = e.target.closest('[data-route]');
    if (link) {
      e.preventDefault();
      const returnTo = link.dataset.returnTo;
      navigateTo(link.dataset.route, returnTo ? { returnTo } : {});
    }
  });

  // Evaluate the path the browser is currently showing.
  routeHandler(window.location.pathname);
}
