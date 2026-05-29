# Frontend Developers Guide

This document is the reference for agents and developers working on the Transportation Forms frontend. It describes the modular ES Module architecture, conventions, and step-by-step instructions for common tasks.

---

## Architecture Overview

```
frontend/
├── index.html                  ← HTML shell only. No inline JS. One <script type="module">.
├── css/main.css                ← Shared BC Gov stylesheet. Do not add inline styles.
├── assets/                     ← Static assets (logo etc.)
├── archived/form_demo.html     ← Dead prototype. Do not serve or edit.
└── js/
    ├── main.js                 ← Entry point. DOMContentLoaded bootstrap only.
    ├── constants.js            ← ALL magic strings. Import from here, never hardcode.
    ├── utils.js                ← ALL reusable DOM/format helpers. One canonical copy.
    ├── state.js                ← Cross-module shared state (currentUser, isAuthInitialized).
    ├── api.js                  ← Fetch interceptor (JWT attach + 401 retry).
    ├── auth.js                 ← OIDC auth: login, callback, refresh, signOut, guards.
    ├── token-refresh.js        ← Shared token-refresh logic (used by api.js + auth.js).
    ├── router.js               ← SPA router: navigateTo, routeHandler, auth guards.
    ├── validation.js           ← Form field error helpers (showFieldError etc.).
    └── views/
        ├── welcome.js          ← Unauthenticated landing screen.
        ├── dashboard.js        ← /dashboard — stats overview.
        ├── list.js             ← Shim → forms-list.js
        ├── forms-list.js       ← /forms — search, filter, paginate.
        ├── create.js           ← Shim → forms-create.js
        ├── forms-create.js     ← /create and /edit/:id — create/edit a form.
        ├── keywords.js         ← Keyword tag widget (used by forms-create).
        ├── file-upload.js      ← PDF drag-and-drop upload widget (used by forms-create).
        ├── business-areas.js   ← Business area combobox + filter tags widget.
        ├── reserve.js          ← Shim → reservation-form.js
        ├── reservation-form.js ← /reserve — form number reservation wizard.
        ├── my-reservations.js  ← /my-reservations — current user's reservations.
        ├── approvals.js        ← /approvals — reviewer approval queue.
        ├── reservation-detail.js ← /reservations/:id — reservation detail.
        ├── roles.js            ← Shim → admin/roles.js
        ├── users.js            ← Shim → admin/users.js
        ├── access-requests.js  ← Shim → admin/access-requests.js
        └── admin/
            ├── roles.js        ← /roles — admin role management.
            ├── users.js        ← /users — admin user management.
            └── access-requests.js ← /access-requests — admin access request queue
                                     + user-facing "request access" flow.
```

### What are shims?
`views/list.js`, `views/create.js`, `views/reserve.js`, `views/roles.js`, `views/users.js`, and `views/access-requests.js` are thin re-export files. The router imports from short predictable paths (`./views/list.js`), but the real modules have descriptive names (`forms-list.js`, `forms-create.js` etc.). The shims bridge the gap without renaming the real modules.

---

## Bootstrap Sequence (`main.js`)

```
DOMContentLoaded
  │
  ├─ installAuthFetchInterceptor()   ← patches window.fetch FIRST
  ├─ initRouter()                    ← wires popstate, data-route clicks, auth events
  │                                    (exits early because isAuthInitialized=false)
  ├─ await initializeAuth()          ← calls GET /auth/me, sets currentUser in state
  ├─ updateAuthUi()                  ← syncs navbar login/logout buttons
  └─ await routeHandler(pathname)    ← handles the actual initial route
```

---

## How to Add a New Route/View

### Step 1 — Add the route constant (`constants.js`)

```js
export const ROUTES = {
  // ... existing routes ...
  MY_NEW_FEATURE: '/my-feature',
};
```

### Step 2 — Add a `<div>` view container to `index.html`

Add it alongside the other view divs (they are all hidden by default via `style="display:none"`):

```html
<div id="myFeatureView" style="display:none">
  <!-- Static HTML structure for the view -->
</div>
```

