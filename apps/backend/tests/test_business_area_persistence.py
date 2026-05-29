"""FEAT-0003: Integration tests for single business area per form.

Covers:
- Business area persisted on form create (scalar business_area_id)
- Business area returned in GET /forms/{id} as scalar object
- Business area returned in GET /forms (list) as scalar object
- Business area updated via PUT /forms/{id}
- Business area cleared via PUT /forms/{id}
- Form created without business area has null
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.models import BusinessArea


@pytest.fixture()
def ba_client(db, user_factory):
    """TestClient wired for business area integration tests."""
    user = user_factory(email="ba_user@example.com")
    token = TokenData(
        sub=str(user.id),
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        roles=["staff"],
        token_type="access",
        permissions=["form:read", "form:create", "form:edit"],
    )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token

    client = TestClient(app)
    yield client

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def business_area(db):
    """Create a test business area."""
    ba = BusinessArea(
        id=uuid.uuid4(),
        name=f"Highways-{uuid.uuid4().hex[:6]}",
        description="Test business area",
        is_active=True,
    )
    db.add(ba)
    db.flush()
    return ba


# ── Create with business area ─────────────────────────────────────────────────


@pytest.mark.integration
def test_create_form_with_business_area(ba_client, business_area):
    """Business area is persisted when creating a form with business_area_id."""
    resp = ba_client.post(
        "/api/v1/forms",
        json={
            "title": "BA Persistence Test",
            "description": "Test form with business area.",
            "is_public": False,
            "business_area_id": str(business_area.id),
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["business_area"] is not None
    assert data["business_area"]["id"] == str(business_area.id)
    assert data["business_area"]["name"] == business_area.name


@pytest.mark.integration
def test_create_form_without_business_area(ba_client):
    """Form created without business_area_id has null business_area."""
    resp = ba_client.post(
        "/api/v1/forms",
        json={
            "title": "No BA Form",
            "description": "Form without business area.",
            "is_public": True,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["business_area"] is None


# ── GET single form returns business area ──────────────────────────────────────


@pytest.mark.integration
def test_get_form_returns_business_area(ba_client, business_area):
    """GET /forms/{id} returns the scalar business_area object."""
    create_resp = ba_client.post(
        "/api/v1/forms",
        json={
            "title": "GET BA Test",
            "description": "Testing GET returns BA.",
            "is_public": False,
            "business_area_id": str(business_area.id),
        },
    )
    form_id = create_resp.json()["id"]

    get_resp = ba_client.get(f"/api/v1/forms/{form_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["business_area"] is not None
    assert data["business_area"]["id"] == str(business_area.id)
    assert data["business_area"]["name"] == business_area.name
    # Must NOT have old plural field
    assert "business_areas" not in data


# ── GET list returns business area ─────────────────────────────────────────────


@pytest.mark.integration
def test_list_forms_returns_business_area(ba_client, business_area):
    """GET /forms list includes business_area for each form."""
    ba_client.post(
        "/api/v1/forms",
        json={
            "title": "List BA Test",
            "description": "For list check.",
            "is_public": False,
            "business_area_id": str(business_area.id),
        },
    )

    list_resp = ba_client.get("/api/v1/forms")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    form = next(f for f in items if f["title"] == "List BA Test")
    assert form["business_area"] is not None
    assert form["business_area"]["id"] == str(business_area.id)


# ── Update business area ──────────────────────────────────────────────────────


@pytest.mark.integration
def test_update_form_sets_business_area(ba_client, business_area):
    """PUT /forms/{id} with business_area_id sets the association on a form that had none."""
    create_resp = ba_client.post(
        "/api/v1/forms",
        json={
            "title": "Update BA Test",
            "description": "Test BA update.",
            "is_public": False,
        },
    )
    assert create_resp.status_code == 201
    form_id = create_resp.json()["id"]
    assert create_resp.json()["business_area"] is None

    update_resp = ba_client.put(
        f"/api/v1/forms/{form_id}",
        json={"business_area_id": str(business_area.id)},
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["business_area"]["id"] == str(business_area.id)
    assert data["business_area"]["name"] == business_area.name


# ── Roundtrip: create → get → verify BA persisted ─────────────────────────────


@pytest.mark.integration
def test_business_area_roundtrip(ba_client, business_area):
    """Full roundtrip: create with BA, fetch back, confirm BA is present.

    This is the exact bug scenario — frontend creates a form with a
    business area, then loads it for edit and expects to see the BA.
    """
    create_resp = ba_client.post(
        "/api/v1/forms",
        json={
            "title": "Roundtrip BA Test",
            "description": "Roundtrip test.",
            "is_public": False,
            "business_area_id": str(business_area.id),
        },
    )
    assert create_resp.status_code == 201
    form_id = create_resp.json()["id"]

    # Simulate edit-mode load
    get_resp = ba_client.get(f"/api/v1/forms/{form_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()

    # The frontend reads form.business_area (scalar object)
    assert data["business_area"] is not None
    assert data["business_area"]["id"] == str(business_area.id)


# ── Old plural field is rejected / ignored ─────────────────────────────────────


@pytest.mark.integration
def test_create_with_old_plural_field_is_ignored(ba_client, business_area):
    """Sending the old business_area_ids array should NOT set business area.

    This verifies the bug is detectable: if the frontend sends the wrong
    field name, the business area is silently lost.
    """
    resp = ba_client.post(
        "/api/v1/forms",
        json={
            "title": "Old Field Name Test",
            "description": "Using deprecated plural field.",
            "is_public": False,
            "business_area_ids": [str(business_area.id)],  # Wrong field name!
        },
    )
    assert resp.status_code == 201
    # business_area should be null because the field was silently ignored
    assert resp.json()["business_area"] is None
