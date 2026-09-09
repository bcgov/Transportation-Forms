"""FEAT-0030 US-010: Staff Forms search includes current Business Area names."""

from datetime import datetime, timezone
import uuid

import pytest

from backend.models import BusinessArea, Form
from backend.services.forms import FormService


def _make_form(
    db,
    user,
    *,
    title,
    description="Description",
    keywords=None,
    business_area=None,
    created_at=None,
):
    form = Form(
        id=uuid.uuid4(),
        title=title,
        description=description,
        status="published",
        is_public=False,
        current_version=0,
        keywords=keywords or [],
        created_by_id=user.id,
        business_area_id=business_area.id if business_area else None,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(form)
    db.flush()
    return form


def _search(db, query):
    forms, total = FormService.list_forms(db, q=query, limit=100)
    return {form.id for form in forms}, total


@pytest.mark.integration
def test_business_area_name_is_searchable_with_existing_full_text_semantics(
    db, user_factory
):
    user = user_factory()
    area = BusinessArea(id=uuid.uuid4(), name="Applications Services")
    db.add(area)
    db.flush()
    form = _make_form(
        db,
        user,
        title="Permit Intake",
        description="General request information",
        keywords=["intake"],
        business_area=area,
    )

    result_ids, total = _search(db, "applications")

    assert total == 1
    assert result_ids == {form.id}

    result_ids, total = _search(db, "lication")
    assert total == 0
    assert result_ids == set()


@pytest.mark.integration
def test_non_deleted_area_is_searchable_but_deleted_area_is_not(db, user_factory):
    user = user_factory()
    inactive = BusinessArea(id=uuid.uuid4(), name="Inactive Licensing")
    deleted = BusinessArea(
        id=uuid.uuid4(),
        name="Deleted Licensing",
        deleted_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add_all([inactive, deleted])
    db.flush()
    inactive_form = _make_form(
        db, user, title="Inactive Form", business_area=inactive
    )
    deleted_form = _make_form(
        db, user, title="Deleted Form", business_area=deleted
    )

    result_ids, total = _search(db, "licensing")

    assert total == 1
    assert result_ids == {inactive_form.id}
    assert deleted_form.id not in result_ids


@pytest.mark.integration
def test_renamed_area_uses_only_current_name(db, user_factory):
    user = user_factory()
    area = BusinessArea(id=uuid.uuid4(), name="Legacy Operations")
    db.add(area)
    db.flush()
    form = _make_form(db, user, title="Unique Intake", business_area=area)

    area.name = "Current Operations"
    db.flush()

    current_ids, current_total = _search(db, "current")
    prior_ids, prior_total = _search(db, "legacy")

    assert current_total == 1
    assert current_ids == {form.id}
    assert prior_total == 0
    assert prior_ids == set()


@pytest.mark.integration
def test_business_area_search_preserves_filters_and_missing_area_safety(
    db, user_factory
):
    user = user_factory()
    area = BusinessArea(id=uuid.uuid4(), name="Road Safety")
    db.add(area)
    db.flush()
    matched = _make_form(db, user, title="Matched Form", business_area=area)
    _make_form(db, user, title="No Area Form")

    forms, total = FormService.list_forms(
        db, q="road", business_area_ids=[area.id], limit=100
    )

    assert total == 1
    assert [form.id for form in forms] == [matched.id]

    forms, total = FormService.list_forms(db, q="form", limit=100)
    assert total == 2
    assert total == len(forms)
    assert {form.title for form in forms} == {"Matched Form", "No Area Form"}


@pytest.mark.integration
def test_business_area_match_does_not_change_form_number_priority_or_autocomplete(
    db, user_factory
):
    user = user_factory()
    area = BusinessArea(id=uuid.uuid4(), name="Priority Services")
    db.add(area)
    db.flush()
    area_form = _make_form(db, user, title="Area Only", business_area=area)
    title_form = _make_form(db, user, title="Priority Policy")

    forms, total = FormService.list_forms(db, q="priority", limit=100)
    suggestions = FormService.get_autocomplete_suggestions(db, "priority")

    assert total == 2
    assert {form.id for form in forms} == {area_form.id, title_form.id}
    assert "Priority Services" not in suggestions
