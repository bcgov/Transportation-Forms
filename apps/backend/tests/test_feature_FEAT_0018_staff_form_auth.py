"""FEAT-0018 SEC-002: Enforce authentication and form:read permission on staff form read endpoints.

Covers all test cases from TC-US-001:
- TC1.1–TC1.3:  Unauthenticated requests to list, detail, autocomplete → 401
- TC1.4–TC1.5:  Authenticated without form:read → 403
- TC1.6–TC1.8:  Authenticated with form:read → 200 with data
- TC1.9:        No sensitive metadata in error responses
- TC1.10–TC1.11: Expired/malformed tokens → 401
- TC1.12:       Unauthenticated detail for non-existent ID → 401 (not 404)
- TC1.13:       Regression — authenticated workflows unaffected
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData, jwt_handler
from backend.models import Form


# ── Sensitive field names that must never appear in 401/403 response bodies ──

_SENSITIVE_FIELDS = {
    "status",
    "is_public",
    "form_attachment_url",
    "created_by",
    "collects_personal_info",
    "form_source_url",
    "form_number",
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _seed_form(db, user_factory):
    """Insert a form directly so GET endpoints have data to return."""
    owner = user_factory(email="form-owner-0018@example.com")
    form = Form(
        id=uuid.uuid4(),
        title="FEAT-0018 Test Form",
        description="A test form for auth enforcement",
        status="published",
        is_public=True,
        current_version=1,
        keywords=["test"],
        created_by_id=owner.id,
        collects_personal_info="Yes",
        form_source="URL",
        form_source_url="https://example.com/form.pdf",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(form)
    db.flush()
    return form


@pytest.fixture()
def auth_client_with_read(db, user_factory, _seed_form):
    """Authenticated test client whose user has form:read permission."""
    user = user_factory(email="reader-0018@example.com")

    def _get_user(request: Request) -> TokenData:
        return TokenData(
            sub=str(user.id),
            email=user.email,
            name="Reader User",
            roles=["staff_viewer"],
            token_type="access",
            permissions=["form:read"],
        )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _get_user
    yield TestClient(app), _seed_form
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def auth_client_no_read(db, user_factory, _seed_form):
    """Authenticated test client whose user lacks form:read permission."""
    user = user_factory(email="noperm-0018@example.com")

    def _get_user(request: Request) -> TokenData:
        return TokenData(
            sub=str(user.id),
            email=user.email,
            name="No-Perm User",
            roles=["staff"],
            token_type="access",
            permissions=[],  # no form:read
        )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _get_user
    yield TestClient(app), _seed_form
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def unauth_client(db, _seed_form):
    """Test client with NO get_current_user override — truly unauthenticated.

    Only get_db is overridden; requests that hit endpoints protected by
    get_current_user will fail with 401 from the real HTTPBearer dependency.
    """
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides.pop(get_current_user, None)
    yield TestClient(app, raise_server_exceptions=False), _seed_form
    app.dependency_overrides.pop(get_db, None)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _assert_no_sensitive_data(response):
    """Verify response body contains no form metadata fields."""
    body = response.text
    for field in _SENSITIVE_FIELDS:
        assert field not in body, (
            f"Sensitive field '{field}' found in {response.status_code} response body"
        )


# ===========================================================================
# TC1.1: Unauthenticated → form list → 401
# ===========================================================================


class TestUnauthenticatedReturns401:

    def test_form_list_unauthenticated(self, unauth_client):
        """TC1.1: Anonymous GET /forms returns 401, no form data."""
        client, _ = unauth_client
        resp = client.get("/api/v1/forms")
        assert resp.status_code == 401
        _assert_no_sensitive_data(resp)

    def test_form_detail_unauthenticated(self, unauth_client):
        """TC1.2: Anonymous GET /forms/{id} returns 401, no form data."""
        client, form = unauth_client
        resp = client.get(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 401
        _assert_no_sensitive_data(resp)

    def test_form_autocomplete_unauthenticated(self, unauth_client):
        """TC1.3: Anonymous GET /forms/autocomplete returns 401, no form data."""
        client, _ = unauth_client
        resp = client.get("/api/v1/forms/autocomplete", params={"q": "test"})
        assert resp.status_code == 401
        _assert_no_sensitive_data(resp)

    def test_form_detail_nonexistent_id_unauthenticated(self, unauth_client):
        """TC1.12: Anonymous GET /forms/{nonexistent} returns 401, not 404."""
        client, _ = unauth_client
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/forms/{fake_id}")
        assert resp.status_code == 401
        _assert_no_sensitive_data(resp)


# ===========================================================================
# TC1.4–TC1.5: Authenticated without form:read → 403
# ===========================================================================


class TestAuthenticatedWithoutPermissionReturns403:

    def test_form_list_no_read_permission(self, auth_client_no_read):
        """TC1.4: Authenticated (no form:read) GET /forms → 403."""
        client, _ = auth_client_no_read
        resp = client.get("/api/v1/forms")
        assert resp.status_code == 403
        _assert_no_sensitive_data(resp)

    def test_form_detail_no_read_permission(self, auth_client_no_read):
        """TC1.5a: Authenticated (no form:read) GET /forms/{id} → 403."""
        client, form = auth_client_no_read
        resp = client.get(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 403
        _assert_no_sensitive_data(resp)

    def test_form_autocomplete_no_read_permission(self, auth_client_no_read):
        """TC1.5b: Authenticated (no form:read) GET /forms/autocomplete → 403."""
        client, _ = auth_client_no_read
        resp = client.get("/api/v1/forms/autocomplete", params={"q": "test"})
        assert resp.status_code == 403
        _assert_no_sensitive_data(resp)


# ===========================================================================
# TC1.6–TC1.8: Authenticated with form:read → 200
# ===========================================================================


class TestAuthenticatedWithReadReturns200:

    def test_form_list_with_read_permission(self, auth_client_with_read):
        """TC1.6: Authenticated (form:read) GET /forms → 200 with items."""
        client, _ = auth_client_with_read
        resp = client.get("/api/v1/forms")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 1

    def test_form_detail_with_read_permission(self, auth_client_with_read):
        """TC1.7: Authenticated (form:read) GET /forms/{id} → 200 with form."""
        client, form = auth_client_with_read
        resp = client.get(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(form.id)
        assert data["title"] == "FEAT-0018 Test Form"
        # Verify all expected fields are present
        assert "status" in data
        assert "is_public" in data
        assert "created_by" in data
        assert "collects_personal_info" in data

    def test_form_autocomplete_with_read_permission(self, auth_client_with_read):
        """TC1.8: Authenticated (form:read) GET /forms/autocomplete → 200."""
        client, _ = auth_client_with_read
        resp = client.get("/api/v1/forms/autocomplete", params={"q": "FEAT"})
        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data
        assert "suggestions" in data


# ===========================================================================
# TC1.9: No sensitive metadata in error responses
# ===========================================================================


class TestNoSensitiveDataInErrorResponses:

    def test_401_body_has_no_form_metadata(self, unauth_client):
        """TC1.9a: 401 response body is clean."""
        client, form = unauth_client
        for url in [
            "/api/v1/forms",
            f"/api/v1/forms/{form.id}",
            "/api/v1/forms/autocomplete?q=test",
        ]:
            resp = client.get(url)
            assert resp.status_code == 401
            _assert_no_sensitive_data(resp)

    def test_403_body_has_no_form_metadata(self, auth_client_no_read):
        """TC1.9b: 403 response body is clean."""
        client, form = auth_client_no_read
        for url in [
            "/api/v1/forms",
            f"/api/v1/forms/{form.id}",
            "/api/v1/forms/autocomplete?q=test",
        ]:
            resp = client.get(url)
            assert resp.status_code == 403
            _assert_no_sensitive_data(resp)


# ===========================================================================
# TC1.10–TC1.11: Expired / malformed tokens → 401
# ===========================================================================


class TestTokenEdgeCases:

    def test_expired_token_returns_401(self, db, _seed_form):
        """TC1.10: Expired JWT → 401 on all endpoints."""
        from datetime import timedelta

        expired_token = jwt_handler.generate_access_token(
            user_id=str(uuid.uuid4()),
            email="expired@example.com",
            name="Expired User",
            roles=["staff"],
            expires_delta=timedelta(seconds=-10),
            permissions=["form:read"],
        )

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides.pop(get_current_user, None)
        client = TestClient(app, raise_server_exceptions=False)

        headers = {"Authorization": f"Bearer {expired_token}"}
        for url in [
            "/api/v1/forms",
            f"/api/v1/forms/{_seed_form.id}",
            "/api/v1/forms/autocomplete?q=test",
        ]:
            resp = client.get(url, headers=headers)
            assert resp.status_code == 401, f"Expected 401 for expired token on {url}"
            _assert_no_sensitive_data(resp)

        app.dependency_overrides.pop(get_db, None)

    def test_malformed_token_returns_401(self, db, _seed_form):
        """TC1.11: Malformed JWT → 401 on all endpoints."""
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides.pop(get_current_user, None)
        client = TestClient(app, raise_server_exceptions=False)

        headers = {"Authorization": "Bearer not.a.valid.jwt.token"}
        for url in [
            "/api/v1/forms",
            f"/api/v1/forms/{_seed_form.id}",
            "/api/v1/forms/autocomplete?q=test",
        ]:
            resp = client.get(url, headers=headers)
            assert resp.status_code == 401, f"Expected 401 for malformed token on {url}"
            _assert_no_sensitive_data(resp)

        app.dependency_overrides.pop(get_db, None)

    def test_no_auth_header_returns_401(self, db, _seed_form):
        """No Authorization header → 401 on all endpoints."""
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides.pop(get_current_user, None)
        client = TestClient(app, raise_server_exceptions=False)

        for url in [
            "/api/v1/forms",
            f"/api/v1/forms/{_seed_form.id}",
            "/api/v1/forms/autocomplete?q=test",
        ]:
            resp = client.get(url)
            assert resp.status_code in (401, 403), f"Expected 401/403 for no header on {url}"
            _assert_no_sensitive_data(resp)

        app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# TC1.13: Regression — authenticated staff workflows unaffected
# ===========================================================================


class TestRegressionAuthenticatedWorkflows:

    def test_form_list_returns_expected_schema(self, auth_client_with_read):
        """TC1.13a: List response schema is unchanged."""
        client, _ = auth_client_with_read
        resp = client.get("/api/v1/forms")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"total", "skip", "limit", "items"}
        if data["items"]:
            item = data["items"][0]
            expected_keys = {
                "id", "title", "description", "status", "is_public",
                "current_version", "keywords", "business_area",
                "created_by", "effective_date", "form_source",
                "form_source_url", "form_attachment_url",
                "form_attachment_filename", "file_type",
                "form_number_reservation_id", "form_number",
                "full_form_number", "collects_personal_info",
                "created_at", "updated_at",
            }
            assert expected_keys == set(item.keys())

    def test_form_detail_returns_all_fields(self, auth_client_with_read):
        """TC1.13b: Detail response includes all expected fields."""
        client, form = auth_client_with_read
        resp = client.get(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "FEAT-0018 Test Form"
        assert data["collects_personal_info"] == "Yes"
        assert data["form_source"] == "URL"

    def test_autocomplete_returns_suggestions(self, auth_client_with_read):
        """TC1.13c: Autocomplete returns query and suggestions list."""
        client, _ = auth_client_with_read
        resp = client.get("/api/v1/forms/autocomplete", params={"q": "FEAT"})
        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)

    def test_form_list_pagination_works(self, auth_client_with_read):
        """TC1.13d: Pagination parameters still work correctly."""
        client, _ = auth_client_with_read
        resp = client.get("/api/v1/forms", params={"skip": 0, "limit": 25})
        assert resp.status_code == 200
        data = resp.json()
        assert data["skip"] == 0
        assert data["limit"] == 25

    def test_authenticated_user_gets_404_for_nonexistent_form(self, auth_client_with_read):
        """EC-003: Authenticated user with form:read gets 404 for non-existent form."""
        client, _ = auth_client_with_read
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/forms/{fake_id}")
        assert resp.status_code == 404
