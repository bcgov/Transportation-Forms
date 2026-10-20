"""Equivalent effective-date instants do not create false form edits."""

import uuid
from datetime import datetime

import pytest

from backend.models import BusinessArea, Form, FormActivityEvent


def _create_form(client, db, headers, effective_date):
    area = BusinessArea(name=f"Audit date area {uuid.uuid4().hex}")
    db.add(area)
    db.flush()
    response = client.post(
        "/api/v1/forms",
        json={
            "title": "Effective date audit",
            "description": "Date normalization regression",
            "business_area_id": str(area.id),
            "effective_date": effective_date,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize(
    "created_date",
    ["2026-10-20", "2026-10-19T17:00:00-07:00"],
)
@pytest.mark.parametrize(
    "equivalent_date",
    [
        "2026-10-20T00:00:00Z",
        "2026-10-19T17:00:00-07:00",
        "2026-10-20T02:00:00+02:00",
    ],
)
def test_resaving_equivalent_instant_is_noop(
    client, db, admin_token_headers, created_date, equivalent_date
):
    form_id = _create_form(client, db, admin_token_headers, created_date)
    stored = db.get(Form, uuid.UUID(form_id))
    assert stored.effective_date == datetime(2026, 10, 20)
    assert stored.effective_date.tzinfo is None

    response = client.put(
        f"/api/v1/forms/{form_id}",
        json={"effective_date": equivalent_date, "expected_version": 0},
        headers=admin_token_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["current_version"] == 0
    db.refresh(stored)
    assert stored.effective_date == datetime(2026, 10, 20)
    events = db.query(FormActivityEvent).filter_by(form_id=stored.id).all()
    assert len(events) == 1
    assert events[0].event_name == "Form created"
    summary = client.get(
        f"/api/v1/staff/forms/{form_id}/audit/summary",
        headers=admin_token_headers,
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["last_edited_by"] is None


def test_different_instant_advances_version_and_audits_date(
    client, db, admin_token_headers
):
    form_id = _create_form(client, db, admin_token_headers, "2026-10-20")

    response = client.put(
        f"/api/v1/forms/{form_id}",
        json={
            "effective_date": "2026-10-19T19:00:00-07:00",
            "expected_version": 0,
        },
        headers=admin_token_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["current_version"] == 1
    stored = db.get(Form, uuid.UUID(form_id))
    assert stored.effective_date == datetime(2026, 10, 20, 2)
    events = (
        db.query(FormActivityEvent)
        .filter_by(form_id=stored.id)
        .order_by(FormActivityEvent.occurred_at.desc())
        .all()
    )
    assert [event.event_name for event in events] == ["Form saved", "Form created"]
    assert events[0].changed_fields == ["effective_date"]
    assert events[0].old_values == {"effective_date": "2026-10-20T00:00:00"}
    assert events[0].new_values == {"effective_date": "2026-10-20T02:00:00"}


def test_equivalent_date_with_real_edit_preserves_last_editor_on_next_noop(
    client, db, admin_token_headers
):
    form_id = _create_form(client, db, admin_token_headers, "2026-10-20")
    path = f"/api/v1/forms/{form_id}"
    audit_path = f"/api/v1/staff/forms/{form_id}/audit/summary"

    changed = client.put(
        path,
        json={
            "title": "Updated title",
            "effective_date": "2026-10-20T00:00:00Z",
            "expected_version": 0,
        },
        headers=admin_token_headers,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["current_version"] == 1
    saved = (
        db.query(FormActivityEvent)
        .filter_by(form_id=uuid.UUID(form_id), event_name="Form saved")
        .one()
    )
    assert saved.changed_fields == ["title"]
    last_editor = client.get(audit_path, headers=admin_token_headers).json()
    assert last_editor["last_edited_by"] is not None

    unchanged = client.put(
        path,
        json={
            "effective_date": "2026-10-19T17:00:00-07:00",
            "expected_version": 1,
        },
        headers=admin_token_headers,
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["current_version"] == 1
    assert (
        db.query(FormActivityEvent).filter_by(form_id=uuid.UUID(form_id)).count() == 2
    )
    assert client.get(audit_path, headers=admin_token_headers).json() == last_editor
