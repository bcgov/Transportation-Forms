import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import update as sa_update

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import (
    AuditLog,
    BusinessArea,
    BusinessAreaContact,
    Form,
    FormActivityEvent,
    FormNumberPrefix,
    FormNumberReservation,
    FormWorkflow,
    Role,
    UserRole,
)
from backend.seeds.default_roles import seed_default_roles
from backend.services import s3_service
from backend.services.forms import FormService


@pytest.fixture
def manager_context(db, user_factory):
    seed_default_roles(db)
    manager = user_factory(first_name="Manager", last_name="Scoped")
    owner = user_factory(first_name="Owner", last_name="Distinct")
    active_area = BusinessArea(id=uuid.uuid4(), name=f"Active {uuid.uuid4().hex}")
    other_area = BusinessArea(id=uuid.uuid4(), name=f"Other {uuid.uuid4().hex}")
    deleted_area = BusinessArea(
        id=uuid.uuid4(),
        name=f"Deleted {uuid.uuid4().hex}",
        deleted_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add_all([active_area, other_area, deleted_area])
    db.flush()
    db.add_all(
        [
            BusinessAreaContact(
                id=uuid.uuid4(), business_area_id=area.id, contact_user_id=manager.id
            )
            for area in (active_area, deleted_area)
        ]
    )
    role = db.query(Role).filter(Role.name == "business_area_manager").one()
    db.add(UserRole(id=uuid.uuid4(), user_id=manager.id, role_id=role.id))
    db.flush()

    def _current_user(_request: Request) -> TokenData:
        return TokenData(
            sub=str(manager.id),
            email=manager.email,
            name="Test Manager",
            roles=[role.name],
            token_type="access",
            permissions=role.permissions,
        )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    try:
        yield TestClient(app), manager, owner, active_area, other_area, deleted_area
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def _form(db, owner, area, *, status="draft", title="Scoped form"):
    form = Form(
        id=uuid.uuid4(),
        title=title,
        description="Valid description",
        status=status,
        is_public=False,
        current_version=1,
        keywords=[],
        created_by_id=owner.id,
        business_area_id=area.id if area else None,
        collects_personal_info="No",
        form_source="Download",
        form_attachment_url="uploads/us004.pdf",
        form_attachment_filename="us004.pdf",
        file_type="pdf",
    )
    db.add(form)
    db.flush()
    return form


def test_manager_list_and_details_follow_status_and_area_scope(manager_context, db):
    client, _, owner, active_area, other_area, deleted_area = manager_context
    scoped_draft = _form(db, owner, active_area)
    scoped_pending = _form(db, owner, active_area, status="pending_review")
    published_other = _form(db, owner, other_area, status="published")
    published_no_area = _form(db, owner, None, status="published")
    excluded = [
        _form(db, owner, other_area),
        _form(db, owner, other_area, status="pending_review"),
        _form(db, owner, None),
        _form(db, owner, deleted_area),
        _form(db, owner, active_area, status="archived"),
    ]
    visible = {
        str(scoped_draft.id),
        str(scoped_pending.id),
        str(published_other.id),
        str(published_no_area.id),
    }

    listed = client.get("/api/v1/forms")
    assert listed.status_code == 200
    assert listed.json()["total"] == len(visible)
    items = {item["id"]: item for item in listed.json()["items"]}
    assert set(items) == visible
    assert items[str(scoped_draft.id)]["available_actions"] == [
        "edit",
        "submit_for_review",
    ]
    assert items[str(scoped_pending.id)]["available_actions"] == []
    assert items[str(published_other.id)]["available_actions"] == []

    for form_status, expected in (
        ("draft", {str(scoped_draft.id)}),
        ("pending_review", {str(scoped_pending.id)}),
        ("published", {str(published_other.id), str(published_no_area.id)}),
        ("archived", set()),
    ):
        response = client.get("/api/v1/forms", params={"status": form_status})
        assert response.status_code == 200
        assert {item["id"] for item in response.json()["items"]} == expected
        assert response.json()["total"] == len(expected)

    for form in (scoped_pending, published_other, published_no_area):
        response = client.get(f"/api/v1/forms/{form.id}")
        assert response.status_code == 200
        assert response.json()["available_actions"] == []
    for form in excluded:
        response = client.get(f"/api/v1/forms/{form.id}")
        assert response.status_code == (404 if form.status == "archived" else 403)
        assert str(form.id) not in response.text


def test_manager_scope_unions_active_areas_with_viewer_role(manager_context, db):
    client, manager, owner, active_area, other_area, _ = manager_context
    viewer_role = db.query(Role).filter(Role.name == "staff_viewer").one()
    db.add(UserRole(id=uuid.uuid4(), user_id=manager.id, role_id=viewer_role.id))
    db.add(
        BusinessAreaContact(
            id=uuid.uuid4(), business_area_id=other_area.id, contact_user_id=manager.id
        )
    )
    first = _form(db, owner, active_area)
    second = _form(db, owner, other_area, status="pending_review")
    db.flush()

    response = client.get("/api/v1/forms")

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["items"]} == {
        str(first.id),
        str(second.id),
    }
    assert client.get(f"/api/v1/forms/{second.id}").status_code == 200