### Step 3 — Create the view module (`views/my-feature.js`)

```js
// frontend/js/views/my-feature.js
import { API_BASE, ROUTES } from '../constants.js';
import { escapeHtml, showAlert, showSpinner, getErrorDetail } from '../utils.js';
import { getCurrentUser } from '../state.js';

// Module-private state (never exported as raw variables)
let _someLocalState = null;

// Listener guard — prevents duplicate event bindings on re-navigation
let _listenersAttached = false;

/**
 * Entry point called by the router.
 * Shows the view, wires events once, loads data.
 */
export async function showMyFeatureView() {
  // 1. Hide all other views and show this one
  const { hideAllViews } = await import('../router.js');
  hideAllViews();
  document.getElementById('myFeatureView').style.display = 'block';
  document.title = 'My Feature - BC Gov';

  // 2. Bind events once via delegation (no onclick attributes)
  if (!_listenersAttached) {
    _listenersAttached = true;
    document.getElementById('myFeatureView').addEventListener('click', _handleClick);
  }

  // 3. Load data
  await _loadData();
}

function _handleClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  if (btn.dataset.action === 'do-something') _doSomething();
}

async function _loadData() {
  showSpinner('#myFeatureView .spinner', true);
  try {
    const res = await fetch(`${API_BASE}/my-endpoint`);
    if (!res.ok) throw new Error(await getErrorDetail(res, 'Failed to load'));
    const data = await res.json();
    _render(data);
  } catch (err) {
    showAlert(err.message, 'danger');
  } finally {
    showSpinner('#myFeatureView .spinner', false);
  }
}

function _render(data) {
  document.getElementById('myFeatureContent').innerHTML = data.items
    .map(item => `<p>${escapeHtml(item.name)}</p>`)
    .join('');
}
```

### Step 4 — Register the route in `router.js`

In the route dispatch block inside `routeHandler()`:

```js
} else if (path === ROUTES.MY_NEW_FEATURE) {
  _currentRoute = 'my-feature';
  _routeParams = {};
  const { showMyFeatureView } = await import('./views/my-feature.js');
  await showMyFeatureView();
```

Then add it to `hideAllViews()`:

```js
const viewIds = [
  // ... existing ids ...
  'myFeatureView',
];
```

And add it to the `_ROUTE_LINK_MAP` if there is a navbar link:

```js
const _ROUTE_LINK_MAP = {
  // ... existing entries ...
  'my-feature': 'myFeatureLinkId',
};
```

### Step 5 — Add a nav link in `index.html` (if needed)

```html
<a class="nav-link" data-route="/my-feature" href="/my-feature" id="myFeatureLinkId">
  My Feature
</a>
```

No `onclick`. The router's delegated listener on `[data-route]` handles navigation automatically.

### Step 6 — For admin-only routes, add a guard

In `router.js`, `isAdminRoute()`:

```js
export function isAdminRoute(path) {
  return (
    // ... existing checks ...
    path === ROUTES.MY_NEW_FEATURE ||
    path.startsWith('/my-feature/')
  );
}
```

---

## Where to Put Things

### Constants → `constants.js`
Any string or value used in more than one place:
- API base URL
- `sessionStorage` key names
- Route paths
- Status label maps

```js
// ✅ Correct
import { API_BASE, ROUTES, STATUS_LABELS } from '../constants.js';

// ❌ Wrong — never hardcode
fetch('/api/v1/forms')
navigateTo('/dashboard')
```

### Utility functions → `utils.js`
Any reusable display, format, or DOM helper:

| Function | Purpose |
|---|---|
| `escapeHtml(text)` | **Always** use when inserting user/API data into innerHTML |
| `formatDateTime(value)` | ISO string → human-readable local datetime |
| `showAlert(message, type)` | Page-level Bootstrap alert (`'success'`, `'danger'`, `'warning'`, `'info'`) |
| `showNotification(message, type)` | Toast notification |
| `showSpinner(selector, show)` | Show/hide a loading spinner by CSS selector |
| `getErrorDetail(response, fallback)` | Extract `detail` field from API error response |
| `parsePermissions(value)` | Parse comma-separated permission strings |
| `formatReservationStatus(status)` | Status code → human label |
| `getFormNumberDisplay(form)` | Format a form's number for display |

