import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend.auth.authorization import get_user_permissions
from backend.auth.form_authorization import FormAuthorizationContext
from backend.auth.permissions import DEFAULT_ROLES, Permission
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import (
    BusinessArea,
    BusinessAreaContact,
    Form,
    FormWorkflow,
    Role,
    UserRole,
)
from backend.seeds.default_roles import seed_default_roles
from backend.services.forms import FormService, FormWorkflowValidationError


def _client_for_role(db, user, role):
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()

    def _current_user(_request: Request) -> TokenData:
        return TokenData(
            sub=str(user.id),
            email=user.email,
            name="Test User",
            roles=[role.name],
            token_type="access",
            permissions=role.permissions,
        )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


def _cleanup_client():
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def _new_role(db, permissions):
    role = Role(
        id=uuid.uuid4(),
        name=f"us001_{uuid.uuid4().hex}",
        permissions=permissions,
        is_system=False,
        is_active=True,
    )
    db.add(role)
    db.flush()
    return role


def _new_form(db, owner, *, status="draft", business_area=None):
    form = Form(
        id=uuid.uuid4(),
        title=f"US-001 {status}",
        description="Scoped authorization test form",
        status=status,
        is_public=False,
        current_version=1,
        keywords=[],
        created_by_id=owner.id,
        business_area_id=business_area.id if business_area else None,
        collects_personal_info="No",
        form_source="URL",
        form_source_url="https://example.com/form",
    )
    db.add(form)
    db.flush()
    return form


def test_seeded_business_area_manager_has_only_required_capabilities(db):
    seed_default_roles(db)
    role = db.query(Role).filter(Role.name == "business_area_manager").one()
    required = {
        *(
            permission.value
            for permission in DEFAULT_ROLES["staff_viewer"]["permissions"]
        ),
        Permission.FORM_READ_UNPUBLISHED_BUSINESS_AREA.value,
        Permission.FORM_EDIT_BUSINESS_AREA.value,
        Permission.FORM_SUBMIT_FOR_REVIEW_BUSINESS_AREA.value,
        Permission.FORM_VIEW_WORKFLOW_STATE.value,
    }

    assert role.is_system is True
    assert role.is_active is True
    assert set(role.permissions) == required
    assert not {
        "form:create",
        "form:delete",
        "form:archive",
        "form:approve",
        "form:publish",
        "form:audit",
        "form:stats",
        "form:edit",
        "form:submit_for_review",
        "user:manage_roles",
        "role:create",
    } & set(role.permissions)


def test_business_area_manager_seed_repairs_permissions_without_duplicates(
    db,
):
    seed_default_roles(db)
    role = db.query(Role).filter(Role.name == "business_area_manager").one()
    role.permissions = ["form:read", "form:create", "form:approve"]
    role.is_active = False
    db.flush()

    result = seed_default_roles(db)

    assert result["updated"] == 1
    assert role.is_active is True
    assert (
        db.query(Role)
        .filter(
            Role.name == "business_area_manager",
            Role.deleted_at.is_(None),
        )
        .count()
        == 1
    )
    expected_permissions = DEFAULT_ROLES["business_area_manager"]["permissions"]
    assert set(role.permissions) == {
        permission.value for permission in expected_permissions
    }


@pytest.mark.asyncio
async def test_legacy_permissions_keep_owner_access_and_admin_draft_override(
    db, user_factory
):
    owner_scoped_user = user_factory()
    legacy_role = _new_role(
        db,
        ["form:read", "form:edit", "form:submit_for_review"],
    )
    db.add(
        UserRole(
            id=uuid.uuid4(),
            user_id=owner_scoped_user.id,
            role_id=legacy_role.id,
        )
    )
    seed_default_roles(db)
    admin = db.query(Role).filter(Role.name == "admin").one()
    admin_user = user_factory()
    db.add(UserRole(id=uuid.uuid4(), user_id=admin_user.id, role_id=admin.id))
    db.flush()

    legacy_permissions = await get_user_permissions(str(owner_scoped_user.id), db)
    admin_permissions = await get_user_permissions(str(admin_user.id), db)

    assert "form:edit:own" in legacy_permissions
    assert "form:submit_for_review:own" in legacy_permissions
    assert "form:read_unpublished:any" in legacy_permissions
    assert "form:edit:any" in admin_permissions
    assert "form:submit_for_review:any" in admin_permissions


