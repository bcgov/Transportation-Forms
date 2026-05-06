// frontend/js/constants.js
// Single source of truth for magic strings, API roots, storage keys, routes, and status labels.

export const API_BASE = '/api/v1';

export const AUTH_STORAGE_ACCESS = 'tf_access_token';
export const AUTH_STORAGE_REFRESH = 'tf_refresh_token';
export const AUTH_STORAGE_USER = 'tf_user';

export const ROUTES = {
  HOME: '/',
  CALLBACK: '/callback',
  DASHBOARD: '/dashboard',
  FORMS_LIST: '/forms',
  FORM_CREATE: '/create',
  FORM_EDIT: '/edit/:id',
  RESERVE: '/reserve',
  MY_RESERVATIONS: '/my-reservations',
  APPROVALS: '/approvals',
  ROLES: '/roles',
  ROLE_DETAIL: '/roles/:id',
  USERS: '/users',
  USER_DETAIL: '/users/:id',
  ACCESS_REQUESTS: '/access-requests',
};

export const STATUS_LABELS = {
  reserved: 'Reserved',
  pending_approval: 'Pending Approval',
  approved: 'Approved',
  rejected: 'Rejected',
  changes_requested: 'Changes Requested',
  released: 'Released',
  expired: 'Expired',
};
