"""FEAT-0032 US-003: contact-based Business Area Manager assignment at login."""

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import literal, text

from backend.auth import form_authorization
from backend.auth.business_area_scope import (
    normalized_email_expression,
    qualifying_contact_area_ids,
    sync_business_area_manager_role,
)
from backend.auth.form_authorization import FormAuthorizationContext
from backend.database import get_db
from backend.main import app
from backend.models import (
    AuditLog,
    BusinessArea,
    BusinessAreaContact,
    Form,
    Role,
    User,
    UserRole,
)
from backend.routes import auth as auth_routes
from backend.seeds.default_roles import seed_default_roles


@pytest.fixture()
def login_client(db, monkeypatch):
    seed_default_roles(db)
    app.dependency_overrides[get_db] = lambda: db
    original_startup = list(app.router.on_startup)
    original_auth_states = dict(auth_routes._auth_states)
    app.router.on_startup.clear()
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        lambda state, redirect_uri=None: f"https://keycloak.example/auth?state={state}",
    )
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "exchange_code_for_token",
        lambda code, redirect_uri=None: {
            "access_token": "kc-access",
            "refresh_token": "kc-refresh",
        },
    )
    client = TestClient(app)
    yield client
    client.close()
    app.router.on_startup[:] = original_startup
    auth_routes._auth_states.clear()
    auth_routes._auth_states.update(original_auth_states)
    app.dependency_overrides.pop(get_db, None)


def _login(client, monkeypatch, email):
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_user_info",
        lambda token: {
            "sub": str(uuid.uuid5(uuid.NAMESPACE_URL, email)),
            "email": email,
            "given_name": "Contact",
            "family_name": "User",
        },
    )
    state = client.post("/api/v1/auth/login").json()["state"]
    response = client.post("/api/v1/auth/callback", json={"code": "ok", "state": state})
    assert response.status_code == 200
    return response.json()


def _role(db, name):
    return db.query(Role).filter(Role.name == name).one()


def _grant(db, user, role_name):
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=_role(db, role_name).id))
    db.flush()


def _area(db, *, deleted=False):
    area = BusinessArea(
        id=uuid.uuid4(),
        name=f"US-003 {uuid.uuid4().hex}",
        deleted_at=datetime(2026, 1, 1) if deleted else None,
    )
    db.add(area)
    db.flush()
    return area


def _email_contact(db, area, email):
    contact = BusinessAreaContact(
        id=uuid.uuid4(), business_area_id=area.id, name="Contact", email=email
    )
    db.add(contact)
    db.flush()
    return contact


def _linked_contact(db, area, user):
    contact = BusinessAreaContact(
        id=uuid.uuid4(), business_area_id=area.id, contact_user_id=user.id
    )
    db.add(contact)
    db.flush()
    return contact


def _manager_membership(db, user):
    return (
        db.query(UserRole)
        .filter(
            UserRole.user_id == user.id,
            UserRole.role_id == _role(db, "business_area_manager").id,
        )
        .one_or_none()
    )


async def _scope(db, user):
    return (
        await FormAuthorizationContext.load(str(user.id), db)
    ).active_business_area_ids


@pytest.mark.asyncio
async def test_tc_003_1_email_match_ignores_case_and_surrounding_whitespace(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="Person.One@Example.test")
    area = _area(db)
    _email_contact(db, area, "  PERSON.one@example.TEST  ")

    payload = _login(login_client, monkeypatch, "Person.One@Example.test")

    assert "business_area_manager" in payload["user"]["roles"]
    assert await _scope(db, user) == {area.id}


@pytest.mark.asyncio
async def test_tc_003_2_linked_contact_uses_linked_account(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="linked.contact@example.test")
    area = _area(db)
    _linked_contact(db, area, user)

    payload = _login(login_client, monkeypatch, user.email)

    assert "business_area_manager" in payload["user"]["roles"]
    assert await _scope(db, user) == {area.id}


@pytest.mark.asyncio
async def test_tc_003_3_multiple_areas_union_and_existing_roles_retained(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="multi.area@example.test")
    _grant(db, user, "staff_viewer")
    area_a, area_b = _area(db), _area(db)
    _linked_contact(db, area_a, user)
    _email_contact(db, area_b, "MULTI.AREA@example.test")

    payload = _login(login_client, monkeypatch, user.email)

    assert set(payload["user"]["roles"]) == {"staff_viewer", "business_area_manager"}
    assert await _scope(db, user) == {area_a.id, area_b.id}


