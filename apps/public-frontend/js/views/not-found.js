/*
 * 404 view (unknown SPA route) — US-006 AC9.
 */

export function showNotFoundView() {
  document.title = 'Page not found — Public Forms — BC Government';
  let robots = document.head.querySelector('meta[name="robots"]');
  if (!robots) {
    robots = document.createElement('meta');
    robots.setAttribute('name', 'robots');
    document.head.appendChild(robots);
  }
  robots.setAttribute('content', 'noindex');
}