def test_manager_without_active_contact_only_sees_published(manager_context, db):
    client, manager, owner, active_area, other_area, _ = manager_context
    draft = _form(db, owner, active_area, title="NoContact Draft")
    published = _form(
        db, owner, other_area, status="published", title="NoContact Published"
    )
    db.query(BusinessAreaContact).filter(
        BusinessAreaContact.contact_user_id == manager.id
    ).delete(synchronize_session=False)
    db.flush()

    listed = client.get("/api/v1/forms")
    suggested = client.get("/api/v1/forms/autocomplete", params={"q": "NoContact"})
    detail = client.get(f"/api/v1/forms/{draft.id}")
    updated = client.put(f"/api/v1/forms/{draft.id}", json={"title": "Denied"})

    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()["items"]} == {str(published.id)}
    assert suggested.status_code == 200
    assert suggested.json()["suggestions"] == ["NoContact Published"]
    assert detail.status_code == 403
    assert updated.status_code == 403


def test_unrelated_role_does_not_expand_viewer_autocomplete(
    manager_context, db, user_factory
):
    _, _, owner, active_area, _, _ = manager_context
    viewer = user_factory()
    viewer_role = db.query(Role).filter(Role.name == "staff_viewer").one()
    extra_role = Role(
        id=uuid.uuid4(),
        name=f"unrelated_{uuid.uuid4().hex}",
        permissions=["category:read"],
        is_active=True,
    )
    db.add(extra_role)
    db.add_all(
        [
            UserRole(id=uuid.uuid4(), user_id=viewer.id, role_id=role.id)
            for role in (viewer_role, extra_role)
        ]
    )
    _form(db, owner, active_area, status="draft", title="MixedRole Draft")
    _form(db, owner, active_area, status="published", title="MixedRole Published")
    db.flush()

    def _viewer(_request: Request) -> TokenData:
        return TokenData(
            sub=str(viewer.id),
            email=viewer.email,
            name="Viewer with unrelated role",
            roles=[viewer_role.name, extra_role.name],
            token_type="access",
            permissions=["form:read", "category:read"],
        )

    manager_override = app.dependency_overrides[get_current_user]
    app.dependency_overrides[get_current_user] = _viewer
    try:
        response = TestClient(app).get(
            "/api/v1/forms/autocomplete", params={"q": "MixedRole"}
        )
    finally:
        app.dependency_overrides[get_current_user] = manager_override

    assert response.status_code == 200
    assert response.json()["suggestions"] == ["MixedRole Published"]


