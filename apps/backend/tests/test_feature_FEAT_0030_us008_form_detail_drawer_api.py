"""FEAT-0030 US-008 authorized form-detail contract tests."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import BusinessArea, UserRole


@pytest.fixture()
def form_detail_client(db, user_factory, role_factory):
    user = user_factory(email=f"us008-{uuid.uuid4().hex}@example.com")
    role = role_factory(
        name=f"us008_reader_{uuid.uuid4().hex}",
        permissions=["form:read", "form:create"],
    )
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()
    token = TokenData(
        sub=str(user.id),
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        roles=["staff"],
        token_type="access",
        permissions=["form:read", "form:create"],
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def _create_form(client: TestClient, business_area_id: uuid.UUID | None = None) -> dict:
    response = client.post(
        "/api/v1/forms",
        json={
            "title": "US-008 detail contract",
            "description": "First line\nSecond line",
            "is_public": False,
            "business_area_id": str(business_area_id) if business_area_id else None,
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.integration
def test_authorized_single_form_detail_includes_business_area_mailbox(
    form_detail_client, db
):
    business_area = BusinessArea(
        id=uuid.uuid4(),
        name=f"US-008 Area {uuid.uuid4().hex[:8]}",
        mailbox="transport.forms@example.com",
    )
    db.add(business_area)
    db.flush()
    created = _create_form(form_detail_client, business_area.id)

    response = form_detail_client.get(f"/api/v1/forms/{created['id']}")

    assert response.status_code == 200
    assert response.json()["business_area"] == {
        "id": str(business_area.id),
        "name": business_area.name,
        "mailbox": business_area.mailbox,
    }


@pytest.mark.integration
def test_mailbox_is_not_serialized_in_form_create_or_list_responses(
    form_detail_client, db
):
    business_area = BusinessArea(
        id=uuid.uuid4(),
        name=f"US-008 Private Area {uuid.uuid4().hex[:8]}",
        mailbox="detail-only@example.com",
    )
    db.add(business_area)
    db.flush()

    created = _create_form(form_detail_client, business_area.id)
    assert "mailbox" not in created["business_area"]

    response = form_detail_client.get("/api/v1/forms")
    assert response.status_code == 200
    listed = next(item for item in response.json()["items"] if item["id"] == created["id"])
    assert "mailbox" not in listed["business_area"]


@pytest.mark.integration
def test_single_form_detail_uses_null_for_blank_mailbox(form_detail_client, db):
    business_area = BusinessArea(
        id=uuid.uuid4(),
        name=f"US-008 Blank Area {uuid.uuid4().hex[:8]}",
        mailbox="",
    )
    db.add(business_area)
    db.flush()
    created = _create_form(form_detail_client, business_area.id)

    response = form_detail_client.get(f"/api/v1/forms/{created['id']}")

    assert response.status_code == 200
    assert response.json()["business_area"]["mailbox"] is None


@pytest.mark.integration
def test_single_form_detail_without_business_area_returns_null(form_detail_client):
    created = _create_form(form_detail_client)

    response = form_detail_client.get(f"/api/v1/forms/{created['id']}")

    assert response.status_code == 200
    assert response.json()["business_area"] is None
    assert response.json()["description"] == "First line\nSecond line"


@pytest.mark.integration
def test_denied_form_detail_response_exposes_no_mailbox(form_detail_client, db):
    business_area = BusinessArea(
        id=uuid.uuid4(),
        name=f"US-008 Denied Area {uuid.uuid4().hex[:8]}",
        mailbox="must-not-leak@example.com",
    )
    db.add(business_area)
    db.flush()
    created = _create_form(form_detail_client, business_area.id)
    denied_token = TokenData(
        sub=str(uuid.uuid4()),
        email="denied-us008@example.com",
        name="Denied User",
        roles=["staff"],
        token_type="access",
        permissions=[],
    )
    app.dependency_overrides[get_current_user] = lambda: denied_token

    response = form_detail_client.get(f"/api/v1/forms/{created['id']}")

    assert response.status_code == 403
    assert business_area.mailbox not in response.text
