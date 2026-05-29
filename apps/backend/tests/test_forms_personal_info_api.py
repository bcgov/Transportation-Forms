"""API integration tests for form personal info collection field."""

from fastapi.testclient import TestClient
import pytest

from backend.main import app
from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData


@pytest.fixture()
def forms_client(db, user_factory):
    """Create a TestClient with DB and auth dependency overrides."""
    user = user_factory(email="forms_api_user@example.com")
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


@pytest.mark.integration
def test_create_form_with_personal_info_yes(forms_client: TestClient):
    response = forms_client.post(
        "/api/v1/forms",
        json={
            "title": "Driver Application Form",
            "description": "Form for driver onboarding.",
            "is_public": False,
            "collects_personal_info": "Yes",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["collects_personal_info"] == "Yes"


@pytest.mark.integration
def test_create_form_defaults_personal_info_to_no(forms_client: TestClient):
    response = forms_client.post(
        "/api/v1/forms",
        json={
            "title": "Vehicle Checklist",
            "description": "Daily vehicle checklist.",
            "is_public": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["collects_personal_info"] == "No"


@pytest.mark.integration
def test_update_form_personal_info_field(forms_client: TestClient):
    create_response = forms_client.post(
        "/api/v1/forms",
        json={
            "title": "Permit Renewal",
            "description": "Permit renewal request form.",
            "is_public": False,
            "collects_personal_info": "No",
        },
    )
    assert create_response.status_code == 201

    form_id = create_response.json()["id"]

    update_response = forms_client.put(
        f"/api/v1/forms/{form_id}",
        json={"collects_personal_info": "Yes"},
    )

    assert update_response.status_code == 200
    updated_payload = update_response.json()
    assert updated_payload["collects_personal_info"] == "Yes"


@pytest.mark.integration
def test_reject_invalid_personal_info_value(forms_client: TestClient):
    response = forms_client.post(
        "/api/v1/forms",
        json={
            "title": "Invalid Personal Info",
            "description": "Should fail.",
            "is_public": False,
            "collects_personal_info": "Maybe",
        },
    )

    assert response.status_code == 422
    assert "collects_personal_info" in str(response.json()["detail"])
