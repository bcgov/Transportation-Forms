// Not Found view for unavailable and retired Staff portal routes.
export function showNotFoundView() {
  const view = document.getElementById('notFoundView');
  if (view) view.style.display = 'block';
  document.getElementById('pageTitle').textContent = 'Not Found - BC Gov';
}