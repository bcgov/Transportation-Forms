// frontend/js/views/list.js
// Re-export shim so the router can import { showListView } from './views/list.js'.
import { showFormsListView } from './forms-list.js';

export function showListView() {
    showFormsListView();
}
