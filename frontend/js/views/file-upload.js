// frontend/js/views/file-upload.js
// Manages the PDF/document file drag-and-drop upload UI (extracted from TASK-110C inline JS).

import { API_BASE } from '../constants.js';
import { escapeHtml } from '../utils.js';
import { showFieldError, clearFieldError } from '../validation.js';
import { getAuthToken } from '../auth.js';

// ─── Module-private state ────────────────────────────────────────────────────

let _uploadedFileUrl = null;
let _uploadedFileFilename = null;
let _uploadedFileType = null;
let _uploadListenerController = null;

// ─── State accessors ─────────────────────────────────────────────────────────

export function getUploadedFileUrl() { return _uploadedFileUrl; }
export function getUploadedFileFilename() { return _uploadedFileFilename; }
export function getUploadedFileType() { return _uploadedFileType; }

export function clearUploadState() {
    _uploadedFileUrl = null;
    _uploadedFileFilename = null;
    _uploadedFileType = null;
}

/**
 * Restore upload state when loading an existing form in edit mode.
 * Sets internal state AND updates the DOM indicator.
 * @param {string} url       The already-stored file URL.
 * @param {string} filename  Human-readable filename to display.
 * @param {string|null} [fileType]  Previously stored file type label.
 */
export function restoreUploadState(url, filename, fileType) {
    _uploadedFileUrl = url;
    _uploadedFileFilename = filename;
    _uploadedFileType = fileType || null;
    showUploadedFile(url, filename);
}

// ─── Init ─────────────────────────────────────────────────────────────────────

/**
 * Bind all drag-and-drop and file-input events for the upload zone.
 * Must be called after the DOM is ready and the upload section is rendered.
 */
export function initFileUpload() {
    // Abort any previously registered listeners before re-binding, so repeated
    // calls (create → navigate away → create again) don't stack handlers.
    if (_uploadListenerController) _uploadListenerController.abort();
    _uploadListenerController = new AbortController();
    const { signal } = _uploadListenerController;

    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const clearBtn = document.querySelector('#uploadedFileInfo .btn-close');

    if (dropZone) {
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        }, { signal });
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('drag-over');
        }, { signal });
        dropZone.addEventListener('drop', handleFileDrop, { signal });
        dropZone.addEventListener('click', () => fileInput && fileInput.click(), { signal });
    }

    if (fileInput) {
        fileInput.addEventListener('change', handleFileSelect, { signal });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', clearUploadedFile, { signal });
    }
}

// ─── Event handlers ───────────────────────────────────────────────────────────

function handleFileDrop(event) {
    event.preventDefault();
    document.getElementById('dropZone').classList.remove('drag-over');
    const file = event.dataTransfer.files[0];
    if (file) uploadFile(file);
}

/**
 * Called from the file <input> change event.
 * @param {Event|File} eventOrFile  Either the native change event or a File directly.
 */
export async function handleFileSelect(eventOrFile) {
    const file = eventOrFile instanceof File ? eventOrFile : eventOrFile.target.files[0];
    if (file) await uploadFile(file);
}

// ─── Upload ───────────────────────────────────────────────────────────────────

/**
 * POST the file to `API_BASE/forms/upload`, update module state, and refresh the UI.
 * @param {File} file
 */
export async function uploadFile(file) {
    document.getElementById('uploadProgress').style.display = 'block';
    document.getElementById('uploadProgressText').textContent = `Uploading ${file.name}\u2026`;
    document.getElementById('uploadedFileInfo').style.display = 'none';
    clearFieldError('fileUpload');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const token = _getAuthToken();
        const response = await fetch(`${API_BASE}/forms/upload`, {
            method: 'POST',
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
            body: formData,
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Upload failed');
        }

        const result = await response.json();
        _uploadedFileUrl = result.url;
        _uploadedFileFilename = result.filename;
        _uploadedFileType = result.file_type || null;
        showUploadedFile(result.url, result.filename);
    } catch (error) {
        showFieldError('fileUpload', 'Upload failed: ' + error.message);
    } finally {
        document.getElementById('uploadProgress').style.display = 'none';
        // Reset the input so the same file can be re-selected if needed
        const fileInput = document.getElementById('fileInput');
        if (fileInput) fileInput.value = '';
    }
}

// ─── Display helpers ──────────────────────────────────────────────────────────

/**
 * Show the "uploaded file" success indicator.
 * @param {string} url       Stored file URL (unused in display but kept for symmetry).
 * @param {string} filename  Human-readable filename to display.
 */
export function showUploadedFile(url, filename) {
    const nameEl = document.getElementById('uploadedFileName');
    if (nameEl) nameEl.textContent = ' ' + escapeHtml(filename);
    document.getElementById('uploadedFileInfo').style.display = 'block';
}

/** Hide the uploaded-file indicator and reset module state. */
export function clearUploadedFile() {
    _uploadedFileUrl = null;
    _uploadedFileFilename = null;
    _uploadedFileType = null;
    document.getElementById('uploadedFileInfo').style.display = 'none';
}

// ─── Private helpers ──────────────────────────────────────────────────────────

/**
 * Read the auth token from localStorage using the same key as the rest of the app.
 * Falls back gracefully when running outside the full app shell.
 */
function _getAuthToken() {
    return getAuthToken();
}
