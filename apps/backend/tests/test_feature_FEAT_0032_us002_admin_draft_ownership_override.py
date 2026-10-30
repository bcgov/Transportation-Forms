import uuid

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import (
    AuditLog,
    BusinessArea,
    Form,
    FormActivityEvent,
    FormWorkflow,
    Role,
    UserRole,
)
from backend.seeds.default_roles import seed_default_roles


def _client_for_role(db, user, role):
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()

    def _current_user(_request: Request) -> TokenData:
        return TokenData(
            sub=str(user.id),
            email=user.email,
            name=f"{user.first_name} {user.last_name}",
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
        name=f"us002_{uuid.uuid4().hex}",
        permissions=permissions,
        is_system=False,
        is_active=True,
    )
    db.add(role)
    db.flush()
    return role


def _new_form(
    db,
    owner,
    *,
    status="draft",
    reservation_id=None,
):
    area = BusinessArea(id=uuid.uuid4(), name=f"US-002 {uuid.uuid4().hex}")
    db.add(area)
    db.flush()
    form = Form(
        id=uuid.uuid4(),
        title=f"US-002 {status}",
        description="Admin Draft ownership override test",
        status=status,
        is_public=False,
        current_version=1,
        keywords=[],
        created_by_id=owner.id,
        business_area_id=area.id,
        form_number_reservation_id=reservation_id,
        collects_personal_info="No",
        form_source="URL",
        form_source_url="https://example.com/form",
    )
    db.add(form)
    db.flush()
    return form


def _admin_client(db, admin_user):
    seed_default_roles(db)
    admin = db.query(Role).filter(Role.name == "admin").one()
    return _client_for_role(db, admin_user, admin)


def test_admin_can_edit_non_owned_draft_and_audit_as_actor(db, user_factory):
    admin_user = user_factory(first_name="Admin", last_name="Actor")
    owner = user_factory()
    form = _new_form(db, owner)
    client = _admin_client(db, admin_user)
    try:
        response = client.put(
            f"/api/v1/forms/{form.id}",
            json={"title": "Admin updated Draft"},
        )

        assert response.status_code == 200
        assert response.json()["title"] == "Admin updated Draft"
        db.refresh(form)
        assert form.status == "draft"
        assert form.created_by_id == owner.id

        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "forms",
                AuditLog.entity_id == str(form.id),
                AuditLog.action == "UPDATE",
            )
            .one()
        )
        assert audit.user_id == admin_user.id
        activity = (
            db.query(FormActivityEvent)
            .filter(
                FormActivityEvent.form_id == form.id,
                FormActivityEvent.event_name == "Form saved",
            )
            .one()
        )
        assert activity.actor_label == "Admin Actor"
    finally:
        _cleanup_client()


def test_admin_is_offered_edit_and_submit_on_another_admins_draft(db, user_factory):
    owner_admin = user_factory(first_name="Owner", last_name="Admin")
    other_admin = user_factory(first_name="Other", last_name="Admin")
    form = _new_form(db, owner_admin)
    seed_default_roles(db)
    admin = db.query(Role).filter(Role.name == "admin").one()
    db.add(UserRole(id=uuid.uuid4(), user_id=owner_admin.id, role_id=admin.id))
    client = _client_for_role(db, other_admin, admin)
    try:
        listed = client.get("/api/v1/forms", params={"limit": 100})
        detail = client.get(f"/api/v1/forms/{form.id}")

        assert listed.status_code == 200
        items = {item["id"]: item for item in listed.json()["items"]}
        expected = {"edit", "submit_for_review", "delete"}
        assert expected <= set(items[str(form.id)]["available_actions"])
        assert detail.status_code == 200
        assert expected <= set(detail.json()["available_actions"])
    finally:
        _cleanup_client()


