"""FEAT-0031 US-001: Business Area validation on form write paths."""

import uuid
from datetime import datetime, timezone

import pytest

from backend.models import BusinessArea, Form, FormWorkflow


@pytest.fixture()
def active_area(db):
    area = BusinessArea(id=uuid.uuid4(), name=f"US-001 {uuid.uuid4().hex}")
    db.add(area)
    db.flush()
    return area


@pytest.fixture()
def saved_form(client, admin_token_headers, active_area):
    response = client.post(
        "/api/v1/forms",
        json={
            "title": "Business Area regression",
            "description": "Must stay editable",
            "business_area_id": str(active_area.id),
        },
        headers=admin_token_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "selection",
    ["missing", "null", "unknown", "deleted"],
)
def test_create_requires_active_area(
    client, db, admin_token_headers, active_area, selection
):
    payload = {"title": "Invalid selection", "description": "No write allowed"}
    if selection == "null":
        payload["business_area_id"] = None
    elif selection == "unknown":
        payload["business_area_id"] = str(uuid.uuid4())
    elif selection == "deleted":
        active_area.deleted_at = datetime.now(timezone.utc)
        db.flush()
        payload["business_area_id"] = str(active_area.id)

    before = db.query(Form).count()
    response = client.post(
        "/api/v1/forms",
        json=payload,
        headers=admin_token_headers,
    )

    assert response.status_code == 400
    assert "Business Area" in response.json()["detail"]
    assert db.query(Form).count() == before


@pytest.mark.integration
@pytest.mark.parametrize(
    "selection",
    ["null", "unknown", "deleted", "omitted"],
)
def test_update_rejects_invalid_area_without_changing_form(
    client, db, admin_token_headers, saved_form, active_area, selection
):
    form = db.query(Form).filter(Form.id == uuid.UUID(saved_form)).one()
    payload = {"title": "Should not persist"}
    if selection == "null":
        payload["business_area_id"] = None
    elif selection == "unknown":
        payload["business_area_id"] = str(uuid.uuid4())
    if selection in ("deleted", "omitted"):
        active_area.deleted_at = datetime.now(timezone.utc)
        db.flush()
        if selection == "deleted":
            payload["business_area_id"] = str(active_area.id)

    response = client.put(
        f"/api/v1/forms/{saved_form}",
        json=payload,
        headers=admin_token_headers,
    )

    assert response.status_code == 400
    assert "Business Area" in response.json()["detail"]
    db.refresh(form)
    assert form.title == "Business Area regression"


@pytest.mark.integration
def test_legacy_form_can_be_corrected_and_submitted(
    client, db, admin_token_headers, admin_user, active_area
):
    form = Form(
        id=uuid.uuid4(),
        title="Legacy form",
        description="Needs correction",
        created_by_id=admin_user.id,
        status="draft",
        is_public=False,
        current_version=0,
        business_area_id=None,
    )
    db.add(form)
    db.flush()
    path = f"/api/v1/forms/{form.id}"

    assert client.get(path, headers=admin_token_headers).status_code == 200
    response = client.post(
        f"/api/v1/staff/forms/{form.id}/submit", headers=admin_token_headers
    )
    assert response.status_code == 400
    assert "Business Area" in response.json()["detail"]
    db.refresh(form)
    assert form.status == "draft"
    history = db.query(FormWorkflow).filter(FormWorkflow.form_id == form.id)
    assert history.count() == 0

    response = client.put(
        path,
        json={"business_area_id": str(active_area.id)},
        headers=admin_token_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["business_area"]["id"] == str(active_area.id)
    response = client.post(
        f"/api/v1/staff/forms/{form.id}/submit", headers=admin_token_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending_review"


@pytest.mark.integration
def test_deleted_area_blocks_submit_and_unprivileged_submit_stays_denied(
    client,
    db,
    admin_token_headers,
    user_token_headers,
    saved_form,
    active_area,
):
    active_area.deleted_at = datetime.now(timezone.utc)
    db.flush()
    path = f"/api/v1/staff/forms/{saved_form}/submit"

    denied = client.post(path, headers=user_token_headers)
    assert denied.status_code == 403
    invalid = client.post(path, headers=admin_token_headers)
    assert invalid.status_code == 400
    assert "Business Area" in invalid.json()["detail"]
    form = db.query(Form).filter(Form.id == uuid.UUID(saved_form)).one()
    assert form.status == "draft"
    history = db.query(FormWorkflow).filter(FormWorkflow.form_id == form.id)
    assert history.count() == 0
