// frontend/js/validation.js

export function showFieldError(fieldId, message) {
    const el = document.getElementById('error-' + fieldId);
    if (el) {
        el.textContent = message;
        el.style.display = 'block';
        el.classList.add('d-block');
        const input = document.getElementById(fieldId) || document.getElementById('formSource');
        if (input) input.classList.add('is-invalid');
    }
}

export function clearFieldError(fieldId) {
    const el = document.getElementById('error-' + fieldId);
    if (el) {
        el.textContent = '';
        el.style.display = 'none';
        el.classList.remove('d-block');
    }
    const input = document.getElementById(fieldId);
    if (input) input.classList.remove('is-invalid');
}

export function clearAllFieldErrors() {
    ['title', 'description', 'formSource', 'formSourceUrl', 'fileUpload'].forEach(clearFieldError);
    const generalErrors = document.getElementById('formErrors');
    if (generalErrors) { generalErrors.style.display = 'none'; generalErrors.textContent = ''; }
}

export function showValidationErrors(detail) {
    // detail can be a string or a list of pydantic errors
    clearAllFieldErrors();
    const generalErrors = document.getElementById('formErrors');
    if (Array.isArray(detail)) {
        detail.forEach(err => {
            const loc = err.loc && err.loc[err.loc.length - 1];
            const fieldMap = {
                'title': 'title',
                'description': 'description',
                'form_source': 'formSource',
                'form_source_url': 'formSourceUrl',
                'form_attachment_url': 'fileUpload',
            };
            const fieldId = fieldMap[loc];
            if (fieldId) {
                showFieldError(fieldId, err.msg);
            } else {
                if (generalErrors) {
                    generalErrors.style.display = 'block';
                    generalErrors.textContent += (generalErrors.textContent ? ' ' : '') + err.msg;
                }
            }
        });
    } else if (typeof detail === 'string') {
        if (generalErrors) {
            generalErrors.style.display = 'block';
            generalErrors.textContent = detail;
        }
    }
}