@pytest.mark.parametrize(
    ("permissions", "owner", "area_id", "state", "can_edit", "can_submit"),
    [
        (
            {"form:edit:own", "form:submit_for_review:own"},
            True,
            None,
            "draft",
            True,
            True,
        ),
        (
            {"form:edit:own", "form:submit_for_review:own"},
            False,
            None,
            "draft",
            False,
            False,
        ),
        (
            {
                "form:edit:business_area",
                "form:submit_for_review:business_area",
            },
            False,
            "active",
            "draft",
            True,
            True,
        ),
        (
            {
                "form:edit:business_area",
                "form:submit_for_review:business_area",
            },
            False,
            "other",
            "draft",
            False,
            False,
        ),
        (
            {"form:edit:any", "form:submit_for_review:any"},
            False,
            None,
            "draft",
            True,
            True,
        ),
        (
            {"form:edit:any", "form:submit_for_review:any"},
            False,
            None,
            "pending_review",
            False,
            False,
        ),
    ],
)
def test_scoped_actions_require_matching_scope_and_draft_state(
    permissions,
    owner,
    area_id,
    state,
    can_edit,
    can_submit,
):
    user_id = uuid.uuid4()
    active_area_id = uuid.uuid4()
    form = SimpleNamespace(
        created_by_id=user_id if owner else uuid.uuid4(),
        business_area_id=(
            active_area_id
            if area_id == "active"
            else uuid.uuid4() if area_id == "other" else None
        ),
        status=state,
    )
    context = FormAuthorizationContext(
        user_id=user_id,
        permissions=frozenset(permissions),
        active_business_area_ids=frozenset({active_area_id}),
        role_names=frozenset(),
    )

    assert context.can_edit(form) is can_edit
    assert context.can_submit(form) is can_submit


def test_workflow_state_visibility_does_not_grant_mutation():
    context = FormAuthorizationContext(
        user_id=uuid.uuid4(),
        permissions=frozenset({"form:view_workflow_state"}),
        active_business_area_ids=frozenset(),
        role_names=frozenset(),
    )
    draft = SimpleNamespace(
        status="draft",
        created_by_id=uuid.uuid4(),
        business_area_id=None,
    )

    assert context.can_view_workflow_state() is True
    assert context.can_edit(draft) is False
    assert context.available_actions(draft) == []