def test_manager_edits_and_submits_another_users_draft_as_actor(manager_context, db):
    client, manager, owner, active_area, _, _ = manager_context
    form = _form(db, owner, active_area)
    detail = client.get(f"/api/v1/forms/{form.id}")
    assert detail.status_code == 200
    assert detail.json()["available_actions"] == ["edit", "submit_for_review"]

    updated = client.put(f"/api/v1/forms/{form.id}", json={"title": "Manager edit"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Manager edit"
    db.refresh(form)
    assert form.created_by_id == owner.id
    assert (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_id == str(form.id),
            AuditLog.action == "UPDATE",
            AuditLog.user_id == manager.id,
        )
        .count()
        == 1
    )
    assert (
        db.query(FormActivityEvent)
        .filter(
            FormActivityEvent.form_id == form.id,
            FormActivityEvent.event_name == "Form saved",
            FormActivityEvent.actor_label == "Manager Scoped",
        )
        .count()
        == 1
    )

    submitted = client.post(
        f"/api/v1/staff/forms/{form.id}/submit",
        json={"expected_version": updated.json()["current_version"]},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending_review"
    db.refresh(form)
    assert form.status == "pending_review"
    assert (
        db.query(FormWorkflow)
        .filter(
            FormWorkflow.form_id == form.id,
            FormWorkflow.action == "submit",
            FormWorkflow.triggered_by_id == manager.id,
        )
        .count()
        == 1
    )
    assert (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_id == str(form.id),
            AuditLog.action == "WORKFLOW_TRANSITION",
            AuditLog.user_id == manager.id,
        )
        .count()
        == 1
    )


def test_form_owner_and_admin_can_change_draft_business_area(
    manager_context, db, user_factory
):
    client, manager, owner, active_area, other_area, _ = manager_context
    owned_form = _form(db, manager, active_area)

    owner_update = client.put(
        f"/api/v1/forms/{owned_form.id}",
        json={"business_area_id": str(other_area.id)},
    )

    assert owner_update.status_code == 200
    db.refresh(owned_form)
    assert owned_form.business_area_id == other_area.id
    assert client.get(f"/api/v1/forms/{owned_form.id}").status_code == 403

    admin_user = user_factory()
    admin_role = db.query(Role).filter(Role.name == "admin").one()
    db.add(UserRole(id=uuid.uuid4(), user_id=admin_user.id, role_id=admin_role.id))
    admin_form = _form(db, owner, active_area)
    db.flush()

    def _admin_user(_request: Request) -> TokenData:
        return TokenData(
            sub=str(admin_user.id),
            email=admin_user.email,
            name="Test Admin",
            roles=[admin_role.name],
            token_type="access",
            permissions=admin_role.permissions,
        )

    manager_override = app.dependency_overrides[get_current_user]
    app.dependency_overrides[get_current_user] = _admin_user
    try:
        admin_update = TestClient(app).put(
            f"/api/v1/forms/{admin_form.id}",
            json={"business_area_id": str(other_area.id)},
        )
    finally:
        app.dependency_overrides[get_current_user] = manager_override

    assert admin_update.status_code == 200
    db.refresh(admin_form)
    assert admin_form.business_area_id == other_area.id


@pytest.mark.parametrize("description", ["", "   "])
def test_manager_cannot_save_blank_description(description, manager_context, db):
    client, _, owner, active_area, _, _ = manager_context
    form = _form(db, owner, active_area)

    response = client.put(f"/api/v1/forms/{form.id}", json={"description": description})

    assert response.status_code == 422
    db.refresh(form)
    assert form.description == "Valid description"
    assert (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == str(form.id), AuditLog.action == "UPDATE")
        .count()
        == 0
    )


def test_manager_cannot_submit_persisted_invalid_draft(manager_context, db):
    client, _, owner, active_area, _, _ = manager_context
    form = _form(db, owner, active_area)
    form.description = ""
    db.flush()

    response = client.post(
        f"/api/v1/staff/forms/{form.id}/submit",
        json={"expected_version": form.current_version},
    )

    assert response.status_code == 400
    db.refresh(form)
    assert form.status == "draft"
    assert db.query(FormWorkflow).filter(FormWorkflow.form_id == form.id).count() == 0


def test_manager_submission_requires_approved_reservation(
    manager_context, db, prefix_factory, reservation_factory
):
    client, _, owner, active_area, _, _ = manager_context
    prefix = prefix_factory(prefix=f"R{uuid.uuid4().hex[:4].upper()}", created_by=owner)
    reservation = reservation_factory(
        prefix=prefix, status="reserved", reserved_by=owner
    )
    form = _form(db, owner, active_area)
    form.form_number_reservation_id = reservation.id
    db.flush()

    response = client.post(
        f"/api/v1/staff/forms/{form.id}/submit",
        json={"expected_version": form.current_version},
    )

    assert response.status_code == 409
    db.refresh(form)
    assert form.status == "draft"
    assert db.query(FormWorkflow).filter(FormWorkflow.form_id == form.id).count() == 0


