"""FEAT-0030 US-012: deterministic Staff Forms sorting contracts."""

from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import (
    Form,
    FormNumberPrefix,
    FormNumberReservation,
    Role,
    UserRole,
)
from backend.services.forms import FormService


COLLATION_SQL = """
CREATE COLLATION IF NOT EXISTS public.forms_title_en_natural_ci (
    provider = icu,
    locale = 'en-u-kn-ks-level2',
    deterministic = false
)
"""


@pytest.fixture(autouse=True)
def title_sort_collation(db):
    db.execute(text(COLLATION_SQL))


@pytest.fixture()
def forms_client(db, user_factory):
    user = user_factory(email="us012-reader@example.com")
    role = Role(
        id=uuid.uuid4(),
        name=f"us012_reader_{uuid.uuid4().hex}",
        permissions=["form:read"],
        is_system=False,
        is_active=True,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()
    token = TokenData(
        sub=str(user.id),
        email=user.email,
        name="US-012 Reader",
        roles=["staff"],
        token_type="access",
        permissions=["form:read"],
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    yield TestClient(app), user
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def _make_form(db, user, *, form_id, title, created_at, reservation=None):
    form = Form(
        id=uuid.UUID(form_id),
        title=title,
        description="US-012 deterministic sort fixture",
        status="published",
        is_public=False,
        current_version=0,
        keywords=[],
        created_by_id=user.id,
        form_number_reservation_id=reservation.id if reservation else None,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(form)
    db.flush()
    return form


def _list_ids(db, *, sort_field, sort_order, q=None, skip=0, limit=100):
    forms, total = FormService.list_forms(
        db,
        q=q,
        sort_field=sort_field,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )
    return [form.id for form in forms], total


@pytest.mark.integration
@pytest.mark.parametrize(
    ("sort_field", "sort_order"),
    [
        ("suggested", "desc"),
        ("title", "asc"),
        ("title", "desc"),
        ("form_number", "asc"),
        ("form_number", "desc"),
    ],
)
def test_api_accepts_only_approved_sort_combinations(
    forms_client, db, sort_field, sort_order
):
    client, user = forms_client
    _make_form(
        db,
        user,
        form_id="10000000-0000-4000-8000-000000000001",
        title="Approved Sort",
        created_at=datetime(2026, 9, 9, 12, 0, 0),
    )

    response = client.get(
        "/api/v1/forms",
        params={
            "sort_field": sort_field,
            "sort_order": sort_order,
            "limit": 24,
        },
    )

    assert response.status_code == 200
    assert set(response.json()) == {"total", "skip", "limit", "items"}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("sort_field", "sort_order"),
    [
        ("created_at", "asc"),
        ("created_at", "desc"),
        ("suggested", "asc"),
        ("unknown", "asc"),
        ("title", "sideways"),
        ("form_number", "sideways"),
    ],
)
def test_api_rejects_legacy_and_invalid_sort_combinations_without_results(
    forms_client, db, sort_field, sort_order
):
    client, user = forms_client
    form = _make_form(
        db,
        user,
        form_id="10000000-0000-4000-8000-000000000002",
        title="Sensitive Result Sentinel",
        created_at=datetime(2026, 9, 9, 12, 0, 0),
    )

    response = client.get(
        "/api/v1/forms",
        params={
            "sort_field": sort_field,
            "sort_order": sort_order,
            "limit": 24,
        },
    )

    assert response.status_code == 422
    assert set(response.json()) == {"detail"}
    assert str(form.id) not in response.text
    assert form.title not in response.text


@pytest.mark.integration
def test_omitted_sort_matches_suggested_desc(forms_client, db):
    client, user = forms_client
    now = datetime(2026, 9, 9, 12, 0, 0)
    for index, age in enumerate((2, 0, 1), start=1):
        _make_form(
            db,
            user,
            form_id=f"20000000-0000-4000-8000-{index:012d}",
            title=f"Form {index}",
            created_at=now - timedelta(days=age),
        )

    default_response = client.get("/api/v1/forms", params={"limit": 24})
    explicit_response = client.get(
        "/api/v1/forms",
        params={"sort_field": "suggested", "sort_order": "desc", "limit": 24},
    )

    assert default_response.status_code == 200
    assert [item["id"] for item in default_response.json()["items"]] == [
        item["id"] for item in explicit_response.json()["items"]
    ]


@pytest.mark.integration
def test_suggested_orders_created_at_desc_then_id_asc(db, user_factory):
    user = user_factory()
    older = _make_form(
        db,
        user,
        form_id="30000000-0000-4000-8000-000000000003",
        title="Older",
        created_at=datetime(2026, 9, 7, 12, 0, 0),
    )
    tied_high = _make_form(
        db,
        user,
        form_id="30000000-0000-4000-8000-000000000002",
        title="Tied high",
        created_at=datetime(2026, 9, 9, 12, 0, 0),
    )
    tied_low = _make_form(
        db,
        user,
        form_id="30000000-0000-4000-8000-000000000001",
        title="Tied low",
        created_at=datetime(2026, 9, 9, 12, 0, 0),
    )

    first_ids, total = _list_ids(
        db, sort_field="suggested", sort_order="desc"
    )
    repeated_ids, _ = _list_ids(
        db, sort_field="suggested", sort_order="desc"
    )

    assert total == 3
    assert first_ids == [tied_low.id, tied_high.id, older.id]
    assert repeated_ids == first_ids


@pytest.mark.integration
def test_title_sorts_use_natural_english_order_and_stable_ties(
    db, user_factory
):
    user = user_factory()
    base_time = datetime(2026, 9, 9, 12, 0, 0)
    fixtures = [
        ("40000000-0000-4000-8000-000000000001", "eagle", base_time),
        ("40000000-0000-4000-8000-000000000002", "Éclair", base_time),
        ("40000000-0000-4000-8000-000000000003", "Form 2", base_time),
        ("40000000-0000-4000-8000-000000000004", "form 10", base_time),
        ("40000000-0000-4000-8000-000000000005", "The Bridge", base_time),
        ("40000000-0000-4000-8000-000000000006", "Permit", base_time),
        ("40000000-0000-4000-8000-000000000007", "permit", base_time),
        (
            "40000000-0000-4000-8000-000000000008",
            "PERMIT",
            base_time - timedelta(days=1),
        ),
        ("40000000-0000-4000-8000-000000000009", "   ", base_time),
        ("40000000-0000-4000-8000-000000000010", "\t\n", base_time),
        ("40000000-0000-4000-8000-000000000011", "\u00a0", base_time),
    ]
    forms = {
        title + form_id: _make_form(
            db,
            user,
            form_id=form_id,
            title=title,
            created_at=created_at,
        )
        for form_id, title, created_at in fixtures
    }

    asc_ids, _ = _list_ids(db, sort_field="title", sort_order="asc")
    desc_ids, _ = _list_ids(db, sort_field="title", sort_order="desc")
    missing_ids = {
        forms["   40000000-0000-4000-8000-000000000009"].id,
        forms["\t\n40000000-0000-4000-8000-000000000010"].id,
        forms[
            "\u00a040000000-0000-4000-8000-000000000011"
        ].id,
    }
    named_asc = [
        form_id for form_id in asc_ids if form_id not in missing_ids
    ]
    named_desc = [
        form_id for form_id in desc_ids if form_id not in missing_ids
    ]

    assert set(asc_ids[-3:]) == missing_ids
    assert set(desc_ids[-3:]) == missing_ids
    asc_titles = [db.get(Form, form_id).title for form_id in named_asc]
    desc_titles = [db.get(Form, form_id).title for form_id in named_desc]
    assert asc_titles[:5] == ["eagle", "Éclair", "Form 2", "form 10", "Permit"]
    assert asc_titles[5:] == ["permit", "PERMIT", "The Bridge"]
    assert desc_titles == [
        "The Bridge",
        "Permit",
        "permit",
        "PERMIT",
        "form 10",
        "Form 2",
        "Éclair",
        "eagle",
    ]


@pytest.mark.integration
def test_active_search_uses_selected_title_sort_without_number_priority(
    db, user_factory
):
    user = user_factory()
    prefix = FormNumberPrefix(
        id=uuid.UUID("50000000-0000-4000-8000-000000000001"),
        prefix="P",
        description="Priority",
        current_sequence=1,
        padding_length=3,
        max_number_length=20,
        is_case_sensitive=False,
        is_active=True,
    )
    reservation = FormNumberReservation(
        id=uuid.UUID("50000000-0000-4000-8000-000000000002"),
        prefix_id=prefix.id,
        form_number="001",
        full_form_number="PRIORITY001",
        numbering_method="auto_generated",
        status="approved",
        reserved_by_id=user.id,
        expires_at=datetime(2026, 9, 30, 12, 0, 0),
    )
    db.add_all([prefix, reservation])
    db.flush()
    title_match = _make_form(
        db,
        user,
        form_id="50000000-0000-4000-8000-000000000003",
        title="Alpha Priority",
        created_at=datetime(2026, 9, 9, 12, 0, 0),
    )
    number_match = _make_form(
        db,
        user,
        form_id="50000000-0000-4000-8000-000000000004",
        title="Zulu Form",
        created_at=datetime(2026, 9, 8, 12, 0, 0),
        reservation=reservation,
    )

    result_ids, total = _list_ids(
        db,
        q="priority",
        sort_field="title",
        sort_order="asc",
    )

    assert total == 2
    assert result_ids == [title_match.id, number_match.id]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("sort_field", "sort_order"),
    [
        ("suggested", "desc"),
        ("title", "asc"),
        ("title", "desc"),
        ("form_number", "asc"),
        ("form_number", "desc"),
    ],
)
def test_approved_sorts_are_stable_across_page_boundaries(
    db, user_factory, sort_field, sort_order
):
    user = user_factory()
    created_at = datetime(2026, 9, 9, 12, 0, 0)
    expected_ids = []
    for index in range(1, 28):
        form = _make_form(
            db,
            user,
            form_id=f"60000000-0000-4000-8000-{index:012d}",
            title="Equivalent title",
            created_at=created_at,
        )
        expected_ids.append(form.id)

    first_page, total = _list_ids(
        db,
        sort_field=sort_field,
        sort_order=sort_order,
        skip=0,
        limit=24,
    )
    second_page, repeated_total = _list_ids(
        db,
        sort_field=sort_field,
        sort_order=sort_order,
        skip=24,
        limit=24,
    )
    repeated_first_page, _ = _list_ids(
        db,
        sort_field=sort_field,
        sort_order=sort_order,
        skip=0,
        limit=24,
    )

    combined_ids = first_page + second_page
    assert total == repeated_total == 27
    assert combined_ids == expected_ids
    assert len(combined_ids) == len(set(combined_ids)) == 27
    assert repeated_first_page == first_page


def test_sort_migration_extends_head_and_is_reversible(monkeypatch):
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "023_feat_0030_forms_sort_options.py"
    )
    spec = importlib.util.spec_from_file_location(
        "us012_sort_migration", migration_path
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()
    migration.downgrade()

    assert migration.revision == "023_feat_0030_forms_sort_options"
    assert (
        migration.down_revision
        == "022_feat_0030_staff_viewer_forms_only_access"
    )
    assert "provider = icu" in statements[0]
    assert "locale = 'en-u-kn-ks-level2'" in statements[0]
    assert "deterministic = false" in statements[0]
    assert statements[1] == "DROP COLLATION public.forms_title_en_natural_ci"