def test_admin_can_submit_non_owned_draft_with_approved_reservation(
    db, user_factory, prefix_factory, reservation_factory
):
    admin_user = user_factory()
    owner = user_factory()
    prefix = prefix_factory(prefix="US2", created_by=owner)
    reservation = reservation_factory(
        prefix=prefix,
        status="approved",
        reserved_by=owner,
    )
    form = _new_form(db, owner, reservation_id=reservation.id)
    client = _admin_client(db, admin_user)
    try:
        response = client.post(
            f"/api/v1/staff/forms/{form.id}/submit",
            json={"expected_version": form.current_version},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "pending_review"
        db.refresh(form)
        assert form.status == "pending_review"
        workflow = (
            db.query(FormWorkflow)
            .filter(
                FormWorkflow.form_id == form.id,
                FormWorkflow.action == "submit",
            )
            .one()
        )
        assert workflow.triggered_by_id == admin_user.id
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "forms",
                AuditLog.entity_id == str(form.id),
                AuditLog.action == "WORKFLOW_TRANSITION",
            )
            .one()
        )
        assert audit.user_id == admin_user.id
    finally:
        _cleanup_client()


def test_admin_submission_still_requires_approved_reservation(
    db, user_factory, prefix_factory, reservation_factory
):
    admin_user = user_factory()
    owner = user_factory()
    prefix = prefix_factory(prefix="US2", created_by=owner)
    reservation = reservation_factory(
        prefix=prefix,
        status="reserved",
        reserved_by=owner,
    )
    form = _new_form(db, owner, reservation_id=reservation.id)
    client = _admin_client(db, admin_user)
    try:
        response = client.post(
            f"/api/v1/staff/forms/{form.id}/submit",
            json={"expected_version": form.current_version},
        )

        assert response.status_code == 409
        db.refresh(form)
        assert form.status == "draft"
        assert (
            db.query(FormWorkflow)
            .filter(
                FormWorkflow.form_id == form.id,
                FormWorkflow.action == "submit",
            )
            .count()
            == 0
        )
    finally:
        _cleanup_client()


def test_admin_invalid_update_payload_keeps_draft_unchanged(db, user_factory):
    admin_user = user_factory()
    owner = user_factory()
    form = _new_form(db, owner)
    client = _admin_client(db, admin_user)
    try:
        response = client.put(
            f"/api/v1/forms/{form.id}",
            json={"title": ""},
        )

        assert response.status_code == 422
        db.refresh(form)
        assert form.status == "draft"
        assert form.title == "US-002 draft"
    finally:
        _cleanup_client()


@pytest.mark.parametrize("form_status", ["pending_review", "archived"])
def test_admin_cannot_edit_or_submit_non_draft_forms(db, user_factory, form_status):
    admin_user = user_factory()
    owner = user_factory()
    form = _new_form(db, owner, status=form_status)
    original_title = form.title
    client = _admin_client(db, admin_user)
    try:
        update_response = client.put(
            f"/api/v1/forms/{form.id}",
            json={"title": "Must remain unchanged"},
        )
        submit_response = client.post(
            f"/api/v1/staff/forms/{form.id}/submit",
            json={"expected_version": form.current_version},
        )

        assert update_response.status_code == 403
        assert submit_response.status_code == 403
        db.refresh(form)
        assert form.status == form_status
        assert form.title == original_title
    finally:
        _cleanup_client()


def test_creator_or_latest_submitter_cannot_approve_without_exception(db, user_factory):
    approver = user_factory()
    other_owner = user_factory()
    created_by_approver = _new_form(db, approver, status="pending_review")
    submitted_by_approver = _new_form(db, other_owner, status="pending_review")
    approver_role = _new_role(db, ["form:approve", "form:review"])
    db.add(
        FormWorkflow(
            id=uuid.uuid4(),
            form_id=submitted_by_approver.id,
            action="submit",
            from_status="draft",
            to_status="pending_review",
            triggered_by_id=approver.id,
        )
    )
    db.flush()
    client = _client_for_role(db, approver, approver_role)
    try:
        creator_response = client.post(
            f"/api/v1/staff/forms/{created_by_approver.id}/approve"
        )
        submitter_response = client.post(
            f"/api/v1/staff/forms/{submitted_by_approver.id}/approve"
        )

        assert creator_response.status_code == 400
        assert submitter_response.status_code == 400
        db.refresh(created_by_approver)
        db.refresh(submitted_by_approver)
        assert created_by_approver.status == "pending_review"
        assert submitted_by_approver.status == "pending_review"
    finally:
        _cleanup_client()


