"""US-003: Persisted content versions protect save-before-submit."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import (
    AuditLog,
    BusinessArea,
    Form,
    FormWorkflow,
    Role,
    UserRole,
)


@pytest.fixture()
def draft(db, admin_user):
    area = BusinessArea(id=uuid.uuid4(), name=f"US-003 {uuid.uuid4().hex}")
    db.add(area)
    db.flush()
    form = Form(
        id=uuid.uuid4(),
        title="Original title",
        description="Original description",
        status="draft",
        is_public=False,
        current_version=0,
        keywords=[],
        created_by_id=admin_user.id,
        business_area_id=area.id,
    )
    db.add(form)
    db.flush()
    return form


@pytest.mark.integration
def test_changed_fields_save_then_exact_version_submits(
    client, db, admin_token_headers, draft
):
    update = client.put(
        f"/api/v1/forms/{draft.id}",
        json={"title": "Saved title", "description": "Saved description"},
        headers=admin_token_headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["current_version"] == 1

    submit = client.post(
        f"/api/v1/staff/forms/{draft.id}/submit",
        json={"expected_version": update.json()["current_version"]},
        headers=admin_token_headers,
    )
    assert submit.status_code == 200, submit.text
    db.refresh(draft)
    assert (draft.title, draft.description, draft.status) == (
        "Saved title",
        "Saved description",
        "pending_review",
    )
    assert (
        db.query(FormWorkflow)
        .filter_by(form_id=draft.id, action="submit")
        .count()
        == 1
    )


@pytest.mark.integration
def test_unchanged_draft_submits_without_update_event(
    client, db, admin_token_headers, draft
):
    response = client.post(
        f"/api/v1/staff/forms/{draft.id}/submit",
        json={"expected_version": 0},
        headers=admin_token_headers,
    )
    assert response.status_code == 200, response.text
    db.refresh(draft)
    assert draft.current_version == 0
    assert (
        db.query(AuditLog)
        .filter_by(entity_id=str(draft.id), action="UPDATE")
        .count()
        == 0
    )


@pytest.mark.integration
def test_intervening_update_blocks_submit(
    client, db, admin_token_headers, draft
):
    path = f"/api/v1/forms/{draft.id}"
    first = client.put(
        path, json={"title": "Saved first"}, headers=admin_token_headers
    )
    second = client.put(
        path,
        json={"title": "Other committed edit"},
        headers=admin_token_headers,
    )
    assert (first.status_code, second.status_code) == (200, 200)
    assert (
        second.json()["current_version"] == first.json()["current_version"] + 1
    )

    response = client.post(
        f"/api/v1/staff/forms/{draft.id}/submit",
        json={"expected_version": first.json()["current_version"]},
        headers=admin_token_headers,
    )
    assert response.status_code == 409
    db.refresh(draft)
    assert draft.status == "draft"
    assert draft.title == "Other committed edit"
    assert (
        db.query(FormWorkflow)
        .filter_by(form_id=draft.id, action="submit")
        .count()
        == 0
    )


@pytest.mark.integration
def test_stale_editor_cannot_overwrite_saved_values(
    client, db, admin_token_headers, draft
):
    path = f"/api/v1/forms/{draft.id}"
    saved = client.put(
        path,
        json={"title": "Saved first", "expected_version": 0},
        headers=admin_token_headers,
    )
    assert saved.status_code == 200
    stale = client.put(
        path,
        json={"title": "Stale overwrite", "expected_version": 0},
        headers=admin_token_headers,
    )
    assert stale.status_code == 409
    db.refresh(draft)
    assert draft.title == "Saved first"
    assert draft.current_version == saved.json()["current_version"]


@pytest.mark.integration
def test_missing_version_and_invalid_business_area_do_not_submit(
    client, db, admin_token_headers, draft
):
    path = f"/api/v1/staff/forms/{draft.id}/submit"
    assert client.post(path, headers=admin_token_headers).status_code == 422
    area = db.query(BusinessArea).filter_by(id=draft.business_area_id).one()
    db.delete(area)
    db.flush()
    response = client.post(
        path, json={"expected_version": 0}, headers=admin_token_headers
    )
    assert response.status_code == 400
    db.refresh(draft)
    assert draft.status == "draft"
    assert (
        db.query(FormWorkflow)
        .filter_by(form_id=draft.id, action="submit")
        .count()
        == 0
    )


@pytest.mark.integration
def test_non_owner_cannot_save_or_submit(
    client, db, admin_token_headers, staff_user, draft
):
    draft.created_by_id = staff_user.id
    db.flush()
    update = client.put(
        f"/api/v1/forms/{draft.id}",
        json={"title": "Unauthorized"},
        headers=admin_token_headers,
    )
    submit = client.post(
        f"/api/v1/staff/forms/{draft.id}/submit",
        json={"expected_version": 0},
        headers=admin_token_headers,
    )
    assert update.status_code == 403
    assert submit.status_code == 403
    db.refresh(draft)
    assert draft.title == "Original title"
    assert draft.status == "draft"


@pytest.mark.integration
def test_submit_permission_without_edit_cannot_transition(
    db, user_factory, draft
):
    submitter = user_factory(
        email=f"submit-only-{uuid.uuid4().hex}@example.com"
    )
    draft.created_by_id = submitter.id
    role = Role(
        id=uuid.uuid4(),
        name=f"submit_only_{uuid.uuid4().hex}",
        permissions=["form:submit_for_review"],
        is_active=True,
    )
    db.add(role)
    db.add(UserRole(id=uuid.uuid4(), user_id=submitter.id, role_id=role.id))
    db.flush()
    token = TokenData(
        sub=str(submitter.id),
        email=submitter.email,
        name="Submit only",
        roles=["staff"],
        token_type="access",
        permissions=["form:submit_for_review"],
    )
    previous_db = app.dependency_overrides.get(get_db)
    previous_user = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    try:
        response = TestClient(app).post(
            f"/api/v1/staff/forms/{draft.id}/submit",
            json={"expected_version": 0},
        )
        assert response.status_code == 403
        db.refresh(draft)
        assert draft.status == "draft"
    finally:
        if previous_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_db
        if previous_user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous_user
