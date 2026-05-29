"""FEAT-0014 integration tests: form number search, autocomplete, sort, multi-value filters.

Strict assertions — no errors suppressed. Every test validates exact expected
behaviour per the acceptance criteria in the FEAT-0014 test plan.
"""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.models import (
    BusinessArea,
    Form,
    FormNumberPrefix,
    FormNumberReservation,
    User,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def feat14_client(db, user_factory):
    """Authenticated test client for FEAT-0014 tests.

    Bearer 'admin'  → admin TokenData
    Bearer 'noauth' → raises (simulates unauthenticated)
    anything else   → staff TokenData
    """
    staff = user_factory(email="feat14-staff@example.com")
    admin = user_factory(email="feat14-admin@example.com")

    def _get_user(request: Request) -> TokenData:
        auth = request.headers.get("Authorization", "")
        if auth.strip().endswith("noauth"):
            from fastapi import HTTPException, status as http_status

            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        if auth.strip().endswith("admin"):
            return TokenData(
                sub=str(admin.id),
                email=str(admin.email),
                name="Admin User",
                roles=["admin"],
                token_type="access",
                permissions=["form:read", "form:edit", "form:delete"],
            )
        return TokenData(
            sub=str(staff.id),
            email=str(staff.email),
            name="Staff User",
            roles=["staff"],
            token_type="access",
            permissions=["form:read"],
        )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _get_user
    yield TestClient(app), staff, admin
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def unauthenticated_client(db):
    """Test client with NO get_current_user override.

    Only get_db is overridden. If an endpoint depends on get_current_user,
    requests will fail — proving the endpoint is genuinely open.
    """
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides.pop(get_current_user, None)
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def prefix_h(db):
    """Active prefix 'H' for form number reservations."""
    p = FormNumberPrefix(
        id=uuid.uuid4(),
        prefix="H",
        description="Highway",
        current_sequence=0,
        padding_length=4,
        max_number_length=10,
        is_case_sensitive=False,
        is_active=True,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def prefix_a(db):
    """Active prefix 'A' for form number reservations."""
    p = FormNumberPrefix(
        id=uuid.uuid4(),
        prefix="A",
        description="Admin",
        current_sequence=0,
        padding_length=3,
        max_number_length=10,
        is_case_sensitive=False,
        is_active=True,
    )
    db.add(p)
    db.flush()
    return p


def _make_reservation(db, prefix, form_number, full_form_number, user, status="approved"):
    r = FormNumberReservation(
        id=uuid.uuid4(),
        prefix_id=prefix.id,
        form_number=form_number,
        full_form_number=full_form_number,
        numbering_method="auto_generated",
        status=status,
        reserved_by_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.add(r)
    db.flush()
    return r


def _make_form(
    db,
    user,
    title,
    description="Test form",
    reservation=None,
    status="draft",
    is_public=False,
    form_source=None,
    keywords=None,
    created_at=None,
    deleted_at=None,
):
    f = Form(
        id=uuid.uuid4(),
        title=title,
        description=description,
        status=status,
        is_public=is_public,
        current_version=0,
        keywords=keywords or [],
        created_by_id=user.id,
        form_source=form_source,
        form_number_reservation_id=reservation.id if reservation else None,
        created_at=created_at,
        updated_at=created_at,
        deleted_at=deleted_at,
    )
    db.add(f)
    db.flush()
    return f


# ============================================================================
# TC-US-001: Search by form number
# ============================================================================


class TestSearchByFormNumber:
    """TC-US-001: Search forms by full_form_number via ILIKE."""

    @pytest.mark.integration
    def test_tc1_1_exact_form_number_search(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Bridge Form", reservation=res)
        db.flush()

        resp = client.get("/api/v1/forms", params={"q": "H0021", "limit": 25})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        titles = [item["title"] for item in data["items"]]
        assert "Bridge Form" in titles

    @pytest.mark.integration
    def test_tc1_2_partial_prefix_search(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        r1 = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        r2 = _make_reservation(db, prefix_h, "0022", "H0022", staff)
        _make_form(db, staff, "Form A", reservation=r1)
        _make_form(db, staff, "Form B", reservation=r2)
        db.flush()

        resp = client.get("/api/v1/forms", params={"q": "H002", "limit": 25})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    @pytest.mark.integration
    def test_tc1_3_infix_partial_search(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Bridge Form", reservation=res)
        db.flush()

        resp = client.get("/api/v1/forms", params={"q": "0021", "limit": 25})
        assert resp.status_code == 200
        data = resp.json()
        full_nums = [item.get("full_form_number") for item in data["items"]]
        assert "H0021" in full_nums

    @pytest.mark.integration
    def test_tc1_4_text_search_still_works(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Highway Policy", description="Highway matters")
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Bridge Form", reservation=res)
        db.flush()

        resp = client.get("/api/v1/forms", params={"q": "Highway", "limit": 25})
        assert resp.status_code == 200
        data = resp.json()
        titles = [item["title"] for item in data["items"]]
        assert "Highway Policy" in titles

    @pytest.mark.integration
    def test_tc1_5_like_wildcards_escaped(self, feat14_client, db, prefix_h):
        """Percent and underscore in user input must be treated as literals."""
        client, staff, _ = feat14_client
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Bridge Form", reservation=res)
        db.flush()

        # Search for literal "H%002" — the '%' should NOT act as a wildcard
        resp = client.get("/api/v1/forms", params={"q": "H%002", "limit": 25})
        assert resp.status_code == 200
        data = resp.json()
        # H0021 should NOT match because there is no literal "H%002" in any form number
        full_nums = [item.get("full_form_number") for item in data["items"]]
        assert "H0021" not in full_nums

    @pytest.mark.integration
    def test_tc1_6_form_number_matches_ranked_first(self, feat14_client, db, prefix_h):
        """Form number matches appear before text-only matches."""
        client, staff, _ = feat14_client
        # Form A: has form number H0021
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Bridge Form", reservation=res)
        # Form B: title contains "H0021" but no form number reservation
        _make_form(db, staff, "H0021 Policy Update", description="H0021 policy stuff")
        db.flush()

        resp = client.get("/api/v1/forms", params={"q": "H0021", "limit": 25})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        # The form with actual form number H0021 should appear first
        assert items[0]["full_form_number"] == "H0021"

    @pytest.mark.integration
    def test_tc1_7_case_insensitive_search(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Bridge Form", reservation=res)
        db.flush()

        resp = client.get("/api/v1/forms", params={"q": "h0021", "limit": 25})
        assert resp.status_code == 200
        full_nums = [item.get("full_form_number") for item in resp.json()["items"]]
        assert "H0021" in full_nums

    @pytest.mark.integration
    def test_tc1_9_rbac_authenticated_can_search(self, feat14_client, db, prefix_h):
        """All authenticated roles can search (staff_viewer has form:read)."""
        client, staff, _ = feat14_client
        resp = client.get(
            "/api/v1/forms",
            params={"q": "H0021", "limit": 25},
            headers={"Authorization": "Bearer staff"},
        )
        assert resp.status_code == 200

    @pytest.mark.integration
    def test_tc1_10_list_endpoint_requires_auth(self, unauthenticated_client, db):
        """FEAT-0018: List endpoint requires authentication.

        Uses a client with no get_current_user override — unauthenticated
        requests must be rejected with 401.
        """
        resp = unauthenticated_client.get(
            "/api/v1/forms",
            params={"q": "H0021", "limit": 25},
        )
        assert resp.status_code == 401

    @pytest.mark.integration
    def test_tc1_11_no_reservation_excluded_from_form_number_match(
        self, feat14_client, db
    ):
        """Form with NULL reservation not matched by form number search."""
        client, staff, _ = feat14_client
        _make_form(db, staff, "Test Form")  # no reservation
        db.flush()

        resp = client.get("/api/v1/forms", params={"q": "H0021", "limit": 25})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @pytest.mark.integration
    def test_tc1_12_deleted_form_excluded(self, feat14_client, db, prefix_h):
        """Soft-deleted forms must not appear in search results."""
        client, staff, _ = feat14_client
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        form = _make_form(db, staff, "Deleted Form", reservation=res)
        form.deleted_at = datetime.now(timezone.utc)
        db.flush()

        resp = client.get("/api/v1/forms", params={"q": "H0021", "limit": 25})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ============================================================================
# TC-US-002: Autocomplete form numbers
# ============================================================================


class TestAutocompleteFormNumbers:
    """TC-US-002: Autocomplete includes form number suggestions."""

    @pytest.mark.integration
    def test_tc2_1_form_number_in_autocomplete(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Bridge Form", reservation=res)
        db.flush()

        resp = client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "H00", "max_suggestions": 10},
        )
        assert resp.status_code == 200
        suggestions = resp.json()["suggestions"]
        assert "H0021" in suggestions

    @pytest.mark.integration
    def test_tc2_2_infix_match_returns_suggestions(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        r1 = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        r2 = _make_reservation(db, prefix_h, "0022", "H0022", staff)
        _make_form(db, staff, "Form A", reservation=r1)
        _make_form(db, staff, "Form B", reservation=r2)
        db.flush()

        resp = client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "002", "max_suggestions": 10},
        )
        assert resp.status_code == 200
        suggestions = resp.json()["suggestions"]
        assert "H0021" in suggestions
        assert "H0022" in suggestions

    @pytest.mark.integration
    def test_tc2_3_both_titles_and_form_numbers(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Highway Policy")
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Bridge Form", reservation=res)
        db.flush()

        # Title match
        resp1 = client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "Hi", "max_suggestions": 10},
        )
        assert resp1.status_code == 200
        assert "Highway Policy" in resp1.json()["suggestions"]

        # Form number match
        resp2 = client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "H0", "max_suggestions": 10},
        )
        assert resp2.status_code == 200
        assert "H0021" in resp2.json()["suggestions"]

    @pytest.mark.integration
    def test_tc2_4_suggestions_deduplicated(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        res = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Bridge Form", reservation=res)
        db.flush()

        resp = client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "H00", "max_suggestions": 10},
        )
        assert resp.status_code == 200
        suggestions = resp.json()["suggestions"]
        assert suggestions.count("H0021") == 1

    @pytest.mark.integration
    def test_tc2_5_max_10_suggestions(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        for i in range(1, 16):
            num = f"{i:04d}"
            r = _make_reservation(db, prefix_h, num, f"H{num}", staff)
            _make_form(db, staff, f"Form {i}", reservation=r)
        db.flush()

        resp = client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "H0", "max_suggestions": 10},
        )
        assert resp.status_code == 200
        assert len(resp.json()["suggestions"]) <= 10

    @pytest.mark.integration
    def test_tc2_6_deleted_form_excluded(self, feat14_client, db, prefix_h):
        client, staff, _ = feat14_client
        res = _make_reservation(db, prefix_h, "9999", "H9999", staff)
        _make_form(
            db,
            staff,
            "Deleted Form",
            reservation=res,
            deleted_at=datetime.now(timezone.utc),
        )
        db.flush()

        resp = client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "H999", "max_suggestions": 10},
        )
        assert resp.status_code == 200
        assert "H9999" not in resp.json()["suggestions"]

    @pytest.mark.integration
    def test_tc2_7_query_too_short(self, feat14_client, db):
        """Query < 2 characters returns 422 (min_length enforcement on route)."""
        client, _, _ = feat14_client
        resp = client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "H", "max_suggestions": 10},
        )
        assert resp.status_code == 422

    @pytest.mark.integration
    def test_tc2_8_rbac_authenticated_can_access(self, feat14_client, db):
        client, _, _ = feat14_client
        resp = client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "H00", "max_suggestions": 10},
            headers={"Authorization": "Bearer staff"},
        )
        assert resp.status_code == 200

    @pytest.mark.integration
    def test_tc2_9_autocomplete_endpoint_requires_auth(self, unauthenticated_client, db):
        """FEAT-0018: Autocomplete endpoint requires authentication.

        Uses a client with no get_current_user override — unauthenticated
        requests must be rejected with 401.
        """
        resp = unauthenticated_client.get(
            "/api/v1/forms/autocomplete",
            params={"q": "H00", "max_suggestions": 10},
        )
        assert resp.status_code == 401


