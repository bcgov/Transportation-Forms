"""TASK-111 API integration tests for form search/autocomplete/filter/pagination."""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import get_db
from backend.models import BusinessArea, Form


@pytest.fixture()
def search_client(db):
    """Test client with DB override for search API tests."""
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def seed_user(user_factory):
    return user_factory(email="search-owner@example.com")


def _create_business_area(db, name: str) -> BusinessArea:
    area = BusinessArea(
        id=uuid.uuid4(),
        name=name,
        description=f"{name} area",
        sort_order=0,
        is_active=True,
    )
    db.add(area)
    db.flush()
    return area


def _create_form(
    db,
    *,
    created_by_id,
    title: str,
    description: str,
    keywords=None,
    is_public=False,
    form_source=None,
    created_at: datetime | None = None,
    business_area: BusinessArea | None = None,
):
    form = Form(
        id=uuid.uuid4(),
        title=title,
        description=description,
        status="draft",
        is_public=is_public,
        current_version=0,
        keywords=keywords or [],
        created_by_id=created_by_id,
        form_source=form_source,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(form)
    db.flush()

    if business_area is not None:
        form.business_area_id = business_area.id
        db.add(form)
        db.flush()

    return form


@pytest.mark.integration
def test_search_keyword_matches_indexed_fields(search_client: TestClient, db, seed_user):
    _create_form(
        db,
        created_by_id=seed_user.id,
        title="Driver Permit Application",
        description="Apply for a permit",
        keywords=["licence", "application"],
        form_source="URL",
    )
    _create_form(
        db,
        created_by_id=seed_user.id,
        title="Vehicle Inspection Checklist",
        description="Commercial inspections",
        keywords=["safety", "inspection"],
        form_source="Download",
    )
    db.commit()

    response = search_client.get("/api/v1/forms", params={"q": "inspection", "limit": 25})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert any("Inspection" in item["title"] for item in payload["items"])


@pytest.mark.integration
def test_autocomplete_enforces_min_length_and_max_suggestions(search_client: TestClient, db, seed_user):
    for i in range(15):
        _create_form(
            db,
            created_by_id=seed_user.id,
            title=f"Permit Search Form {i}",
            description="Autocomplete seed",
            keywords=["permit"],
        )
    db.commit()

    short_response = search_client.get("/api/v1/forms/autocomplete", params={"q": "p"})
    assert short_response.status_code == 422

    response = search_client.get(
        "/api/v1/forms/autocomplete",
        params={"q": "perm", "max_suggestions": 10},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "perm"
    assert len(payload["suggestions"]) <= 10


@pytest.mark.integration
def test_filters_individual_and_combined(search_client: TestClient, db, seed_user):
    area_a = _create_business_area(db, "Highways")
    area_b = _create_business_area(db, "Transit")

    _create_form(
        db,
        created_by_id=seed_user.id,
        title="Highway Link Public",
        description="A",
        is_public=True,
        form_source="URL",
        business_area=area_a,
    )
    _create_form(
        db,
        created_by_id=seed_user.id,
        title="Transit Download Private",
        description="B",
        is_public=False,
        form_source="Download",
        business_area=area_b,
    )
    db.commit()

    source_response = search_client.get("/api/v1/forms", params={"form_source": "Link", "limit": 25})
    assert source_response.status_code == 200
    assert all(item["form_source"] == "URL" for item in source_response.json()["items"])

    public_response = search_client.get("/api/v1/forms", params={"is_public": "false", "limit": 25})
    assert public_response.status_code == 200
    assert all(item["is_public"] is False for item in public_response.json()["items"])

    combined_response = search_client.get(
        "/api/v1/forms",
        params=[
            ("business_area_ids", str(area_b.id)),
            ("form_source", "Download"),
            ("is_public", "false"),
            ("limit", "25"),
        ],
    )
    assert combined_response.status_code == 200
    payload = combined_response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "Transit Download Private"


@pytest.mark.integration
def test_sort_order_created_at(search_client: TestClient, db, seed_user):
    now = datetime.now(timezone.utc)
    _create_form(
        db,
        created_by_id=seed_user.id,
        title="Older Form",
        description="Older",
        created_at=now - timedelta(days=2),
    )
    _create_form(
        db,
        created_by_id=seed_user.id,
        title="Newer Form",
        description="Newer",
        created_at=now,
    )
    db.commit()

    desc_response = search_client.get("/api/v1/forms", params={"sort_order": "desc", "limit": 25})
    asc_response = search_client.get("/api/v1/forms", params={"sort_order": "asc", "limit": 25})

    assert desc_response.status_code == 200
    assert asc_response.status_code == 200
    assert desc_response.json()["items"][0]["title"] == "Newer Form"
    assert asc_response.json()["items"][0]["title"] == "Older Form"


@pytest.mark.integration
def test_pagination_contract_and_limits(search_client: TestClient, db, seed_user):
    for i in range(30):
        _create_form(
            db,
            created_by_id=seed_user.id,
            title=f"Pagination Form {i}",
            description="Pagination seed",
        )
    db.commit()

    default_response = search_client.get("/api/v1/forms")
    assert default_response.status_code == 200
    default_payload = default_response.json()
    assert default_payload["limit"] == 25
    assert len(default_payload["items"]) == 25

    limit_50_response = search_client.get("/api/v1/forms", params={"limit": 50})
    assert limit_50_response.status_code == 200
    assert limit_50_response.json()["limit"] == 50

    limit_100_response = search_client.get("/api/v1/forms", params={"limit": 100})
    assert limit_100_response.status_code == 200
    assert limit_100_response.json()["limit"] == 100

    invalid_limit_response = search_client.get("/api/v1/forms", params={"limit": 30})
    assert invalid_limit_response.status_code == 422
    assert "limit must be one of" in str(invalid_limit_response.json()["detail"])
