"""FEAT-0032 US-005: admin Business Area Manager assignment with contact areas."""

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.auth.business_area_scope import sync_business_area_manager_role
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import (
    AuditLog,
    BusinessArea,
    BusinessAreaContact,
    Role,
    User,
    UserRole,
)
from backend.seeds.default_roles import seed_default_roles


def _user(db, email):
    user = User(
        id=uuid.uuid4(),
        email=email,
        first_name="Test",
        last_name="User",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _role(db, name):
    return db.query(Role).filter(Role.name == name).one()


def _grant(db, user, role_name):
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=_role(db, role_name).id))
    db.flush()


def _area(db, *, deleted=False):
    area = BusinessArea(
        id=uuid.uuid4(),
        name=f"US-005 {uuid.uuid4().hex}",
        deleted_at=datetime(2026, 1, 1) if deleted else None,
    )
    db.add(area)
    db.flush()
    return area


def _client(db, actor, roles):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        sub=str(actor.id),
        email=actor.email,
        name="Actor",
        roles=roles,
        token_type="access",
    )
    return TestClient(app)


def _active_role_names(db, user):
    db.expire_all()
    return {
        ur.role.name
        for ur in db.query(UserRole).filter(UserRole.user_id == user.id).all()
        if ur.deleted_at is None
    }


def _contacts(db, user, area=None):
    query = db.query(BusinessAreaContact).filter(
        BusinessAreaContact.contact_user_id == user.id
    )
    if area is not None:
        query = query.filter(BusinessAreaContact.business_area_id == area.id)
    return query.all()


def _role_audits(db, user):
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_id == str(user.id),
            AuditLog.action != "permission_check",
        )
        .all()
    )


def _put_roles(client, user, role_names, db, area_ids=None):
    body = {"role_ids": [str(_role(db, name).id) for name in role_names]}
    if area_ids is not None:
        body["business_area_ids"] = [str(area_id) for area_id in area_ids]
    return client.put(f"/api/v1/admin/users/{user.id}/roles", json=body)


@pytest.fixture()
def ctx(db):
    seed_default_roles(db)
    admin = _user(db, f"admin-{uuid.uuid4().hex}@example.test")
    _grant(db, admin, "admin")
    target = _user(db, f"target-{uuid.uuid4().hex}@example.test")
    _grant(db, target, "staff_viewer")
    yield {
        "admin": admin,
        "target": target,
        "client": _client(db, admin, ["admin"]),
        "area_a": _area(db),
        "area_b": _area(db),
        "deleted_area": _area(db, deleted=True),
    }
    app.dependency_overrides.clear()


# ── Positive path ─────────────────────────────────────────────────────────────


def test_tc_005_2_assigns_role_and_adds_contacts_in_each_selected_area(db, ctx):
    target, a, b = ctx["target"], ctx["area_a"], ctx["area_b"]

    response = _put_roles(
        ctx["client"],
        target,
        ["staff_viewer", "business_area_manager"],
        db,
        [a.id, b.id],
    )

    assert response.status_code == 200
    body = response.json()
    assert {r["name"] for r in body["roles"]} == {
        "staff_viewer",
        "business_area_manager",
    }
    assert {area["id"] for area in body["contact_business_areas"]} == {
        str(a.id),
        str(b.id),
    }
    assert {c.business_area_id for c in _contacts(db, target)} == {a.id, b.id}
    assert all(c.name is None and c.email is None for c in _contacts(db, target))


def test_tc_005_3_existing_linked_or_email_contact_is_not_duplicated(db, ctx):
    target, a, b = ctx["target"], ctx["area_a"], ctx["area_b"]
    db.add(
        BusinessAreaContact(
            id=uuid.uuid4(), business_area_id=a.id, contact_user_id=target.id
        )
    )
    db.add(
        BusinessAreaContact(
            id=uuid.uuid4(),
            business_area_id=b.id,
            name="Target",
            email=f"  {target.email.upper()} ",
        )
    )
    db.flush()

    response = _put_roles(
        ctx["client"],
        target,
        ["staff_viewer", "business_area_manager"],
        db,
        [a.id, b.id],
    )

    assert response.status_code == 200
    assert len(_contacts(db, target, a)) == 1
    assert _contacts(db, target, b) == []
    assert (
        db.query(BusinessAreaContact)
        .filter(BusinessAreaContact.business_area_id == b.id)
        .count()
        == 1
    )
    assert {area["id"] for area in response.json()["contact_business_areas"]} == {
        str(a.id),
        str(b.id),
    }
    new_values = _role_audits(db, target)[-1].new_values
    assert new_values["added_contact_business_area_ids"] == []


def test_resaving_the_same_assignment_is_idempotent(db, ctx):
    target, a = ctx["target"], ctx["area_a"]
    roles = ["staff_viewer", "business_area_manager"]

    assert _put_roles(ctx["client"], target, roles, db, [a.id]).status_code == 200
    assert _put_roles(ctx["client"], target, roles, db, [a.id]).status_code == 200

    assert len(_contacts(db, target, a)) == 1


def test_user_detail_lists_only_active_contact_areas(db, ctx):
    target, a, deleted = ctx["target"], ctx["area_a"], ctx["deleted_area"]
    for area in (a, deleted):
        db.add(
            BusinessAreaContact(
                id=uuid.uuid4(), business_area_id=area.id, contact_user_id=target.id
            )
        )
    db.flush()

    response = ctx["client"].get(f"/api/v1/admin/users/{target.id}")

    assert response.status_code == 200
    assert response.json()["contact_business_areas"] == [
        {"id": str(a.id), "name": a.name}
    ]