@pytest.mark.parametrize(
    ("form_status", "edit_detail", "submit_status", "submit_detail"),
    [
        (
            "pending_review",
            "Form cannot be edited while it is in Pending Review state",
            400,
            "Form is already in 'pending_review' state",
        ),
        (
            "published",
            "Published and Archived forms cannot be updated",
            400,
            "Invalid transition from 'published' to 'pending_review'",
        ),
        # Archived forms are unreadable for managers, so no state is revealed.
        (
            "archived",
            "Insufficient permissions for this action",
            403,
            "Insufficient permissions for this action",
        ),
    ],
)
def test_manager_cannot_edit_or_submit_non_draft(
    form_status, edit_detail, submit_status, submit_detail, manager_context, db
):
    client, _, owner, active_area, _, _ = manager_context
    form = _form(db, owner, active_area, status=form_status)

    edited = client.put(
        f"/api/v1/forms/{form.id}", json={"title": "Invalid status edit"}
    )
    submitted = client.post(
        f"/api/v1/staff/forms/{form.id}/submit",
        json={"expected_version": form.current_version},
    )

    assert edited.status_code == 403
    assert edited.json() == {"detail": edit_detail}
    assert submitted.status_code == submit_status
    assert submitted.json() == {"detail": submit_detail}
    db.refresh(form)
    assert form.status == form_status
    assert form.title == "Scoped form"
    assert db.query(FormWorkflow).filter(FormWorkflow.form_id == form.id).count() == 0


