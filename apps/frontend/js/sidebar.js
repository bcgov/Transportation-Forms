// Responsive presentation state for the authenticated Staff portal sidebar.

const _mobileViewport = window.matchMedia('(max-width: 767.98px)');

let _available = false;
let _desktopExpanded = true;
let _mobileOpen = false;
let _initialized = false;
let _header = null;
let _sidebar = null;
let _scrim = null;
let _toggle = null;
let _sidebarTopFrame = null;
let _lastSidebarTop = null;

function _elements() {
  return {
    header: _header || document.querySelector('.staff-header'),
    sidebar: _sidebar || document.getElementById('staffSidebar'),
    scrim: _scrim || document.getElementById('sidebarScrim'),
    toggle: _toggle || document.getElementById('navMenuToggle'),
  };
}

function _syncSidebarTop() {
  _sidebarTopFrame = null;
  if (!_available || !_header) return;

  const sidebarTop = Math.max(0, Math.round(_header.getBoundingClientRect().bottom));
  if (sidebarTop === _lastSidebarTop) return;

  _lastSidebarTop = sidebarTop;
  document.documentElement.style.setProperty('--staff-sidebar-top', `${sidebarTop}px`);
}

function _scheduleSidebarTopSync() {
  if (!_available || _sidebarTopFrame !== null) return;
  _sidebarTopFrame = window.requestAnimationFrame(_syncSidebarTop);
}

function _render() {
  const { sidebar, scrim, toggle } = _elements();
  if (!sidebar || !scrim || !toggle) return;

  const isMobile = _mobileViewport.matches;
  const isVisible = _available && (isMobile ? _mobileOpen : _desktopExpanded);
  const overlayOpen = isMobile && isVisible;

  document.body.classList.toggle('sidebar-available', _available);
  document.body.classList.toggle(
    'sidebar-collapsed',
    _available && !isMobile && !isVisible,
  );
  document.body.classList.toggle('sidebar-overlay-open', overlayOpen);

  sidebar.hidden = !_available;
  sidebar.classList.toggle('is-open', overlayOpen);
  sidebar.classList.toggle('is-collapsed', !isMobile && !isVisible);
  sidebar.setAttribute('aria-hidden', String(!isVisible));
  sidebar.toggleAttribute('inert', !isVisible);

  scrim.hidden = !overlayOpen;
  toggle.setAttribute('aria-expanded', String(isVisible));
  toggle.setAttribute('aria-label', isVisible ? 'Close navigation' : 'Open navigation');
  _scheduleSidebarTopSync();
}

function _closeMobileSidebar({ restoreFocus = false } = {}) {
  if (!_mobileOpen) return;
  const { sidebar, toggle } = _elements();
  if (restoreFocus || sidebar?.contains(document.activeElement)) toggle?.focus();
  _mobileOpen = false;
  _render();
}

export function initSidebarNavigation() {
  if (_initialized) return;

  const { sidebar, scrim, toggle } = _elements();
  if (!sidebar || !scrim || !toggle) return;
  _header = document.querySelector('.staff-header');
  _sidebar = sidebar;
  _scrim = scrim;
  _toggle = toggle;
  _initialized = true;

  toggle.addEventListener('click', () => {
    if (!_available) return;
    if (_mobileViewport.matches) {
      _mobileOpen = !_mobileOpen;
    } else {
      _desktopExpanded = !_desktopExpanded;
    }
    _render();
  });

  scrim.addEventListener('click', () => _closeMobileSidebar({ restoreFocus: true }));
  sidebar.addEventListener('click', event => {
    if (event.target.closest('[data-route]') && _mobileViewport.matches) {
      _closeMobileSidebar();
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && _mobileViewport.matches && _mobileOpen) {
      _closeMobileSidebar({ restoreFocus: true });
    }
  });

  _mobileViewport.addEventListener('change', () => {
    _mobileOpen = false;
    _render();
  });
  window.addEventListener('resize', _scheduleSidebarTopSync);
  window.addEventListener('scroll', _scheduleSidebarTopSync, { passive: true });
  _render();
}

export function setSidebarAvailability(available) {
  const { sidebar, toggle } = _elements();
  const navigationHadFocus = sidebar?.contains(document.activeElement) || toggle === document.activeElement;
  _available = Boolean(available);
  if (!_available) {
    _mobileOpen = false;
    if (_sidebarTopFrame !== null) {
      window.cancelAnimationFrame(_sidebarTopFrame);
      _sidebarTopFrame = null;
    }
    _lastSidebarTop = null;
    document.documentElement.style.removeProperty('--staff-sidebar-top');
    if (navigationHadFocus && document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  }
  _render();
}