def test_business_area_manager_list_detail_and_update_share_actions(db, user_factory):
    seed_default_roles(db)
    manager = user_factory()
    owner = user_factory()
    active_area = BusinessArea(id=uuid.uuid4(), name=f"Active {uuid.uuid4().hex}")
    other_area = BusinessArea(id=uuid.uuid4(), name=f"Other {uuid.uuid4().hex}")
    deleted_area = BusinessArea(
        id=uuid.uuid4(),
        name=f"Deleted {uuid.uuid4().hex}",
        deleted_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add_all([active_area, other_area, deleted_area])
    db.flush()
    db.add(
        BusinessAreaContact(
            id=uuid.uuid4(),
            business_area_id=active_area.id,
            contact_user_id=manager.id,
        )
    )
    db.add(
        BusinessAreaContact(
            id=uuid.uuid4(),
            business_area_id=deleted_area.id,
            contact_user_id=manager.id,
        )
    )
    in_scope_draft = _new_form(db, owner, business_area=active_area)
    out_of_scope_draft = _new_form(db, owner, business_area=other_area)
    deleted_area_draft = _new_form(db, owner, business_area=deleted_area)
    published = _new_form(db, owner, status="published", business_area=other_area)
    archived = _new_form(db, owner, status="archived", business_area=active_area)
    role = db.query(Role).filter(Role.name == "business_area_manager").one()
    client = _client_for_role(db, manager, role)
    try:
        response = client.get("/api/v1/forms")
        assert response.status_code == 200
        items = {item["id"]: item for item in response.json()["items"]}
        assert set(items) == {
            str(in_scope_draft.id),
            str(published.id),
        }
        actions = items[str(in_scope_draft.id)]["available_actions"]
        assert actions == ["edit", "submit_for_review"]

        detail = client.get(f"/api/v1/forms/{in_scope_draft.id}")
        assert detail.status_code == 200
        assert detail.json()["available_actions"] == actions

        denied_detail = client.get(f"/api/v1/forms/{out_of_scope_draft.id}")
        assert denied_detail.status_code == 403
        denied_update = client.put(
            f"/api/v1/forms/{out_of_scope_draft.id}",
            json={"title": "Out-of-scope edit"},
        )
        assert denied_update.status_code == 403
        deleted_area_detail = client.get(f"/api/v1/forms/{deleted_area_draft.id}")
        assert deleted_area_detail.status_code == 403
        archived_detail = client.get(f"/api/v1/forms/{archived.id}")
        assert archived_detail.status_code == 404

        area_change = client.put(
            f"/api/v1/forms/{in_scope_draft.id}",
            json={"business_area_id": str(other_area.id)},
        )
        assert area_change.status_code == 403
        db.refresh(in_scope_draft)
        assert in_scope_draft.business_area_id == active_area.id

        updated = client.put(
            f"/api/v1/forms/{in_scope_draft.id}",
            json={"title": "Updated by scoped manager"},
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Updated by scoped manager"
        assert updated.json()["available_actions"] == actions
    finally:
        _cleanup_client()


def test_admin_can_edit_and_submit_another_users_draft(db, user_factory):
    seed_default_roles(db)
    admin_user = user_factory()
    owner = user_factory()
    area = BusinessArea(id=uuid.uuid4(), name=f"Area {uuid.uuid4().hex}")
    db.add(area)
    db.flush()
    form = _new_form(db, owner, business_area=area)
    admin = db.query(Role).filter(Role.name == "admin").one()
    client = _client_for_role(db, admin_user, admin)
    try:
        updated = client.put(
            f"/api/v1/forms/{form.id}",
            json={"title": "Admin updated draft"},
        )
        assert updated.status_code == 200
        assert "edit" in updated.json()["available_actions"]

        submitted = client.post(
            f"/api/v1/staff/forms/{form.id}/submit",
            json={"expected_version": updated.json()["current_version"]},
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "pending_review"
        db.refresh(form)
        assert form.status == "pending_review"
    finally:
        _cleanup_client()


@pytest.mark.parametrize("form_status", ["published", "archived"])
def test_update_api_rejects_published_and_archived_forms(db, user_factory, form_status):
    seed_default_roles(db)
    actor = user_factory()
    owner = user_factory()
    form = _new_form(db, owner, status=form_status)
    admin = db.query(Role).filter(Role.name == "admin").one()
    client = _client_for_role(db, actor, admin)
    try:
        response = client.put(
            f"/api/v1/forms/{form.id}",
            json={"title": "Must remain unchanged"},
        )
        assert response.status_code == 403
        db.refresh(form)
        assert form.status == form_status
        assert form.title == f"US-001 {form_status}"
    finally:
        _cleanup_client()


def test_staff_restore_requires_archive_not_approve(db, user_factory):
    owner = user_factory()
    actor = user_factory()
    form = _new_form(db, owner, status="archived")
    unarchive_form = _new_form(db, owner, status="archived")
    approve_role = _new_role(db, ["form:approve", "form:review"])
    approve_client = _client_for_role(db, actor, approve_role)
    try:
        denied = approve_client.post(f"/api/v1/staff/forms/{form.id}/restore")
        assert denied.status_code == 403
        denied_unarchive = approve_client.post(
            f"/api/v1/forms/{unarchive_form.id}/unarchive"
        )
        assert denied_unarchive.status_code == 403
        db.refresh(form)
        assert form.status == "archived"
        db.refresh(unarchive_form)
        assert unarchive_form.status == "archived"
    finally:
        _cleanup_client()

    archive_actor = user_factory()
    archive_role = _new_role(db, ["form:archive"])
    archive_client = _client_for_role(db, archive_actor, archive_role)
    try:
        restored = archive_client.post(f"/api/v1/staff/forms/{form.id}/restore")
        assert restored.status_code == 200
        assert restored.json()["status"] == "published"
        restored_unarchive = archive_client.post(
            f"/api/v1/forms/{unarchive_form.id}/unarchive"
        )
        assert restored_unarchive.status_code == 200
        assert restored_unarchive.json()["status"] == "published"
    finally:
        _cleanup_client()


def test_latest_submitter_cannot_approve_without_explicit_self_permission(
    db, user_factory
):
    creator = user_factory()
    submitter = user_factory()
    form = _new_form(db, creator, status="pending_review")
    db.add(
        FormWorkflow(
            id=uuid.uuid4(),
            form_id=form.id,
            action="submit",
            from_status="draft",
            to_status="pending_review",
            triggered_by_id=submitter.id,
        )
    )
    db.flush()

    with pytest.raises(
        FormWorkflowValidationError,
        match="most recently submitted",
    ):
        FormService.approve_form(db, form.id, submitter.id)