def test_manager_out_of_scope_update_does_not_reveal_pending_state(manager_context, db):
    client, _, owner, _, other_area, _ = manager_context
    form = _form(db, owner, other_area, status="pending_review")

    response = client.put(f"/api/v1/forms/{form.id}", json={"title": "Denied update"})
    submitted = client.post(
        f"/api/v1/staff/forms/{form.id}/submit",
        json={"expected_version": form.current_version},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions for this action"}
    assert submitted.status_code == 403
    assert submitted.json() == {"detail": "Insufficient permissions for this action"}


@pytest.mark.parametrize(
    ("action", "action_permissions", "body"),
    [
        ("unpublish", ["form:approve"], None),
        ("revert", ["form:create", "form:edit"], {"reason_notes": "Revise form"}),
    ],
)
def test_non_admin_can_return_published_to_draft_before_edit(
    action, action_permissions, body, manager_context, db, user_factory
):
    _, _, owner, active_area, _, _ = manager_context
    actor = user_factory()
    role = Role(
        id=uuid.uuid4(),
        name=f"us004_{uuid.uuid4().hex}",
        permissions=[
            "form:read",
            "form:read_unpublished:any",
            "form:edit:own",
            *action_permissions,
        ],
        is_active=True,
    )
    db.add(role)
    db.add(UserRole(id=uuid.uuid4(), user_id=actor.id, role_id=role.id))
    form = _form(
        db, actor if action == "unpublish" else owner, active_area, status="published"
    )
    db.flush()

    def _acting_user(_request: Request) -> TokenData:
        return TokenData(
            sub=str(actor.id),
            email=actor.email,
            name="Unpublish Actor",
            roles=[role.name],
            token_type="access",
            permissions=role.permissions,
        )

    manager_override = app.dependency_overrides[get_current_user]
    app.dependency_overrides[get_current_user] = _acting_user
    try:
        client = TestClient(app)
        blocked_edit = client.put(
            f"/api/v1/forms/{form.id}", json={"title": "Too early"}
        )
        transitioned = client.post(f"/api/v1/staff/forms/{form.id}/{action}", json=body)
        edited = client.put(
            f"/api/v1/forms/{form.id}", json={"title": "After unpublish"}
        )
    finally:
        app.dependency_overrides[get_current_user] = manager_override

    assert blocked_edit.status_code == 403
    assert transitioned.status_code == 200
    assert transitioned.json()["status"] == "draft"
    assert edited.status_code == 200
    db.refresh(form)
    assert form.created_by_id == actor.id
    assert form.status == "draft"
    assert form.title == "After unpublish"


def test_manager_owner_cannot_update_archived_form(manager_context, db):
    client, manager, _, active_area, _, _ = manager_context
    form = _form(db, manager, active_area, status="archived")

    response = client.put(f"/api/v1/forms/{form.id}", json={"title": "Not editable"})

    assert response.status_code == 403
    db.refresh(form)
    assert form.status == "archived"
    assert form.title == "Scoped form"


def test_manager_cannot_call_restricted_form_or_admin_apis(manager_context, db):
    client, manager, owner, active_area, _, _ = manager_context
    draft = _form(db, owner, active_area)
    pending = _form(db, owner, active_area, status="pending_review")
    published = _form(db, owner, active_area, status="published")
    archived = _form(db, owner, active_area, status="archived")
    requests = [
        (
            "POST",
            "/api/v1/forms",
            {
                "json": {
                    "title": "Denied create",
                    "description": "Cannot create a form",
                    "business_area_id": str(active_area.id),
                }
            },
        ),
        ("DELETE", f"/api/v1/forms/{draft.id}", {}),
        ("POST", f"/api/v1/forms/{published.id}/archive", {}),
        ("POST", f"/api/v1/staff/forms/{published.id}/archive", {}),
        ("POST", f"/api/v1/staff/forms/{published.id}/unpublish", {}),
        (
            "POST",
            f"/api/v1/staff/forms/{published.id}/revert",
            {
                "json": {"reason_notes": "Denied revert"},
            },
        ),
        ("POST", f"/api/v1/forms/{archived.id}/unarchive", {}),
        ("POST", f"/api/v1/staff/forms/{archived.id}/restore", {}),
        ("POST", f"/api/v1/staff/forms/{pending.id}/approve", {}),
        (
            "POST",
            f"/api/v1/staff/forms/{pending.id}/reject",
            {
                "json": {"reason_notes": "Denied reject"},
            },
        ),
        ("POST", f"/api/v1/staff/forms/{pending.id}/publish", {}),
        ("GET", f"/api/v1/staff/forms/{draft.id}/audit/summary", {}),
        ("GET", f"/api/v1/staff/forms/{draft.id}/audit/events", {}),
        ("GET", f"/api/v1/staff/forms/{pending.id}/workflow-history", {}),
        ("GET", "/api/v1/staff/forms/pending-approvals", {}),
        ("GET", "/api/v1/admin/users", {}),
        (
            "PUT",
            f"/api/v1/admin/users/{manager.id}/roles",
            {
                "json": {"role_ids": []},
            },
        ),
    ]

    for method, path, options in requests:
        response = client.request(method, path, **options)
        assert response.status_code == 403, (method, path, response.text)
        assert all(
            str(form.id) not in response.text and form.title not in response.text
            for form in (draft, pending, published, archived)
        )

    for form, form_status in (
        (draft, "draft"),
        (pending, "pending_review"),
        (published, "published"),
        (archived, "archived"),
    ):
        db.refresh(form)
        assert form.status == form_status
        assert form.deleted_at is None


@patch("backend.routes.forms.s3_service.stream_object")
def test_manager_cannot_download_out_of_scope_or_archived_attachments(
    mock_stream, manager_context, db
):
    mock_stream.return_value = iter([b"pdf bytes"])
    client, _, owner, active_area, other_area, deleted_area = manager_context
    forms = [
        (_form(db, owner, other_area), 403),
        (_form(db, owner, other_area, status="pending_review"), 403),
        (_form(db, owner, None), 403),
        (_form(db, owner, deleted_area), 403),
        (_form(db, owner, active_area, status="archived"), 404),
    ]

    for form, expected_status in forms:
        response = client.get(f"/api/v1/forms/{form.id}/file")
        assert response.status_code == expected_status
        assert str(form.id) not in response.text
        assert "uploads/us004.pdf" not in response.text

    mock_stream.assert_not_called()
    assert db.query(AuditLog).filter(AuditLog.action == "FORM_DOWNLOAD").count() == 0


@patch("backend.routes.forms.s3_service.stream_object")
def test_manager_can_download_scoped_draft_and_published_attachment(
    mock_stream, manager_context, db
):
    client, manager, owner, active_area, other_area, _ = manager_context
    scoped_draft = _form(db, owner, active_area)
    published = _form(db, owner, other_area, status="published")
    mock_stream.side_effect = lambda _key: iter([b"pdf bytes"])

    for form in (scoped_draft, published):
        response = client.get(f"/api/v1/forms/{form.id}/file")
        assert response.status_code == 200
        assert response.content == b"pdf bytes"
        assert response.headers["cache-control"] == "private, no-store"
        assert (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_id == str(form.id),
                AuditLog.action == "FORM_DOWNLOAD",
                AuditLog.user_id == manager.id,
            )
            .count()
            == 1
        )

    assert mock_stream.call_count == 2


def test_manager_autocomplete_only_suggests_readable_forms(manager_context, db):
    client, _, owner, active_area, other_area, deleted_area = manager_context
    cases = [
        (active_area, "draft", "active draft", True),
        (active_area, "pending_review", "active pending", True),
        (other_area, "published", "published elsewhere", True),
        (other_area, "draft", "other draft", False),
        (other_area, "pending_review", "other pending", False),
        (active_area, "archived", "archived", False),
        (deleted_area, "draft", "deleted area", False),
        (None, "draft", "no area", False),
    ]
    expected = set()
    for area, form_status, label, readable in cases:
        title = f"ScopedSuggestion {label}"
        keyword = f"ScopedSuggestion keyword {label}"
        form = _form(db, owner, area, status=form_status, title=title)
        form.keywords = [keyword]
        if readable:
            expected.update((title, keyword))
    db.flush()

    response = client.get(
        "/api/v1/forms/autocomplete",
        params={"q": "ScopedSuggestion", "max_suggestions": 10},
    )

    assert response.status_code == 200
    assert set(response.json()["suggestions"]) == expected