Do NOT redefine any of these in a view module. Import them.

### Shared state → `state.js`
Only two values live here (intentionally minimal):

| Export | Type | Set by | Read by |
|---|---|---|---|
| `getCurrentUser()` / `setCurrentUser(u)` | `object \| null` | `auth.js` | everywhere |
| `isAuthInitialized()` / `setAuthInitialized(b)` | `boolean` | `auth.js` | `router.js` |

Do NOT add new state here unless it is genuinely needed by 3+ unrelated modules.

### Module-private state → inside the view file
State used only within one module is a `let` variable at the top of that file, **not exported**:

```js
// ✅ Correct — private to this module
let _currentSkip = 0;
let _listenersAttached = false;

// ❌ Wrong — raw variable export leaks state
export let currentSkip = 0;
```

If another module needs to read it, export a getter function:

```js
export function getCurrentSkip() { return _currentSkip; }
```

### Form validation → `validation.js`

```js
import { showFieldError, clearFieldError, clearAllFieldErrors, showValidationErrors } from '../validation.js';

// Show a single field error
showFieldError('title', 'Title is required');

// Clear all field errors (call before re-validating)
clearAllFieldErrors();

// Handle a Pydantic validation error array from the API
showValidationErrors(errorDetail);
```

---

## Event Handling Rules

**Never use `onclick="..."` attributes.** ES Module functions are not on `window`.

### Static HTML elements (nav, fixed buttons)
Use `data-route` or `data-action` attributes, bound once in the owning module:

```html
<!-- Navigation -->
<a data-route="/dashboard" href="/dashboard">Dashboard</a>

<!-- Action button -->
<button data-action="sign-out">Sign Out</button>
```

```js
// The router handles all [data-route] clicks automatically.
// For [data-action], bind in the view's init:
document.getElementById('myView').addEventListener('click', e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  if (btn.dataset.action === 'sign-out') signOut();
});
```

### Dynamically generated HTML (cards, table rows)
Use a **single delegated listener** on the stable container, not per-element listeners:

```js
// ✅ One listener on the container
document.getElementById('itemList').addEventListener('click', e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const id = btn.dataset.id;
  if (btn.dataset.action === 'edit') openEditModal(id);
  if (btn.dataset.action === 'delete') confirmDelete(id);
});

// The rendered HTML uses data attributes, no onclick:
container.innerHTML = items.map(item => `
  <button data-action="edit" data-id="${escapeHtml(item.id)}">Edit</button>
  <button data-action="delete" data-id="${escapeHtml(item.id)}">Delete</button>
`).join('');
```

### Prevent duplicate listeners

Use a **boolean guard** when the container element itself persists (shown/hidden) and listeners only need to be attached once per page lifetime:

```js
let _listenersAttached = false;
if (!_listenersAttached) {
  _listenersAttached = true;
  el.addEventListener('click', handler);
}
```

Use an **`AbortController`** when the container's innerHTML is replaced on every visit (cards, tables, dynamically rendered lists). Each render must replace the previous listeners or they stack:

```js
// ✅ Required when innerHTML is replaced on each load
let _listenerController = null;
if (_listenerController) _listenerController.abort();
_listenerController = new AbortController();
el.addEventListener('click', handler, { signal: _listenerController.signal });
```

> **Rule of thumb:** if you call `container.innerHTML = ...` inside a function that runs on every page visit, use `AbortController` on the container's listener.

---

## API Calls

The fetch interceptor in `api.js` automatically attaches `Authorization: Bearer <token>` to all requests to `/api/v1/*`. You do not need to set auth headers manually.

```js
// ✅ Just fetch — the interceptor handles auth
const res = await fetch(`${API_BASE}/forms?skip=0&limit=25`);
if (!res.ok) {
  const msg = await getErrorDetail(res, 'Failed to load forms');
  showAlert(msg, 'danger');
  return;
}
const data = await res.json();
```

