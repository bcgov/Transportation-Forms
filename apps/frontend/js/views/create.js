// frontend/js/views/create.js
// Re-export shim so the router can import { showCreateView, showEditView } from './views/create.js'.
import { showCreateView as _showCreateView, showEditView as _showEditView } from './forms-create.js';

export async function showCreateView() {
    await _showCreateView();
}

export async function showEditView(formId) {
    await _showEditView(formId);
}