def test_manager_autocomplete_scopes_form_number_suggestions(manager_context, db):
    client, _, owner, active_area, other_area, deleted_area = manager_context
    prefix = FormNumberPrefix(
        id=uuid.uuid4(),
        prefix=f"U{uuid.uuid4().hex[:4].upper()}",
        description="US-004 scope test",
        current_sequence=0,
        padding_length=4,
        max_number_length=10,
        is_case_sensitive=False,
        is_active=True,
    )
    db.add(prefix)
    db.flush()
    cases = [
        (active_area, "draft", True),
        (active_area, "pending_review", True),
        (other_area, "published", True),
        (other_area, "draft", False),
        (active_area, "archived", False),
        (deleted_area, "draft", False),
        (None, "draft", False),
    ]
    expected = set()
    for index, (area, form_status, readable) in enumerate(cases, start=1):
        number = f"{prefix.prefix}500{index}"
        reservation = FormNumberReservation(
            id=uuid.uuid4(),
            prefix_id=prefix.id,
            form_number=f"500{index}",
            full_form_number=number,
            numbering_method="auto_generated",
            status="approved",
            reserved_by_id=owner.id,
        )
        db.add(reservation)
        db.flush()
        form = _form(db, owner, area, status=form_status)
        form.form_number_reservation_id = reservation.id
        if readable:
            expected.add(number)
    db.flush()

    response = client.get(
        "/api/v1/forms/autocomplete",
        params={"q": f"{prefix.prefix}500", "max_suggestions": 10},
    )

    assert response.status_code == 200
    assert set(response.json()["suggestions"]) == expected


def test_manager_autocomplete_treats_wildcards_as_literals(manager_context, db):
    client, _, owner, active_area, _, _ = manager_context
    cases = (
        ("Scoped%Literal", "ScopedXLiteral", "Scoped%"),
        ("Scoped_Literal", "ScopedXLiteral", "Scoped_"),
        ("Scoped\\Literal", "ScopedXLiteral", "Scoped\\"),
    )
    for matching, other, query in cases:
        _form(db, owner, active_area, title=matching)
        _form(db, owner, active_area, title=other)
        response = client.get("/api/v1/forms/autocomplete", params={"q": query})
        assert response.status_code == 200
        assert response.json()["suggestions"] == [matching]


@pytest.mark.parametrize(
    ("actual_status", "other_area_at_lock"),
    [("draft", True), ("published", False), ("archived", False)],
)
def test_update_rechecks_locked_status_and_scope(
    actual_status, other_area_at_lock, manager_context, db
):
    client, _, owner, active_area, other_area, _ = manager_context
    form = _form(
        db,
        owner,
        other_area if other_area_at_lock else active_area,
        status=actual_status,
    )
    initial_title = form.title
    stale_form = SimpleNamespace(
        status="draft", business_area_id=active_area.id, created_by_id=owner.id
    )

    with patch.object(FormService, "get_form_by_id", side_effect=[stale_form, form]):
        response = client.put(
            f"/api/v1/forms/{form.id}", json={"title": "Unauthorized change"}
        )

    assert response.status_code == 403
    db.refresh(form)
    assert form.title == initial_title
    assert form.status == actual_status
    assert (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == str(form.id), AuditLog.action == "UPDATE")
        .count()
        == 0
    )


@pytest.mark.parametrize("new_area", ["other", "deleted", "none"])
def test_submit_rechecks_locked_business_area(new_area, manager_context, db):
    client, manager, owner, active_area, other_area, deleted_area = manager_context
    form = _form(db, owner, active_area)
    areas = {"other": other_area, "deleted": deleted_area, "none": None}
    target_area = areas[new_area]
    original_get = FormService._get_form_for_transition

    def _move_form_before_lock(session, form_id, lock=True):
        session.execute(
            sa_update(Form)
            .where(Form.id == form_id)
            .values(business_area_id=target_area.id if target_area else None)
        )
        return original_get(session, form_id, lock=lock)

    with patch.object(FormService, "_get_form_for_transition", _move_form_before_lock):
        response = client.post(
            f"/api/v1/staff/forms/{form.id}/submit",
            json={"expected_version": form.current_version},
        )

    assert response.status_code == 403
    assert str(form.id) not in response.text
    db.refresh(form)
    assert form.status == "draft"
    assert db.query(FormWorkflow).filter(FormWorkflow.form_id == form.id).count() == 0
    assert (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_id == str(form.id), AuditLog.action == "WORKFLOW_TRANSITION"
        )
        .count()
        == 0
    )


