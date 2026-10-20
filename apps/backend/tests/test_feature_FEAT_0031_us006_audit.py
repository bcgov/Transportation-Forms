"""US-006: privileged, durable and non-leaking form activity history."""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import (
    BusinessArea,
    Form,
    FormActivityEvent,
    Role,
    UserRole,
)
from backend.services.forms import FormService, _record_form_activity


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def _client(db, user, permissions):
    role = Role(
        name=f"us006_{uuid.uuid4().hex}",
        permissions=permissions,
        is_active=True,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        sub=str(user.id),
        email=user.email,
        name="Claim not used",
        roles=["admin"],
        permissions=["form:audit", "form:edit"],
        token_type="access",
    )
    return TestClient(app)


def _area(db):
    area = BusinessArea(name=f"US006 area {uuid.uuid4().hex}")
    db.add(area)
    db.flush()
    return area


def _form(db, user, area):
    return FormService.create_form(
        db,
        title="First",
        description="Description",
        is_public=False,
        keywords=[],
        business_area_id=area.id,
        created_by_id=user.id,
    )


def _url(form):
    return f"/api/v1/staff/forms/{form.id}/audit"


def test_creation_changed_save_noop_and_last_editor(db, user_factory):
    user = user_factory(first_name="Original", last_name="Name")
    area = _area(db)
    form = _form(db, user, area)
    client = _client(db, user, ["form:audit", "form:edit"])
    assert client.get(_url(form) + "/summary").json() == {
        "last_edited_by": None,
    }
    events = client.get(_url(form) + "/events").json()["events"]
    assert events[0]["event_name"] == "Form created"
    FormService.update_form(db, form.id, user.id, title="First")
    assert db.query(FormActivityEvent).filter_by(form_id=form.id).count() == 1
    assert form.current_version == 0

    FormService.update_form(
        db,
        form.id,
        user.id,
        title="Second",
        form_source="Download",
        form_attachment_url="https://storage.example/uploads/historical.pdf"
        "?token=signed",
        form_attachment_filename="historical.pdf",
    )
    user.first_name = "Renamed"
    db.flush()
    summary = client.get(_url(form) + "/summary").json()
    assert summary["last_edited_by"]["actor_label"] == "Original Name"
    assert summary["last_edited_by"]["occurred_at"].endswith("+00:00")
    page = client.get(_url(form) + "/events").json()
    assert [e["event_name"] for e in page["events"]] == [
        "Form saved",
        "Form created",
    ]
    assert "old_value" not in str(page["events"])
    detail = client.get(_url(form) + "/events/" + page["events"][0]["id"])
    assert detail.status_code == 200
    changes = detail.json()["changes"]
    attachment_field = "form_attachment_url"
    attachment = next(c for c in changes if c["field"] == attachment_field)
    assert attachment["new_value"] == "uploads/historical.pdf"
    assert "signed" not in detail.text
    assert detail.headers["cache-control"] == "private, no-store"


def test_audit_requires_both_live_permissions_and_ignores_ownership(
    db,
    user_factory,
):
    owner = user_factory()
    form = _form(db, owner, _area(db))
    for permissions in (["form:audit"], ["form:edit"], ["form:read"], []):
        other = user_factory()
        client = _client(db, other, permissions)
        for path in (
            "/summary",
            "/events",
            f"/events/{uuid.uuid4()}",
        ):
            result = client.get(_url(form) + path)
            assert result.status_code == 403
            assert result.json() == {
                "detail": "Insufficient permissions for this action",
            }
        app.dependency_overrides.pop(get_current_user)
        app.dependency_overrides.pop(get_db)
    client = _client(db, other, ["form:audit", "form:edit"])
    assert client.get(_url(form) + "/events").status_code == 200
    unknown = str(uuid.uuid4())
    for path in ("/summary", "/events", f"/events/{uuid.uuid4()}"):
        missing = client.get(f"/api/v1/staff/forms/{unknown}/audit" + path)
        form.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.flush()
        deleted = client.get(_url(form) + path)
        assert deleted.status_code == missing.status_code == 404
        assert deleted.json() == missing.json()


def test_cursor_is_stable_and_restricted_to_form(db, user_factory):
    actor = user_factory()
    area = _area(db)
    form = _form(db, actor, area)
    client = _client(db, actor, ["form:audit", "form:edit"])
    for number in range(21):
        FormService.update_form(db, form.id, actor.id, title=f"Title {number}")
    first = client.get(_url(form) + "/events").json()
    assert len(first["events"]) == 10
    second = client.get(
        _url(form) + "/events",
        params={"cursor": first["next_cursor"]},
    ).json()
    assert len(second["events"]) == 10
    third = client.get(
        _url(form) + "/events",
        params={"cursor": second["next_cursor"]},
    ).json()
    assert len(third["events"]) == 2
    assert third["next_cursor"] is None
    ids = []
    for page in (first, second, third):
        ids.extend(event["id"] for event in page["events"])
    assert len(ids) == len(set(ids)) == 22
    other = _form(db, actor, area)
    invalid = client.get(
        _url(other) + "/events",
        params={"cursor": first["next_cursor"]},
    )
    assert invalid.status_code == 400


def test_workflow_is_atomic_and_does_not_change_last_editor(db, user_factory):
    actor = user_factory(first_name="Editor", last_name="Example")
    form = _form(db, actor, _area(db))
    client = _client(db, actor, ["form:audit", "form:edit"])
    FormService.update_form(db, form.id, actor.id, title="Edited")
    last = client.get(_url(form) + "/summary").json()["last_edited_by"]
    FormService.submit_form_for_review(db, form.id, actor.id)
    assert client.get(_url(form) + "/summary").json()["last_edited_by"] == last
    page = client.get(_url(form) + "/events").json()["events"]
    assert page[0]["event_name"] == "Form submitted"
    detail = client.get(_url(form) + "/events/" + page[0]["id"]).json()
    assert detail["changes"] == [
        {
            "field": "status",
            "old_value": "draft",
            "new_value": "pending_review",
        }
    ]