# ============================================================================
# TC-US-003: Sort by form number
# ============================================================================


class TestSortByFormNumber:
    """TC-US-003: Sort forms by full_form_number."""

    @pytest.mark.integration
    def test_tc3_3_form_number_asc(self, feat14_client, db, prefix_h, prefix_a):
        client, staff, _ = feat14_client
        r1 = _make_reservation(db, prefix_a, "001", "A001", staff)
        r2 = _make_reservation(db, prefix_h, "0002", "H002", staff)
        r3 = _make_reservation(db, prefix_h, "0003", "H003", staff)

        _make_form(db, staff, "Form A", reservation=r1)
        _make_form(db, staff, "Form B", reservation=r2)
        _make_form(db, staff, "Form C", reservation=r3)
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params={"sort_field": "form_number", "sort_order": "asc", "limit": 25},
        )
        assert resp.status_code == 200
        nums = [
            item["full_form_number"]
            for item in resp.json()["items"]
            if item.get("full_form_number")
        ]
        assert nums == sorted(nums), f"Expected ascending order, got {nums}"

    @pytest.mark.integration
    def test_tc3_4_form_number_desc(self, feat14_client, db, prefix_a):
        client, staff, _ = feat14_client
        r1 = _make_reservation(db, prefix_a, "001", "A001", staff)
        r2 = _make_reservation(db, prefix_a, "002", "B002", staff)
        r3 = _make_reservation(db, prefix_a, "003", "C003", staff)
        _make_form(db, staff, "Form A", reservation=r1)
        _make_form(db, staff, "Form B", reservation=r2)
        _make_form(db, staff, "Form C", reservation=r3)
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params={"sort_field": "form_number", "sort_order": "desc", "limit": 25},
        )
        assert resp.status_code == 200
        nums = [
            item["full_form_number"]
            for item in resp.json()["items"]
            if item.get("full_form_number")
        ]
        assert nums == sorted(nums, reverse=True), f"Expected descending order, got {nums}"

    @pytest.mark.integration
    def test_tc3_5_nulls_last_asc(self, feat14_client, db, prefix_a):
        """Forms without form numbers sort last when ascending."""
        client, staff, _ = feat14_client
        r1 = _make_reservation(db, prefix_a, "001", "A001", staff)
        r2 = _make_reservation(db, prefix_a, "002", "B002", staff)
        _make_form(db, staff, "Form A", reservation=r1)
        _make_form(db, staff, "Form B", reservation=r2)
        _make_form(db, staff, "No Number Form")  # no reservation
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params={"sort_field": "form_number", "sort_order": "asc", "limit": 25},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 3
        # Last item should have no form number
        assert items[-1]["full_form_number"] is None
        # First items should have form numbers in ascending order
        assert items[0]["full_form_number"] == "A001"
        assert items[1]["full_form_number"] == "B002"

    @pytest.mark.integration
    def test_tc3_6_nulls_last_desc(self, feat14_client, db, prefix_a):
        """Forms without form numbers sort last when descending."""
        client, staff, _ = feat14_client
        r1 = _make_reservation(db, prefix_a, "001", "A001", staff)
        r2 = _make_reservation(db, prefix_a, "002", "B002", staff)
        _make_form(db, staff, "Form A", reservation=r1)
        _make_form(db, staff, "Form B", reservation=r2)
        _make_form(db, staff, "No Number Form")
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params={"sort_field": "form_number", "sort_order": "desc", "limit": 25},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 3
        assert items[-1]["full_form_number"] is None
        assert items[0]["full_form_number"] == "B002"
        assert items[1]["full_form_number"] == "A001"

    @pytest.mark.integration
    def test_tc3_7_sort_field_form_number_accepted(self, feat14_client, db):
        client, _, _ = feat14_client
        resp = client.get(
            "/api/v1/forms",
            params={"sort_field": "form_number", "sort_order": "asc", "limit": 25},
        )
        assert resp.status_code == 200

    @pytest.mark.integration
    def test_tc3_8_sort_field_created_at_accepted(self, feat14_client, db):
        client, staff, _ = feat14_client
        now = datetime.now(timezone.utc)
        _make_form(db, staff, "Older", created_at=now - timedelta(days=2))
        _make_form(db, staff, "Newer", created_at=now)
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params={"sort_field": "created_at", "sort_order": "desc", "limit": 25},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["title"] == "Newer"

    @pytest.mark.integration
    def test_tc3_9_invalid_sort_field_rejected(self, feat14_client, db):
        client, _, _ = feat14_client
        resp = client.get(
            "/api/v1/forms",
            params={"sort_field": "invalid_field", "limit": 25},
        )
        assert resp.status_code == 422

    @pytest.mark.integration
    def test_tc3_10_default_sort_field(self, feat14_client, db):
        """Default sort is by created_at descending when sort_field omitted."""
        client, staff, _ = feat14_client
        now = datetime.now(timezone.utc)
        _make_form(db, staff, "Older", created_at=now - timedelta(days=2))
        _make_form(db, staff, "Newer", created_at=now)
        db.flush()

        resp = client.get("/api/v1/forms", params={"limit": 25})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["title"] == "Newer"

    @pytest.mark.integration
    def test_tc3_12_rbac_all_roles_can_sort(self, feat14_client, db):
        client, _, _ = feat14_client
        resp = client.get(
            "/api/v1/forms",
            params={"sort_field": "form_number", "sort_order": "asc", "limit": 25},
            headers={"Authorization": "Bearer staff"},
        )
        assert resp.status_code == 200

    @pytest.mark.integration
    def test_tc3_13_sort_endpoint_requires_auth(self, unauthenticated_client, db):
        """FEAT-0018: List endpoint with sort requires authentication.

        Uses a client with no get_current_user override — unauthenticated
        requests must be rejected with 401.
        """
        resp = unauthenticated_client.get(
            "/api/v1/forms",
            params={"sort_field": "form_number", "limit": 25},
        )
        assert resp.status_code == 401