@patch("backend.routes.forms.s3_service.upload_file")
def test_manager_cannot_upload_unscoped_form_attachment(mock_upload, manager_context):
    client, _, _, _, _, _ = manager_context
    mock_upload.return_value = ("uploads/us004.pdf", "uploads/us004.pdf")

    response = client.post(
        "/api/v1/forms/upload",
        files={"file": ("us004.pdf", b"pdf bytes", "application/pdf")},
    )

    assert response.status_code == 403
    mock_upload.assert_not_called()


@patch("backend.services.s3_service.ensure_bucket_exists")
@patch("backend.services.s3_service._get_s3_client")
def test_scoped_s3_upload_creates_form_bound_safe_key(mock_client, mock_bucket):
    form_id = uuid.uuid4()
    key, reference = s3_service.upload_file(
        b"pdf bytes", "document.PDF", "application/pdf", form_id=form_id
    )

    assert key == reference
    assert key.startswith(f"uploads/forms/{form_id}/")
    assert key.endswith(".pdf")
    assert mock_client.return_value.put_object.call_args.kwargs["Key"] == key
    mock_bucket.assert_called_once()

    unsafe_key, _ = s3_service.upload_file(
        b"pdf bytes", "document.bad+unsafe", "application/pdf", form_id=form_id
    )
    assert unsafe_key.startswith(f"uploads/forms/{form_id}/")
    assert (
        str(uuid.UUID(unsafe_key.rsplit("/", 1)[-1])) == unsafe_key.rsplit("/", 1)[-1]
    )