def test_legacy_unpublish_is_not_an_approved_activity_event(db, user_factory):
    actor = user_factory()
    form = _form(db, actor, _area(db))
    FormService.submit_form_for_review(db, form.id, actor.id)
    FormService.approve_form(db, form.id, actor.id, allow_self_approve=True)
    count = db.query(FormActivityEvent).filter_by(form_id=form.id).count()

    FormService.unpublish_form(db, form.id, actor.id)

    assert form.status == "draft"
    remaining = db.query(FormActivityEvent).filter_by(form_id=form.id).count()
    assert remaining == count


def test_email_fallback_and_secret_redaction_in_details(db, user_factory):
    actor = user_factory(first_name="", last_name="")
    form = _form(db, actor, _area(db))
    client = _client(db, actor, ["form:audit", "form:edit"])
    source_url = "https://user:password@example.org/source"
    FormService.update_form(
        db,
        form.id,
        actor.id,
        form_source_url=source_url + "?token=secret",
    )
    FormService.submit_form_for_review(db, form.id, actor.id)
    FormService.reject_form(
        db,
        form.id,
        actor.id,
        " https://user:password@example.org/reject?signature=signed ",
    )
    page = client.get(_url(form) + "/events").json()["events"]
    assert page[0]["actor_label"] == actor.email
    detail = client.get(_url(form) + "/events/" + page[0]["id"])
    assert detail.json()["reason"] == "https://example.org/reject"
    save = client.get(_url(form) + "/events/" + page[2]["id"])
    changes = save.json()["changes"]
    field = "form_source_url"
    source = next(c for c in changes if c["field"] == field)
    assert source["new_value"] == "https://example.org/source"
    assert "password" not in detail.text + save.text
    assert "signed" not in detail.text + save.text


def test_unauthed_and_unresolvable_actor_fail_closed(db, user_factory):
    user = user_factory()
    form = _form(db, user, _area(db))
    app.dependency_overrides[get_db] = lambda: db
    assert TestClient(app).get(_url(form) + "/events").status_code == 401
    with Session(
        bind=db.connection(),
        join_transaction_mode="create_savepoint",
    ) as session:
        missing = uuid.uuid4()
        with pytest.raises(RuntimeError, match="Audit actor unavailable"):
            _record_form_activity(
                session,
                form,
                missing,
                "Form saved",
                old={"title": "First"},
                new={"title": "Denied"},
            )
        session.expire_all()
        assert session.get(Form, form.id).title == "First"


def test_audit_failure_rolls_back_save_and_workflow(db, user_factory):
    actor = user_factory()
    with Session(
        bind=db.connection(),
        join_transaction_mode="create_savepoint",
    ) as session:
        form = _form(session, actor, _area(session))
        form_id = form.id
        original_add = session.add

        def reject_event(instance):
            if isinstance(instance, FormActivityEvent):
                raise RuntimeError("audit store unavailable")
            return original_add(instance)

        with patch.object(session, "add", side_effect=reject_event):
            with pytest.raises(RuntimeError, match="audit store unavailable"):
                FormService.update_form(
                    session,
                    form_id,
                    actor.id,
                    title="Not persisted",
                )
        session.expire_all()
        assert session.get(Form, form_id).title == "First"
        history = session.query(FormActivityEvent).filter_by(form_id=form_id)
        count = history.count()
        assert count == 1
        with patch.object(session, "add", side_effect=reject_event):
            with pytest.raises(RuntimeError, match="audit store unavailable"):
                FormService.submit_form_for_review(session, form_id, actor.id)
        session.expire_all()
        assert session.get(Form, form_id).status == "draft"
        count = history.count()
        assert count == 1


def test_creation_requires_durable_audit(db, user_factory):
    actor = user_factory()
    with Session(
        bind=db.connection(),
        join_transaction_mode="create_savepoint",
    ) as session:
        area = _area(session)
        original_add = session.add

        def reject_event(instance):
            if isinstance(instance, FormActivityEvent):
                raise RuntimeError("audit store unavailable")
            return original_add(instance)

        with patch.object(session, "add", side_effect=reject_event):
            with pytest.raises(RuntimeError, match="audit store unavailable"):
                _form(session, actor, area)
        assert session.query(Form).filter(Form.title == "First").count() == 0
        assert session.query(FormActivityEvent).count() == 0


def test_save_api_reports_safe_error_on_required_audit_failure(
    db,
    user_factory,
):
    actor = user_factory()
    with Session(
        bind=db.connection(),
        join_transaction_mode="create_savepoint",
    ) as session:
        form = _form(session, actor, _area(session))
        form_id = form.id
        client = _client(
            session,
            actor,
            ["form:edit"],
        )
        original_add = session.add

        def reject_event(instance):
            if isinstance(instance, FormActivityEvent):
                raise RuntimeError("private audit database details")
            return original_add(instance)

        with patch.object(session, "add", side_effect=reject_event):
            save = client.put(
                f"/api/v1/forms/{form_id}",
                json={"title": "Not persisted"},
            )
        assert save.status_code == 500
        assert save.json() == {"detail": "Failed to save form"}
        session.expire_all()
        assert session.get(Form, form_id).title == "First"
        assert session.get(Form, form_id).status == "draft"