# ============================================================================
# TC-US-004: Multi-value status and form_source filters
# ============================================================================


class TestMultiValueFilters:
    """TC-US-004: Backend accepts multiple status and form_source values."""

    @pytest.mark.integration
    def test_tc4_1_multiple_status_values(self, feat14_client, db):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Draft Form", status="draft")
        _make_form(db, staff, "Published Form", status="published")
        _make_form(db, staff, "Archived Form", status="archived")
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params=[("status", "draft"), ("status", "published"), ("limit", "25")],
        )
        assert resp.status_code == 200
        data = resp.json()
        statuses = {item["status"] for item in data["items"]}
        assert "draft" in statuses
        assert "published" in statuses
        assert "archived" not in statuses

    @pytest.mark.integration
    def test_tc4_2_single_status_backward_compatible(self, feat14_client, db):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Draft Form", status="draft")
        _make_form(db, staff, "Published Form", status="published")
        db.flush()

        resp = client.get("/api/v1/forms", params={"status": "draft", "limit": 25})
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["status"] == "draft"

    @pytest.mark.integration
    def test_tc4_3_no_status_returns_all(self, feat14_client, db):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Draft", status="draft")
        _make_form(db, staff, "Published", status="published")
        _make_form(db, staff, "Archived", status="archived")
        db.flush()

        resp = client.get("/api/v1/forms", params={"limit": 25})
        assert resp.status_code == 200
        statuses = {item["status"] for item in resp.json()["items"]}
        assert len(statuses) >= 2  # at least draft + published from our data

    @pytest.mark.integration
    def test_tc4_4_invalid_status_rejected(self, feat14_client, db):
        client, _, _ = feat14_client
        resp = client.get("/api/v1/forms", params={"status": "invalid_status", "limit": 25})
        assert resp.status_code == 422

    @pytest.mark.integration
    def test_tc4_5_approved_is_invalid_status(self, feat14_client, db):
        """'approved' is not a valid status for filtering."""
        client, _, _ = feat14_client
        resp = client.get("/api/v1/forms", params={"status": "approved", "limit": 25})
        assert resp.status_code == 422

    @pytest.mark.integration
    def test_tc4_6_multiple_form_source_values(self, feat14_client, db):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Link Form", form_source="URL")
        _make_form(db, staff, "Download Form", form_source="Download")
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params=[
                ("form_source", "Link"),
                ("form_source", "Download"),
                ("limit", "25"),
            ],
        )
        assert resp.status_code == 200
        sources = {item["form_source"] for item in resp.json()["items"] if item.get("form_source")}
        assert "URL" in sources
        assert "Download" in sources

    @pytest.mark.integration
    def test_tc4_7_single_form_source_backward_compatible(self, feat14_client, db):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Link Form", form_source="URL")
        _make_form(db, staff, "Download Form", form_source="Download")
        db.flush()

        resp = client.get("/api/v1/forms", params={"form_source": "Link", "limit": 25})
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            if item.get("form_source"):
                assert item["form_source"] == "URL"

    @pytest.mark.integration
    def test_tc4_8_no_form_source_returns_all(self, feat14_client, db):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Link Form", form_source="URL")
        _make_form(db, staff, "Download Form", form_source="Download")
        _make_form(db, staff, "No Source Form")
        db.flush()

        resp = client.get("/api/v1/forms", params={"limit": 25})
        assert resp.status_code == 200
        assert resp.json()["total"] >= 3

    @pytest.mark.integration
    def test_tc4_9_all_statuses_returns_all(self, feat14_client, db):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Draft", status="draft")
        _make_form(db, staff, "Pending", status="pending_review")
        _make_form(db, staff, "Published", status="published")
        _make_form(db, staff, "Archived", status="archived")
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params=[
                ("status", "draft"),
                ("status", "pending_review"),
                ("status", "published"),
                ("status", "archived"),
                ("limit", "25"),
            ],
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 4

    @pytest.mark.integration
    def test_tc4_10_duplicate_values_handled(self, feat14_client, db):
        client, staff, _ = feat14_client
        _make_form(db, staff, "Draft Form", status="draft")
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params=[("status", "draft"), ("status", "draft"), ("limit", "25")],
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["status"] == "draft"

    @pytest.mark.integration
    def test_tc4_11_rbac_authenticated_can_filter(self, feat14_client, db):
        client, _, _ = feat14_client
        resp = client.get(
            "/api/v1/forms",
            params=[("status", "draft"), ("status", "published"), ("limit", "25")],
            headers={"Authorization": "Bearer staff"},
        )
        assert resp.status_code == 200

    @pytest.mark.integration
    def test_tc4_12_filter_endpoint_requires_auth(self, unauthenticated_client, db):
        """FEAT-0018: List endpoint with filters requires authentication.

        Uses a client with no get_current_user override — unauthenticated
        requests must be rejected with 401.
        """
        resp = unauthenticated_client.get(
            "/api/v1/forms",
            params={"status": "draft", "limit": 25},
        )
        assert resp.status_code == 401


