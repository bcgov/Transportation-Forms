# TASK-414 — Form Personal Info Indicator

## Summary
Add a new form field to capture whether the form collects personal information from end users.

## Requirements Implemented
- Database schema updated with `collects_personal_info` on `forms`.
- Allowed values constrained to `Yes` / `No`.
- Default value set to `No`.
- Forms API create, update, and response payloads updated.
- Add New Form UI updated with the field label: **Does this form collect personal info?**
- Form View modal updated to display the selected value.
- Integration tests added for create/update/default/validation behavior.

## Files
- `alembic/versions/006_personal_info_collection_field.py`
- `backend/models.py`
- `backend/routes/forms.py`
- `backend/services/forms.py`
- `frontend/index.html`
- `tests/test_forms_personal_info_api.py`
