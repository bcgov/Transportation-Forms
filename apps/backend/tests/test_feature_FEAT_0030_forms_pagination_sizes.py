"""API contract coverage for FEAT-0030 US-006 page sizes."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import Form, Role, UserRole


@pytest.fixture()
def search_client(db, user_factory):
    user = user_factory(email="pagination-size-client@example.com")
    role = Role(
        name="pagination_size_reader",
        permissions=["form:read"],
        is_system=False,
        is_active=True,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()
    token = TokenData(
        sub=str(user.id),
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        roles=["staff"],
        token_type="access",
        permissions=["form:read"],
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def test_forms_pagination_defaults_to_24(search_client):
    response = search_client.get("/api/v1/forms")

    assert response.status_code == 200
    assert response.json()["limit"] == 24


@pytest.mark.parametrize("limit", [24, 48, 96])
def test_forms_pagination_accepts_staff_ui_page_sizes(search_client, limit):
    response = search_client.get("/api/v1/forms", params={"limit": limit})

    assert response.status_code == 200
    assert response.json()["limit"] == limit


@pytest.mark.parametrize("limit", [25, 50, 100])
def test_forms_pagination_retains_legacy_client_compatibility(search_client, limit):
    response = search_client.get("/api/v1/forms", params={"limit": limit})

    assert response.status_code == 200
    assert response.json()["limit"] == limit


@pytest.mark.parametrize("limit", [0, 23, 49, 97, 101])
def test_forms_pagination_rejects_unsupported_page_sizes(search_client, limit):
    response = search_client.get("/api/v1/forms", params={"limit": limit})

    assert response.status_code == 422
    assert "limit must be one of" in str(response.json()["detail"])


@pytest.mark.parametrize("limit", [24, 48, 96])
def test_forms_pagination_traverses_200_forms_without_gaps(
    search_client, db, user_factory, limit
):
    owner = user_factory(email=f"pagination-{limit}-owner@example.com")
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.add_all(
        [
            Form(
                title=f"Pagination Form {index:03d}",
                description="Deterministic pagination test entry",
                status="draft",
                is_public=False,
                current_version=0,
                keywords=[],
                created_by_id=owner.id,
                collects_personal_info="No",
                created_at=created_at + timedelta(seconds=index),
                updated_at=created_at + timedelta(seconds=index),
            )
            for index in range(200)
        ]
    )
    db.commit()

    returned_ids = []
    for skip in range(0, 200, limit):
        response = search_client.get(
            "/api/v1/forms", params={"skip": skip, "limit": limit}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 200
        assert payload["skip"] == skip
        assert payload["limit"] == limit
        returned_ids.extend(item["id"] for item in payload["items"])

    assert len(returned_ids) == 200
    assert len(set(returned_ids)) == 200

    final_response = search_client.get(
        "/api/v1/forms", params={"skip": 192, "limit": limit}
    )
    assert final_response.status_code == 200
    assert len(final_response.json()["items"]) == 8

    empty_response = search_client.get(
        "/api/v1/forms", params={"skip": 200, "limit": limit}
    )
    assert empty_response.status_code == 200
    assert empty_response.json()["items"] == []