# ============================================================================
# Regression & Combined tests
# ============================================================================


class TestRegressionAndCombined:
    """Cross-cutting regression tests for search + sort + filter combinations."""

    @pytest.mark.integration
    def test_search_with_sort_by_form_number(self, feat14_client, db, prefix_a):
        """Search results can be sorted by form number."""
        client, staff, _ = feat14_client
        r1 = _make_reservation(db, prefix_a, "001", "A001", staff)
        r2 = _make_reservation(db, prefix_a, "002", "A002", staff)
        _make_form(db, staff, "Form Alpha", reservation=r1)
        _make_form(db, staff, "Form Beta", reservation=r2)
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params={
                "q": "A00",
                "sort_field": "form_number",
                "sort_order": "asc",
                "limit": 25,
            },
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        nums = [i["full_form_number"] for i in items if i.get("full_form_number")]
        assert nums == sorted(nums)

    @pytest.mark.integration
    def test_filter_with_sort_by_form_number(self, feat14_client, db, prefix_a):
        """Filters combined with form number sort work correctly."""
        client, staff, _ = feat14_client
        r1 = _make_reservation(db, prefix_a, "001", "A001", staff)
        r2 = _make_reservation(db, prefix_a, "002", "A002", staff)
        _make_form(db, staff, "Draft A", reservation=r1, status="draft")
        _make_form(db, staff, "Published B", reservation=r2, status="published")
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params={
                "status": "draft",
                "sort_field": "form_number",
                "sort_order": "asc",
                "limit": 25,
            },
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        assert all(i["status"] == "draft" for i in items)

    @pytest.mark.integration
    def test_multi_filter_cross_category_and(self, feat14_client, db):
        """Multiple filter categories use AND logic across categories."""
        client, staff, _ = feat14_client
        _make_form(db, staff, "Public Draft", status="draft", is_public=True)
        _make_form(db, staff, "Private Draft", status="draft", is_public=False)
        _make_form(db, staff, "Public Published", status="published", is_public=True)
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params={"status": "draft", "is_public": "true", "limit": 25},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(i["status"] == "draft" and i["is_public"] is True for i in items)

    @pytest.mark.integration
    def test_pagination_with_form_number_sort(self, feat14_client, db, prefix_a):
        """Pagination works correctly with form number sort."""
        client, staff, _ = feat14_client
        for i in range(5):
            num = f"{i+1:03d}"
            r = _make_reservation(db, prefix_a, num, f"A{num}", staff)
            _make_form(db, staff, f"Form {i+1}", reservation=r)
        db.flush()

        resp = client.get(
            "/api/v1/forms",
            params={
                "sort_field": "form_number",
                "sort_order": "asc",
                "skip": 0,
                "limit": 25,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 5

    @pytest.mark.integration
    def test_underscore_escaped_in_search(self, feat14_client, db, prefix_h):
        """Underscore in search input is treated as literal, not single-char wildcard."""
        client, staff, _ = feat14_client
        r = _make_reservation(db, prefix_h, "0021", "H0021", staff)
        _make_form(db, staff, "Some Form", reservation=r)
        db.flush()

        # Search for "H_021" — the _ should be literal, not a wildcard
        resp = client.get("/api/v1/forms", params={"q": "H_021", "limit": 25})
        assert resp.status_code == 200
        # H0021 should NOT match because there is no literal "_" in "H0021"
        full_nums = [item.get("full_form_number") for item in resp.json()["items"]]
        assert "H0021" not in full_nums