def test_tc_003_4_admin_contact_keeps_admin_and_gains_manager(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="admin.contact@example.test")
    _grant(db, user, "admin")
    _linked_contact(db, _area(db), user)

    payload = _login(login_client, monkeypatch, user.email)

    assert set(payload["user"]["roles"]) == {"admin", "business_area_manager"}


@pytest.mark.asyncio
async def test_tc_003_5_removing_one_area_keeps_remaining_scope(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="two.areas@example.test")
    area_a, area_b = _area(db), _area(db)
    contact_a = _linked_contact(db, area_a, user)
    _linked_contact(db, area_b, user)
    _login(login_client, monkeypatch, user.email)

    db.delete(contact_a)
    db.flush()
    payload = _login(login_client, monkeypatch, user.email)

    assert "business_area_manager" in payload["user"]["roles"]
    assert await _scope(db, user) == {area_b.id}


@pytest.mark.asyncio
async def test_tc_003_6_final_contact_removal_revokes_role_at_next_login(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="final.contact@example.test")
    _grant(db, user, "staff_viewer")
    contact = _linked_contact(db, _area(db), user)
    _login(login_client, monkeypatch, user.email)
    granted = _manager_membership(db, user)
    assert granted is not None and granted.deleted_at is None

    db.delete(contact)
    db.flush()
    payload = _login(login_client, monkeypatch, user.email)

    assert payload["user"]["roles"] == ["staff_viewer"]
    db.refresh(granted)
    assert granted.deleted_at is not None
    context = await FormAuthorizationContext.load(str(user.id), db)
    assert "form:edit:business_area" not in context.permissions
    assert context.active_business_area_ids == frozenset()


def test_manually_assigned_manager_without_contact_is_revoked(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="manual.manager@example.test")
    _grant(db, user, "staff_viewer")
    _grant(db, user, "business_area_manager")

    payload = _login(login_client, monkeypatch, user.email)

    assert payload["user"]["roles"] == ["staff_viewer"]
    assert _manager_membership(db, user).deleted_at is not None


def test_regrant_reactivates_the_same_membership(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="regrant@example.test")
    _grant(db, user, "staff_viewer")
    area = _area(db)
    contact = _linked_contact(db, area, user)
    _login(login_client, monkeypatch, user.email)
    membership_id = _manager_membership(db, user).id
    db.delete(contact)
    db.flush()
    _login(login_client, monkeypatch, user.email)

    _email_contact(db, area, user.email)
    payload = _login(login_client, monkeypatch, user.email)

    membership = _manager_membership(db, user)
    assert "business_area_manager" in payload["user"]["roles"]
    assert membership.id == membership_id
    assert membership.deleted_at is None
    assert membership.assigned_by_id is None


@pytest.mark.asyncio
async def test_tc_003_7_soft_deleted_area_grants_no_role_or_scope(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="deleted.area@example.test")
    _grant(db, user, "staff_viewer")
    _linked_contact(db, _area(db, deleted=True), user)
    _email_contact(db, _area(db, deleted=True), user.email)

    payload = _login(login_client, monkeypatch, user.email)

    assert "business_area_manager" not in payload["user"]["roles"]
    assert _manager_membership(db, user) is None
    assert qualifying_contact_area_ids(db, user.id) == frozenset()
    _grant(db, user, "business_area_manager")
    assert await _scope(db, user) == frozenset()


def test_tc_003_8_no_matching_contact_grants_nothing(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="no.match@example.test")
    _grant(db, user, "staff_viewer")
    other = user_factory(email="someone.else@example.test")
    area = _area(db)
    _linked_contact(db, area, other)
    _email_contact(db, area, "no.match@example.test.other")

    payload = _login(login_client, monkeypatch, user.email)

    assert payload["user"]["roles"] == ["staff_viewer"]
    assert _manager_membership(db, user) is None