def test_approve_self_permission_allows_creator_and_latest_submitter(db, user_factory):
    approver = user_factory()
    other_owner = user_factory()
    created_by_approver = _new_form(db, approver, status="pending_review")
    submitted_by_approver = _new_form(db, other_owner, status="pending_review")
    db.add(
        FormWorkflow(
            id=uuid.uuid4(),
            form_id=submitted_by_approver.id,
            action="submit",
            from_status="draft",
            to_status="pending_review",
            triggered_by_id=approver.id,
        )
    )
    role = _new_role(
        db,
        ["form:approve", "form:review", "form:approve-self"],
    )
    db.flush()
    client = _client_for_role(db, approver, role)
    try:
        creator_response = client.post(
            f"/api/v1/staff/forms/{created_by_approver.id}/approve"
        )
        submitter_response = client.post(
            f"/api/v1/staff/forms/{submitted_by_approver.id}/approve"
        )

        assert creator_response.status_code == 200
        assert submitter_response.status_code == 200
        db.refresh(created_by_approver)
        db.refresh(submitted_by_approver)
        assert created_by_approver.status == "published"
        assert submitted_by_approver.status == "published"
    finally:
        _cleanup_client()


def test_admin_published_actions_still_require_unpublish_before_edit(db, user_factory):
    admin_user = user_factory()
    owner = user_factory()
    form = _new_form(db, owner, status="published")
    client = _admin_client(db, admin_user)
    try:
        detail = client.get(f"/api/v1/forms/{form.id}")
        assert detail.status_code == 200
        actions = set(detail.json()["available_actions"])
        assert {"archive", "unpublish", "revert"} <= actions

        denied_update = client.put(
            f"/api/v1/forms/{form.id}",
            json={"title": "Direct Published edit"},
        )
        assert denied_update.status_code == 403
        db.refresh(form)
        assert form.status == "published"

        unpublished = client.post(f"/api/v1/staff/forms/{form.id}/unpublish")
        assert unpublished.status_code == 200
        assert unpublished.json()["status"] == "draft"

        updated = client.put(
            f"/api/v1/forms/{form.id}",
            json={"title": "Edited after unpublish"},
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Edited after unpublish"
    finally:
        _cleanup_client()


def test_admin_restores_archived_form_with_archive_permission(db, user_factory):
    admin_user = user_factory()
    owner = user_factory()
    form = _new_form(db, owner, status="archived")
    client = _admin_client(db, admin_user)
    try:
        response = client.post(f"/api/v1/staff/forms/{form.id}/restore")

        assert response.status_code == 200
        assert response.json()["status"] == "published"
        db.refresh(form)
        assert form.status == "published"
    finally:
        _cleanup_client()


def test_non_admin_cannot_edit_another_users_draft_with_legacy_permissions(
    db, user_factory
):
    actor = user_factory()
    owner = user_factory()
    form = _new_form(db, owner)
    role = _new_role(
        db,
        ["form:read", "form:edit", "form:submit_for_review"],
    )
    client = _client_for_role(db, actor, role)
    try:
        response = client.put(
            f"/api/v1/forms/{form.id}",
            json={"title": "Must be denied"},
        )
        submit_response = client.post(
            f"/api/v1/staff/forms/{form.id}/submit",
            json={"expected_version": form.current_version},
        )

        assert response.status_code == 403
        assert submit_response.status_code == 403
        db.refresh(form)
        assert form.title == "US-002 draft"
        assert form.created_by_id == owner.id
    finally:
        _cleanup_client()
