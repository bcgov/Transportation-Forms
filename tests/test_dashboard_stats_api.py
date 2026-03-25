"""Tests for GET /api/v1/stats/dashboard (TASK-430)."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import Form, FormNumberReservation, FormNumberPrefix, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(roles: list[str] = None) -> TokenData:
    return TokenData(
        sub=str(uuid.uuid4()),
        email="test@example.com",
        name="Test User",
        roles=roles or ["staff_viewer"],
        token_type="access",
    )


def _client(db, token: TokenData) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    return TestClient(app)


def _anon_client(db) -> TestClient:
    """Client with no auth override — exercises the real 401 path."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides.pop(get_current_user, None)
    return TestClient(app)


def _user(db) -> User:
    """Seed a minimal User row."""
    u = User(
        id=uuid.uuid4(),
        email=f"user-{uuid.uuid4().hex[:6]}@example.com",
        first_name="Test",
        last_name="User",
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def _form(db, *, status: str, deleted: bool = False, created_by: User = None) -> Form:
    """Seed a minimal Form row."""
    if created_by is None:
        created_by = _user(db)
    f = Form(
        id=uuid.uuid4(),
        title=f"Form {uuid.uuid4().hex[:6]}",
        status=status,
        form_source="Download",
        is_public=False,
        created_by_id=created_by.id,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(f)
    db.flush()
    return f


def _prefix(db) -> FormNumberPrefix:
    """Seed a minimal FormNumberPrefix and return it."""
    p = FormNumberPrefix(
        id=uuid.uuid4(),
        prefix=f"TST{uuid.uuid4().hex[:3].upper()}",
        description="Test prefix",
        is_active=True,
    )
    db.add(p)
    db.flush()
    return p


def _reservation(db, *, status: str) -> FormNumberReservation:
    """Seed a minimal FormNumberReservation row."""
    prefix = _prefix(db)
    owner = _user(db)
    seq = uuid.uuid4().hex[:4].upper()
    r = FormNumberReservation(
        id=uuid.uuid4(),
        prefix_id=prefix.id,
        reserved_by_id=owner.id,
        form_number=seq,
        full_form_number=f"{prefix.prefix}-{seq}",
        numbering_method="auto_generated",
        status=status,
    )
    db.add(r)
    db.flush()
    return r


ENDPOINT = "/api/v1/stats/dashboard"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_unauthenticated_returns_401(db):
    """GET /api/v1/stats/dashboard with no token returns HTTP 401."""
    client = _anon_client(db)
    response = client.get(ENDPOINT)
    assert response.status_code == 401


def test_authenticated_empty_db_returns_zero_counts(db):
    """Authenticated staff_viewer on an empty DB returns all-zero counts."""
    client = _client(db, _make_token(["staff_viewer"]))
    response = client.get(ENDPOINT)
    assert response.status_code == 200
    data = response.json()
    assert data["published_forms"] == 0
    assert data["forms_awaiting_approval"] == 0
    assert data["reservations_awaiting_approval"] == 0


def test_published_forms_count(db):
    """Seed 3 published + 2 draft forms; assert published_forms == 3."""
    for _ in range(3):
        _form(db, status="published")
    for _ in range(2):
        _form(db, status="draft")

    client = _client(db, _make_token())
    data = client.get(ENDPOINT).json()
    assert data["published_forms"] == 3


def test_forms_awaiting_approval_count(db):
    """Seed 4 pending_review forms; assert forms_awaiting_approval == 4."""
    for _ in range(4):
        _form(db, status="pending_review")

    client = _client(db, _make_token())
    data = client.get(ENDPOINT).json()
    assert data["forms_awaiting_approval"] == 4


def test_soft_deleted_forms_excluded(db):
    """Seed 2 published forms, soft-delete one; assert published_forms == 1."""
    _form(db, status="published")
    _form(db, status="published", deleted=True)

    client = _client(db, _make_token())
    data = client.get(ENDPOINT).json()
    assert data["published_forms"] == 1


def test_reservations_awaiting_approval_count(db):
    """Seed 5 pending_approval reservations; assert reservations_awaiting_approval == 5."""
    for _ in range(5):
        _reservation(db, status="pending_approval")

    client = _client(db, _make_token())
    data = client.get(ENDPOINT).json()
    assert data["reservations_awaiting_approval"] == 5


def test_all_three_counts_independent(db):
    """Mixed seed: 2 published, 3 pending_review forms, 1 pending_approval reservation."""
    for _ in range(2):
        _form(db, status="published")
    for _ in range(3):
        _form(db, status="pending_review")
    _reservation(db, status="pending_approval")

    client = _client(db, _make_token())
    data = client.get(ENDPOINT).json()
    assert data["published_forms"] == 2
    assert data["forms_awaiting_approval"] == 3
    assert data["reservations_awaiting_approval"] == 1


@pytest.mark.parametrize("role", ["reviewer", "staff_manager", "admin"])
def test_any_portal_role_can_access(db, role):
    """All portal roles can call the endpoint — no role restriction beyond valid JWT."""
    client = _client(db, _make_token([role]))
    response = client.get(ENDPOINT)
    assert response.status_code == 200
    data = response.json()
    assert "published_forms" in data
    assert "forms_awaiting_approval" in data
    assert "reservations_awaiting_approval" in data