def test_tc_003_9_only_existing_login_audit_is_recorded(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="audit.contact@example.test")
    _grant(db, user, "staff_viewer")
    contact = _linked_contact(db, _area(db), user)
    before = db.query(AuditLog).count()

    _login(login_client, monkeypatch, user.email)
    db.delete(contact)
    db.flush()
    _login(login_client, monkeypatch, user.email)

    new_audits = db.query(AuditLog).order_by(AuditLog.created_at).all()[before:]
    assert [audit.action for audit in new_audits] == ["LOGIN", "LOGIN"]
    assert all(audit.entity_type == "auth" for audit in new_audits)


def test_first_login_bootstrap_still_assigns_staff_viewer(
    db, login_client, monkeypatch
):
    payload = _login(login_client, monkeypatch, "brand.new@example.test")

    assert payload["user"]["roles"] == ["staff_viewer"]


def test_first_login_contact_gets_bootstrap_and_manager_roles(
    db, login_client, monkeypatch
):
    _email_contact(db, _area(db), "New.Contact@Example.test")

    payload = _login(login_client, monkeypatch, "new.contact@example.test")

    assert set(payload["user"]["roles"]) == {"staff_viewer", "business_area_manager"}
    user = db.query(User).filter(User.email == "new.contact@example.test").one()
    assert _manager_membership(db, user).assigned_by_id is None


def test_sync_is_idempotent_and_never_touches_other_roles(db, user_factory):
    seed_default_roles(db)
    user = user_factory(email="idempotent@example.test")
    _grant(db, user, "admin")
    _linked_contact(db, _area(db), user)

    sync_business_area_manager_role(db, user.id)
    sync_business_area_manager_role(db, user.id)
    db.flush()

    memberships = db.query(UserRole).filter(UserRole.user_id == user.id).all()
    names = sorted(m.role.name for m in memberships if m.deleted_at is None)
    assert names == ["admin", "business_area_manager"]
    assert len(memberships) == 2


@pytest.mark.asyncio
async def test_scope_lookup_is_skipped_without_business_area_permissions(
    db, user_factory, monkeypatch
):
    seed_default_roles(db)
    user = user_factory(email="admin.skip@example.test")
    _grant(db, user, "admin")
    _linked_contact(db, _area(db), user)

    def _fail(*_args, **_kwargs):
        raise AssertionError("contact scope lookup should not run")

    monkeypatch.setattr(form_authorization, "qualifying_contact_area_ids", _fail)
    context = await FormAuthorizationContext.load(str(user.id), db)

    assert context.active_business_area_ids == frozenset()
    assert "form:edit:any" in context.permissions


def test_email_contact_lookup_uses_normalized_email_index(db, user_factory):
    user = user_factory(email="index.check@example.test")
    _email_contact(db, _area(db), "Index.Check@example.test")
    query = (
        db.query(BusinessAreaContact.business_area_id)
        .filter(
            BusinessAreaContact.email.isnot(None),
            normalized_email_expression(BusinessAreaContact.email)
            == normalized_email_expression(literal(user.email)),
        )
        .statement.compile(db.get_bind(), compile_kwargs={"literal_binds": True})
    )

    db.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(row[0] for row in db.execute(text(f"EXPLAIN {query}")))

    assert "ix_business_area_contacts_email_normalized" in plan


def test_email_contact_scope_reaches_form_endpoints(
    db, login_client, monkeypatch, user_factory
):
    user = user_factory(email="scoped.editor@example.test")
    owner = user_factory(email="owner.us003@example.test")
    area, other_area = _area(db), _area(db)
    _email_contact(db, area, " Scoped.Editor@example.test")
    in_scope = Form(
        id=uuid.uuid4(),
        title="US-003 in scope",
        status="draft",
        created_by_id=owner.id,
        business_area_id=area.id,
        keywords=[],
        collects_personal_info="No",
    )
    out_of_scope = Form(
        id=uuid.uuid4(),
        title="US-003 out of scope",
        status="draft",
        created_by_id=owner.id,
        business_area_id=other_area.id,
        keywords=[],
        collects_personal_info="No",
    )
    db.add_all([in_scope, out_of_scope])
    db.flush()

    token = _login(login_client, monkeypatch, user.email)["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    allowed = login_client.get(f"/api/v1/forms/{in_scope.id}", headers=headers)
    denied = login_client.get(f"/api/v1/forms/{out_of_scope.id}", headers=headers)

    assert allowed.status_code == 200
    assert {"edit", "submit_for_review"} <= set(allowed.json()["available_actions"])
    assert denied.status_code in {403, 404}
