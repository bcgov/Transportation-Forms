// frontend/js/state.js

let _currentUser = null;
let _isAuthInitialized = false;

export function getCurrentUser() {
  return _currentUser;
}

export function setCurrentUser(user) {
  _currentUser = user;
}

export function isAuthInitialized() {
  return _isAuthInitialized;
}

export function setAuthInitialized(value) {
  _isAuthInitialized = value;
}