The interceptor also handles 401 → token refresh → retry automatically. If refresh fails, it dispatches `auth:session-expired` and clears the session.

---

## Auth Guards

```js
import { isAuthenticated, isAdminUser, hasPortalRoles } from '../auth.js';
import { getCurrentUser } from '../state.js';

isAuthenticated()   // true if a valid access token exists
isAdminUser()       // true if user has 'admin' role
hasPortalRoles()    // true if user has any internal portal role (staff, admin, reviewer)
getCurrentUser()    // full user object or null
```

The router enforces guards automatically for registered routes. Inside a view, use these for conditional rendering (e.g. show/hide edit buttons).

### Navigation with back-context (`data-return-to`)

When a card or link navigates to a detail view that has a back button, add `data-return-to` alongside `data-route`. The router reads it and passes it to the view as `params.returnTo`:

```html
<div data-route="/reservations/${escapeHtml(r.id)}"
     data-return-to="my-reservations">
  ...
</div>
```

The detail view receives it as the second argument from the router:

```js
// In routeHandler (router.js):
await showReservationDetailView(reservationId, params.returnTo);

// In the view:
export async function showReservationDetailView(reservationId, returnRoute) {
  _detailReturnRoute = returnRoute || 'approvals'; // safe default
  ...
}
```

Supported `returnTo` values must be handled in the view's back-navigation logic.

---

## Bootstrap Modals

Bootstrap 5 is loaded as a CDN `<script>` (not a module), so it lives on `window.bootstrap`:

```js
// Show a modal
const modal = new window.bootstrap.Modal(document.getElementById('myModal'));
modal.show();

// Hide a modal
modal.hide();
// or
window.bootstrap.Modal.getInstance(document.getElementById('myModal'))?.hide();
```

### Modals shared across views

If a module exports modal openers (`openXModal`) that can be called from **other** views (not just its own list view), the modal confirm-button listeners **must not** assume the module's own view entry-point has been called first.

Use an `_ensureModalListeners()` function with its own one-time guard, and call it at the top of every opener:

```js
let _modalListenersAttached = false;

function _ensureModalListeners() {
  if (_modalListenersAttached) return;
  _modalListenersAttached = true;
  document.getElementById('confirmFooBtn')?.addEventListener('click', confirmFoo);
  document.getElementById('confirmBarBtn')?.addEventListener('click', confirmBar);
}

export function openFooModal(id) {
  _ensureModalListeners(); // ← always call this first
  _actionId = id;
  _getModal('fooModal').show();
}
```

This guarantees the buttons are wired on first use, regardless of which view triggered the modal.

---

**Always use `escapeHtml()` before inserting any user-supplied or API-supplied string into innerHTML.**

```js
// ✅ Safe
el.innerHTML = `<span>${escapeHtml(user.name)}</span>`;

// ✅ Safe — numbers and booleans don't need escaping
el.innerHTML = `<span>${item.count}</span>`;

// ❌ Unsafe
el.innerHTML = `<span>${user.name}</span>`;

// ✅ Use textContent for plain text (no HTML needed)
el.textContent = user.name;
```

---

## Dev Mode (No Keycloak)

Set `ENVIRONMENT=development` and `AUTH_DEMO_MODE=true` in the backend `.env`. Then in the browser console before the page loads:

```js
sessionStorage.setItem('tf_access_token', 'demo-token');
```

`initializeAuth()` passes the token to `GET /auth/me`; when the backend has `AUTH_DEMO_MODE=true` it returns a pre-built admin user — no Keycloak needed.

---

## Adding a New Constant / Status

All constants live in `constants.js`. Never hardcode route strings, storage keys, or status codes in view modules.

```js
// Add a new reservation status label
export const STATUS_LABELS = {
  // ... existing ...
  on_hold: 'On Hold',   // ← add here
};
```

`formatReservationStatus()` in `utils.js` imports directly from `constants.js`, so adding the label here is sufficient.
