// frontend/js/views/welcome.js
// Welcome view — shown to unauthenticated users.
export function showWelcomeView() {
    const view = document.getElementById('welcomeView');
    if (view) view.style.display = 'block';
    document.getElementById('pageTitle').textContent = 'Transportation Forms Management - BC Gov';
}