# ── Negative path ─────────────────────────────────────────────────────────────


def test_tc_005_4_removing_role_keeps_contacts_and_next_login_regrants(db, ctx):
    target, a = ctx["target"], ctx["area_a"]
    _put_roles(
        ctx["client"], target, ["staff_viewer", "business_area_manager"], db, [a.id]
    )

    response = _put_roles(ctx["client"], target, ["staff_viewer"], db)

    assert response.status_code == 200
    assert _active_role_names(db, target) == {"staff_viewer"}
    assert len(_contacts(db, target, a)) == 1
    assert response.json()["contact_business_areas"] == [
        {"id": str(a.id), "name": a.name}
    ]

    sync_business_area_manager_role(db, target.id)
    db.flush()
    assert _active_role_names(db, target) == {"staff_viewer", "business_area_manager"}


def test_tc_005_5_removing_final_contact_revokes_admin_assigned_role_at_login(db, ctx):
    target, a = ctx["target"], ctx["area_a"]
    _put_roles(
        ctx["client"], target, ["staff_viewer", "business_area_manager"], db, [a.id]
    )
    for contact in _contacts(db, target):
        db.delete(contact)
    db.flush()

    sync_business_area_manager_role(db, target.id)
    db.flush()

    assert _active_role_names(db, target) == {"staff_viewer"}


@pytest.mark.parametrize(
    "selection",
    ["none", "empty", "deleted_only", "active_and_deleted", "unknown", "malformed"],
)
def test_tc_005_6_invalid_area_selection_is_rejected_without_changes(
    db, ctx, selection
):
    target, a, deleted = ctx["target"], ctx["area_a"], ctx["deleted_area"]
    area_ids = {
        "none": None,
        "empty": [],
        "deleted_only": [deleted.id],
        "active_and_deleted": [a.id, deleted.id],
        "unknown": [uuid.uuid4()],
        "malformed": ["not-a-uuid"],
    }[selection]

    response = _put_roles(
        ctx["client"], target, ["staff_viewer", "business_area_manager"], db, area_ids
    )

    assert response.status_code == 400
    assert _active_role_names(db, target) == {"staff_viewer"}
    assert _contacts(db, target) == []
    assert _role_audits(db, target) == []


def test_areas_without_business_area_manager_role_are_rejected(db, ctx):
    target, a = ctx["target"], ctx["area_a"]

    response = _put_roles(ctx["client"], target, ["staff_viewer"], db, [a.id])

    assert response.status_code == 400
    assert _contacts(db, target) == []
    assert _role_audits(db, target) == []


def test_soft_deleted_area_is_not_offered_for_selection(db, ctx):
    response = ctx["client"].get("/api/v1/business-areas")

    ids = {area["id"] for area in response.json()}
    assert str(ctx["area_a"].id) in ids
    assert str(ctx["deleted_area"].id) not in ids


# ── RBAC ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("actor_role", ["staff_viewer", "business_area_manager"])
def test_tc_005_7_non_admin_cannot_assign_role_or_areas(db, ctx, actor_role):
    target, a = ctx["target"], ctx["area_a"]
    actor = _user(db, f"actor-{uuid.uuid4().hex}@example.test")
    _grant(db, actor, actor_role)
    client = _client(db, actor, [actor_role])

    response = _put_roles(
        client, target, ["staff_viewer", "business_area_manager"], db, [a.id]
    )

    assert response.status_code == 403
    assert _active_role_names(db, target) == {"staff_viewer"}
    assert _contacts(db, target) == []
    assert _role_audits(db, target) == []


# ── Regression ────────────────────────────────────────────────────────────────


def test_tc_005_8_existing_roles_are_retained(db, ctx):
    target, a = ctx["target"], ctx["area_a"]
    _grant(db, target, "admin")

    response = _put_roles(
        ctx["client"],
        target,
        ["staff_viewer", "admin", "business_area_manager"],
        db,
        [a.id],
    )

    assert response.status_code == 200
    assert _active_role_names(db, target) == {
        "staff_viewer",
        "admin",
        "business_area_manager",
    }


def test_tc_005_9_single_update_roles_audit_and_no_contact_audit(db, ctx):
    target, a, b = ctx["target"], ctx["area_a"], ctx["area_b"]
    before = db.query(AuditLog).filter(AuditLog.action != "permission_check").count()

    response = _put_roles(
        ctx["client"],
        target,
        ["staff_viewer", "business_area_manager"],
        db,
        [a.id, b.id],
    )

    assert response.status_code == 200
    audits = _role_audits(db, target)
    assert [row.action for row in audits] == ["UPDATE_ROLES"]
    assert (
        db.query(AuditLog).filter(AuditLog.action != "permission_check").count()
        == before + 1
    )
    assert sorted(audits[0].new_values["business_area_ids"]) == sorted(
        [str(a.id), str(b.id)]
    )
    assert sorted(audits[0].new_values["added_contact_business_area_ids"]) == sorted(
        [str(a.id), str(b.id)]
    )
    assert audits[0].user_id == ctx["admin"].id


def test_unrelated_role_change_keeps_existing_payload_shape(db, ctx):
    target = ctx["target"]

    response = _put_roles(ctx["client"], target, ["staff_viewer", "admin"], db)

    assert response.status_code == 200
    assert set(_role_audits(db, target)[-1].new_values) == {"role_ids"}