@patch("backend.routes.forms.s3_service.upload_file")
def test_manager_upload_requires_an_editable_scoped_draft(
    mock_upload, manager_context, db
):
    client, _, owner, active_area, other_area, deleted_area = manager_context
    draft = _form(db, owner, active_area)
    denied = [
        (_form(db, owner, other_area), 403),
        (_form(db, owner, None), 403),
        (_form(db, owner, deleted_area), 403),
        (_form(db, owner, active_area, status="pending_review"), 403),
        (_form(db, owner, active_area, status="published"), 403),
        (_form(db, owner, active_area, status="archived"), 404),
    ]
    key = f"uploads/forms/{draft.id}/{uuid.uuid4()}.pdf"
    mock_upload.return_value = (key, key)

    for form, expected_status in denied:
        response = client.post(
            f"/api/v1/forms/{form.id}/upload",
            files={"file": ("us004.pdf", b"pdf bytes", "application/pdf")},
        )
        assert response.status_code == expected_status
        assert str(form.id) not in response.text
    mock_upload.assert_not_called()

    response = client.post(
        f"/api/v1/forms/{draft.id}/upload",
        files={"file": ("us004.pdf", b"pdf bytes", "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["url"] == key
    assert mock_upload.call_args.kwargs["form_id"] == draft.id


@patch("backend.routes.forms._MAX_SCOPED_ATTACHMENT_BYTES", 4, create=True)
@patch("backend.routes.forms.s3_service.upload_file")
def test_scoped_upload_rejects_oversize_payload_before_storage(
    mock_upload, manager_context, db
):
    client, _, owner, active_area, _, _ = manager_context
    draft = _form(db, owner, active_area)

    response = client.post(
        f"/api/v1/forms/{draft.id}/upload",
        files={"file": ("large.pdf", b"pdf bytes", "application/pdf")},
    )

    assert response.status_code == 413
    mock_upload.assert_not_called()


@patch("backend.services.forms.s3_service.delete_file")
def test_manager_cannot_attach_foreign_key_or_delete_shared_attachment(
    mock_delete, manager_context, db
):
    client, manager, owner, active_area, other_area, _ = manager_context
    draft = _form(db, owner, active_area)
    published = _form(db, owner, other_area, status="published")
    shared = _form(db, owner, other_area, status="published")
    foreign_key = f"uploads/forms/{published.id}/{uuid.uuid4()}.pdf"
    published.form_attachment_url = foreign_key
    shared.form_attachment_url = "https://storage.example/uploads/us004.pdf"
    db.flush()

    forbidden = client.put(
        f"/api/v1/forms/{draft.id}",
        json={"form_attachment_url": foreign_key},
    )

    assert forbidden.status_code == 403
    db.refresh(draft)
    assert draft.form_attachment_url == "uploads/us004.pdf"
    mock_delete.assert_not_called()

    scoped_key = f"uploads/forms/{draft.id}/{uuid.uuid4()}.pdf"
    allowed = client.put(
        f"/api/v1/forms/{draft.id}",
        json={"form_attachment_url": scoped_key},
    )

    assert allowed.status_code == 200
    db.refresh(draft)
    assert draft.form_attachment_url == scoped_key
    assert (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_id == str(draft.id),
            AuditLog.action == "UPDATE",
            AuditLog.user_id == manager.id,
        )
        .count()
        == 1
    )
    mock_delete.assert_not_called()

    create_role = Role(
        id=uuid.uuid4(),
        name=f"creator_{uuid.uuid4().hex}",
        permissions=["form:create"],
        is_active=True,
    )
    db.add(create_role)
    db.add(UserRole(id=uuid.uuid4(), user_id=manager.id, role_id=create_role.id))
    db.flush()

    mixed_role_update = client.put(
        f"/api/v1/forms/{draft.id}",
        json={"form_attachment_url": foreign_key},
    )
    mixed_role_create = client.post(
        "/api/v1/forms",
        json={
            "title": "Cannot reuse a Published attachment",
            "description": "Cannot claim another form's file",
            "business_area_id": str(active_area.id),
            "form_source": "Download",
            "form_attachment_url": foreign_key,
        },
    )

    assert mixed_role_update.status_code == 403
    assert mixed_role_create.status_code == 400
    assert str(published.id) not in mixed_role_create.text
    db.refresh(draft)
    assert draft.form_attachment_url == scoped_key


def test_scoped_key_cannot_be_claimed_by_another_form_before_save(manager_context, db):
    client, manager, owner, active_area, _, _ = manager_context
    draft = _form(db, owner, active_area)
    key = f"uploads/forms/{draft.id}/{uuid.uuid4()}.pdf"
    creator_role = Role(
        id=uuid.uuid4(),
        name=f"creator_{uuid.uuid4().hex}",
        permissions=["form:create"],
        is_active=True,
    )
    db.add(creator_role)
    db.add(UserRole(id=uuid.uuid4(), user_id=manager.id, role_id=creator_role.id))
    db.flush()

    claimed = client.post(
        "/api/v1/forms",
        json={
            "title": "Cannot claim a scoped key",
            "description": "Cannot attach a form-bound key to another form",
            "business_area_id": str(active_area.id),
            "form_source": "Download",
            "form_attachment_url": key,
        },
    )

    assert claimed.status_code == 400
    assert db.query(Form).filter(Form.form_attachment_url == key).count() == 0


@patch("backend.services.forms.s3_service.delete_file")
@patch("backend.services.s3_service._get_s3_client")
@patch("backend.services.s3_service.ensure_bucket_exists")
def test_manager_uploads_then_saves_file_on_scoped_draft(
    mock_bucket, mock_s3_client, mock_delete, manager_context, db
):
    client, manager, owner, active_area, _, _ = manager_context
    draft = _form(db, owner, active_area)
    upload = client.post(
        f"/api/v1/forms/{draft.id}/upload",
        files={"file": ("replacement.pdf", b"pdf bytes", "application/pdf")},
    )

    assert upload.status_code == 201
    key = upload.json()["url"]
    assert key.startswith(f"uploads/forms/{draft.id}/")
    mock_bucket.assert_called_once()
    assert mock_s3_client.return_value.put_object.call_args.kwargs["Key"] == key

    saved = client.put(
        f"/api/v1/forms/{draft.id}",
        json={
            "form_source": "Download",
            "form_attachment_url": key,
            "form_attachment_filename": upload.json()["filename"],
            "file_type": upload.json()["file_type"],
        },
    )

    assert saved.status_code == 200
    db.refresh(draft)
    assert draft.form_attachment_url == key
    assert (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_id == str(draft.id),
            AuditLog.action == "UPDATE",
            AuditLog.user_id == manager.id,
        )
        .count()
        == 1
    )
    mock_delete.assert_not_called()
